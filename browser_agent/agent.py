"""
browser_agent/agent.py
-----------------------
Agente principal usando browser_use.
"""

import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


# ─── Motor principal: browser_use ────────────────────────────────────────────

async def ejecutar_con_browser_use(plan: dict, credenciales: dict, email_reporte: str) -> list:
    from browser_use import Agent
    from langchain_anthropic import ChatAnthropic

    todas = {**credenciales, **plan.get("credenciales_obtenidas", {})}
    origen   = plan.get("plataforma_origen", "")
    destino  = plan.get("plataforma_destino", "")
    objetivo = plan.get("objetivo", "Ejecutar el proceso aprendido")

    # FIX 3: incluir url_portal para que el agente sepa dónde navegar
    url_portal = plan.get("url_portal", "")
    url_line   = f"\nURL DEL PORTAL: {url_portal}" if url_portal else ""

    creds_texto = "\n".join([f"- {k}: {v}" for k, v in todas.items() if v])

    mapeo = plan.get("mapeo_campos", [])
    mapeo_texto = "\n".join([
        f"- '{m['campo_origen']}' en {origen} → '{m['campo_destino']}' en {destino}"
        for m in mapeo
    ]) if mapeo else "Aprende el mapeo observando la página"

    pasos_texto = "\n".join([
        f"{p['numero']}. [{p['accion'].upper()}] {p['intencion']}"
        + (f" → valor: {p['valor']}" if p.get('valor') else "")
        for p in plan.get("pasos", [])
    ])

    task = f"""
Eres un agente que automatiza procesos entre dos sistemas web para Arca Continental.

OBJETIVO: {objetivo}{url_line}

SISTEMAS:
- Origen: {origen}
- Destino: {destino}

CREDENCIALES DISPONIBLES:
{creds_texto if creds_texto else "Ninguna — infiere del contexto"}

MAPEO DE CAMPOS:
{mapeo_texto}

PASOS APRENDIDOS (guíate por la intención, no por coordenadas):
{pasos_texto}

INSTRUCCIONES:
1. Navega al portal indicado y ejecuta el proceso completo de principio a fin
2. Si un elemento no está visible, haz scroll para encontrarlo
3. Si algo falla, intenta una alternativa antes de rendirte
4. Al terminar, extrae los datos más importantes del resultado
5. NO pares hasta completar el objetivo o agotar opciones razonables
6. Reporta cada acción importante que realices
"""

    print(f"\n🤖 browser_use ejecutando: {objetivo}")
    print(f"   Sistemas: {origen} → {destino}\n")

    # FIX: usar model_name + anthropic_api_key (compatibles con browser-use 0.1.40)
    try:
        llm = ChatAnthropic(
            model_name="claude-opus-4-5",
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0,
        )
    except Exception:
        llm = ChatAnthropic(
            model="claude-opus-4-5",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )

    agent = Agent(task=task, llm=llm)

    try:
        result = await agent.run(max_steps=50)

        # FIX 4: extraer resultado real de AgentHistoryList
        resultado_texto = ""
        if hasattr(result, 'final_result') and result.final_result():
            resultado_texto = str(result.final_result())
        elif hasattr(result, 'all_results') and result.all_results:
            resultado_texto = str(result.all_results[-1])
        else:
            resultado_texto = str(result)

        print(f"\n✅ browser_use completó el proceso")
        print(f"   {resultado_texto[:300]}")
        estado = "ok"
    except Exception as e:
        resultado_texto = f"Error: {e}"
        print(f"\n❌ Error en browser_use: {e}")
        estado = "error"

    # Guardar reporte JSON
    reporte = {
        "objetivo":           objetivo,
        "plataforma_origen":  origen,
        "plataforma_destino": destino,
        "resultado":          resultado_texto,
        "fecha":              datetime.now().isoformat(),
        "motor":              "browser_use",
    }
    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/reporte.json", "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)

    return [{"paso": 1, "accion": "browser_use", "estado": estado,
             "datos_extraidos": resultado_texto}]


