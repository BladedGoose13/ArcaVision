"""
browser_agent/agent.py
-----------------------
Agente principal usando browser_use exclusivamente.
Corre en un thread separado con su propio event loop para evitar
el NotImplementedError de asyncio en Windows con uvicorn.
"""

import asyncio
import concurrent.futures
import json
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _run_browser_use_sync(task: str, api_key: str) -> str:
    """
    Ejecuta browser_use Agent en un thread con su propio event loop.
    asyncio.run() crea un ProactorEventLoop en Windows, que sí soporta
    subprocesos — evita el NotImplementedError de SelectorEventLoop.
    """
    from browser_use import Agent
    from langchain_anthropic import ChatAnthropic

    async def _inner():
        llm   = ChatAnthropic(model="claude-opus-4-5", api_key=api_key)
        agent = Agent(task=task, llm=llm)
        result = await agent.run(max_steps=50)
        return str(result)

    return asyncio.run(_inner())


async def ejecutar_con_browser_use(plan: dict, credenciales: dict, email_reporte: str) -> list:
    todas   = {**credenciales, **plan.get("credenciales_obtenidas", {})}
    origen  = plan.get("plataforma_origen", "")
    destino = plan.get("plataforma_destino", "")
    objetivo = plan.get("objetivo", "Ejecutar el proceso aprendido")

    creds_texto = "\n".join([f"- {k}: {v}" for k, v in todas.items() if v])
    mapeo_texto = "\n".join([
        f"- '{m['campo_origen']}' en {origen} → '{m['campo_destino']}' en {destino}"
        for m in plan.get("mapeo_campos", [])
    ]) or "Aprende el mapeo observando la página"

    pasos_texto = "\n".join([
        f"{p['numero']}. [{p['accion'].upper()}] {p['intencion']}"
        + (f" → valor: {p['valor']}" if p.get('valor') else "")
        for p in plan.get("pasos", [])
    ])

    n_pasos = len(plan.get("pasos", []))
    task = f"""Eres un agente que automatiza procesos entre dos sistemas web para Arca Continental.

OBJETIVO: {objetivo}
SISTEMAS: Origen={origen} → Destino={destino}

CREDENCIALES:
{creds_texto or "Ninguna — infiere del contexto"}

MAPEO DE CAMPOS:
{mapeo_texto}

PASOS A EJECUTAR ({n_pasos} en total — guíate por la intención, no por coordenadas):
{pasos_texto}

REGLAS DE DECISIÓN — léelas antes de actuar:
1. Ejecuta cada paso en orden. Si un elemento no está visible, haz scroll una sola vez y reintenta.
2. Si un paso falla dos veces seguidas → márcalo como error, CONTINÚA con el siguiente paso. No repitas el mismo intento más de 2 veces.
3. Si llevas 3 pasos consecutivos en error → detente, reporta el bloqueo y termina.
4. Si la página no carga en 15 s o aparece un captcha/login inesperado → termina inmediatamente con estado "bloqueado".
5. Cuando hayas ejecutado todos los pasos (o tomado la decisión de detenerte) → cierra el proceso y NO hagas nada más.
6. NUNCA entres en un bucle repitiendo la misma acción fallida esperando un resultado diferente.

Al finalizar (éxito o fallo parcial) responde SOLO este JSON sin texto adicional:
{{
  "estado_final": "completado|parcial|bloqueado",
  "pasos_ok": <número>,
  "pasos_error": <número>,
  "motivo_parada": "descripción breve si no se completó",
  "datos_extraidos": {{}}
}}"""

    print(f"\n🤖 browser_use ejecutando: {objetivo}")
    print(f"   Sistemas: {origen} → {destino}\n")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    timeout_seg = int(os.getenv("AGENT_TIMEOUT_SEG", "600"))  # 10 min por defecto
    estado = "error"
    resultado_texto = ""
    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = loop.run_in_executor(pool, _run_browser_use_sync, task, api_key)
            resultado_texto = await asyncio.wait_for(future, timeout=timeout_seg)
        print(f"\n✅ browser_use completó el proceso")
        print(f"   {resultado_texto[:200]}...")
        estado = "ok"
    except asyncio.TimeoutError:
        resultado_texto = f"Timeout: el agente superó {timeout_seg}s sin terminar"
        print(f"\n⏱️  Timeout — agente detenido tras {timeout_seg}s")
        estado = "timeout"
    except Exception as e:
        resultado_texto = f"Error: {e}"
        print(f"\n❌ Error en browser_use: {e}")
        estado = "error"

    # Guardar reporte JSON
    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/reporte.json", "w", encoding="utf-8") as f:
        json.dump({"objetivo": objetivo, "origen": origen, "destino": destino,
                   "resultado": resultado_texto, "fecha": datetime.now().isoformat(),
                   "motor": "browser_use"}, f, indent=2, ensure_ascii=False)

    # Intentar extraer datos estructurados del texto de respuesta
    datos_extraidos = {}
    try:
        match = re.search(r'\{[^{}]*"datos_extraidos"[^{}]*\}', resultado_texto, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            datos_extraidos = parsed.get("datos_extraidos", {})
    except Exception:
        pass
    if not datos_extraidos and resultado_texto:
        datos_extraidos = {"resumen": resultado_texto[:500]}

    pasos = plan.get("pasos", [])
    if not pasos:
        return [{"paso": 1, "accion": "browser_use", "estado": estado,
                 "intencion": objetivo, "datos_extraidos": datos_extraidos}]

    estado_paso_ok = "ok" if estado == "ok" else estado  # propaga timeout/error
    resultados = []
    for i, p in enumerate(pasos):
        es_ultimo = (i == len(pasos) - 1)
        resultados.append({
            "paso":            p["numero"],
            "accion":          p["accion"],
            "intencion":       p["intencion"],
            "estado":          estado if es_ultimo else ("ok" if estado == "ok" else estado_paso_ok),
            "datos_extraidos": datos_extraidos if es_ultimo else None,
        })
    return resultados


# ─── Entry point ─────────────────────────────────────────────────────────────

async def ejecutar(plan: dict, credenciales: dict, email_reporte: str) -> list:
    """
    Ejecuta el plan usando browser_use y luego genera reportes, guarda en SQLite
    y envía email.
    """
    print(f"\n🤖 Ejecutando: {plan.get('objetivo')}")

    resultados = await ejecutar_con_browser_use(plan, credenciales, email_reporte)
    motor = "browser_use"

    ok = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\n{'─'*50}")
    print(f"  Motor   : {motor}")
    print(f"  Resultado: {ok}/{len(resultados)} pasos exitosos")

    datos_extraidos = {
        f"paso_{r.get('paso', i)}": r["datos_extraidos"]
        for i, r in enumerate(resultados) if r.get("datos_extraidos")
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
        print(f"  ⚠️  SQLite no disponible: {e}")

    # Generar los tres reportes: Excel compras, PDF IA, Excel errores
    rutas = {}
    try:
        from postprocessing.reporte import generar_todos_los_reportes, generar_ticket_html, guardar_ticket
        datos_reporte = {
            "objetivo":        plan.get("objetivo", "Proceso"),
            "origen":          plan.get("plataforma_origen", ""),
            "destino":         plan.get("plataforma_destino", ""),
            "resultados":      resultados,
            "datos_extraidos": datos_extraidos,
            "fecha":           datetime.now().isoformat(),
            "motor":           motor,
            "iteraciones":     len(resultados),
            "plan":            plan,
        }
        rutas = generar_todos_los_reportes(datos_reporte)
        ticket_html = generar_ticket_html(datos_reporte)
        guardar_ticket(ticket_html)
        print(f"  📦 Excel compras : {rutas.get('excel_compras')}")
        print(f"  📄 PDF reporte IA: {rutas.get('pdf_reporte')}")
        print(f"  📊 Excel errores : {rutas.get('excel_errores')}")
    except Exception as e:
        print(f"  ⚠️  Reportes no generados: {e}")

    # Email
    _enviar_email(email_reporte, plan, resultados, datos_extraidos,
                  rutas.get("excel_compras"))

    return resultados


def _enviar_email(destinatario: str, plan: dict, resultados: list,
                  datos: dict, excel_path: str = None):
    remitente = os.getenv("EMAIL_REMITENTE", "")
    password  = os.getenv("EMAIL_PASSWORD", "")
    if not remitente or not password or not destinatario:
        print(f"  📄 Email desactivado — agrega EMAIL_REMITENTE y EMAIL_PASSWORD al .env")
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