# ─── Entry point ─────────────────────────────────────────────────────────────

async def ejecutar(plan: dict, credenciales: dict, email_reporte: str) -> list:
    print(f"\n🤖 Ejecutando: {plan.get('objetivo')}")

    resultados = []
    motor = "browser_use"

    # FIX 2: capturar CUALQUIER excepción, no solo ImportError
    try:
        import browser_use  # noqa
        print("  ℹ️  browser_use disponible — ejecutando...")
        resultados = await ejecutar_con_browser_use(plan, credenciales, email_reporte)
        if not resultados:
            raise ValueError("browser_use devolvió lista vacía")
    except Exception as e:
        print(f"  ❌ browser_use falló ({type(e).__name__}: {e})")
        resultados = [{"paso": 1, "accion": "error", "estado": "error",
                       "datos_extraidos": str(e)}]
        motor = "error"

    ok = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\n{'─'*50}")
    print(f"  Motor    : {motor}")
    print(f"  Resultado: {ok}/{len(resultados)} pasos exitosos")

    # Datos extraídos para reporte
    datos_extraidos = {
        f"paso_{r['paso']}": r["datos_extraidos"]
        for r in resultados if r.get("datos_extraidos")
    }

    # Guardar en SQLite
    try:
        from database.db import guardar_sesion
        guardar_sesion(
            plan=plan,
            resultados=resultados,
            email=email_reporte,
            duracion_seg=None,
        )
        print("  💾 Guardado en SQLite")
    except Exception as e:
        print(f"  ⚠️  SQLite: {e}")

    # Generar Excel + ticket HTML
    try:
        from postprocessing.reporte import generar_excel, generar_ticket_html, guardar_ticket
        datos_reporte = {
            "objetivo":        plan.get("objetivo", "Proceso"),
            "origen":          plan.get("plataforma_origen", ""),
            "destino":         plan.get("plataforma_destino", ""),
            "resultados":      resultados,
            "datos_extraidos": datos_extraidos,
            "fecha":           datetime.now().isoformat(),
        }
        excel_path  = generar_excel(datos_reporte)
        ticket_html = generar_ticket_html(datos_reporte)
        ticket_path = guardar_ticket(ticket_html)
        print(f"  📊 Excel:  {excel_path}")
        print(f"  🎫 Ticket: {ticket_path}")
    except Exception as e:
        excel_path  = None
        ticket_path = None
        print(f"  ⚠️  Reportes: {e}")

    # Email
    _enviar_email(email_reporte, plan, resultados, datos_extraidos, excel_path)

    return resultados


def _enviar_email(destinatario: str, plan: dict, resultados: list,
                  datos: dict, excel_path: str = None):
    remitente = os.getenv("EMAIL_REMITENTE", "")
    password  = os.getenv("EMAIL_PASSWORD", "")
    if not remitente or not password or not destinatario:
        print("  📄 Email desactivado — agrega EMAIL_REMITENTE y EMAIL_PASSWORD al .env")
        return

    ok    = sum(1 for r in resultados if r["estado"] == "ok")
    total = len(resultados)
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")

    cuerpo = f"""
ArcFast — Arca Continental
Reporte de ejecución automática

Proceso : {plan.get('objetivo', '')}
Fecha   : {fecha}
Resultado: {ok}/{total} pasos exitosos

Datos extraídos:
{json.dumps(datos, indent=2, ensure_ascii=False)[:1500]}
"""
    msg = MIMEMultipart()
    msg["From"]    = remitente
    msg["To"]      = destinatario
    msg["Subject"] = f"ArcFast — Reporte {fecha} — {ok}/{total} pasos"
    msg.attach(MIMEText(cuerpo, "plain"))

    if excel_path and Path(excel_path).exists():
        with open(excel_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment; filename=reporte_arcfast.xlsx")
            msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(remitente, password)
            server.sendmail(remitente, destinatario, msg.as_string())
        print(f"  📧 Reporte enviado a {destinatario}")
    except Exception as e:
        print(f"  ⚠️  Email no enviado: {e}")