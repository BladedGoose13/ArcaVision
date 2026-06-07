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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _run_browser_use_sync(task: str, api_key: str) -> dict:
    """
    Ejecuta browser_use Agent en un thread con su propio event loop.
    Retorna dict con estado real extraído del AgentHistoryList.
    """
    from browser_use import Agent
    from langchain_anthropic import ChatAnthropic

    async def _inner():
        llm   = ChatAnthropic(model="claude-opus-4-5", api_key=api_key)
        agent = Agent(
            task=task,
            llm=llm,
            max_failures=2,
            use_vision=False,
        )
        result = await agent.run(max_steps=25)

        errores = result.errors() if hasattr(result, "errors") else []
        errores = [str(e) for e in errores if e]

        final = ""
        if hasattr(result, "final_result"):
            final = result.final_result() or ""
        if not final:
            # fallback: último extracted_content no vacío
            for r in reversed(result.action_results() if hasattr(result, "action_results") else []):
                if getattr(r, "extracted_content", None):
                    final = str(r.extracted_content)
                    break

        completado = result.is_done() if hasattr(result, "is_done") else False
        pasos_ok    = sum(1 for r in (result.action_results() if hasattr(result, "action_results") else [])
                         if getattr(r, "error", None) is None)
        pasos_error = sum(1 for r in (result.action_results() if hasattr(result, "action_results") else [])
                         if getattr(r, "error", None) is not None)

        return {
            "completado":   completado,
            "final":        final,
            "errores":      errores,
            "pasos_ok":     pasos_ok,
            "pasos_error":  pasos_error,
        }

    return asyncio.run(_inner())


def _extraer_json_balanceado(texto: str) -> dict:
    """
    Extrae el primer objeto JSON completo del texto balanceando llaves.
    Reemplaza el regex anterior que no soportaba JSON anidado.
    """
    if not texto:
        return {}
    inicio = texto.find("{")
    while inicio != -1:
        nivel = 0
        en_str = False
        escape = False
        for i in range(inicio, len(texto)):
            c = texto[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                en_str = not en_str
                continue
            if en_str:
                continue
            if c == "{":
                nivel += 1
            elif c == "}":
                nivel -= 1
                if nivel == 0:
                    try:
                        return json.loads(texto[inicio:i + 1])
                    except json.JSONDecodeError:
                        break  # objeto malformado: busca el siguiente "{"
        inicio = texto.find("{", inicio + 1)
    return {}


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

CÓMO ACTUAR (decide rápido, no te trabes):
1. Para interactuar usa el texto/label/placeholder del elemento en el índice del DOM. Si el elemento objetivo ya está en la lista, haz click directo — no scrollees "por si acaso".
2. Solo scrollea si el siguiente paso requiere algo que claramente está más abajo y NO aparece en la lista actual. Un scroll por necesidad, nunca en bucle.
3. Si una acción falla, no la repitas igual: prueba la alternativa más obvia una vez; si tampoco, marca el paso como fallido y avanza al siguiente.
4. Si 2 pasos seguidos fallan, o aparece captcha/login inesperado, o la página no carga en ~10 s → TERMINA y reporta el motivo.
5. Cuando completes todos los pasos → termina de inmediato. No navegues de más.

REGISTRO DE COMPRAS (crítico para el reporte):
Cada vez que agregues un producto al carrito/orden, anota nombre exacto, precio unitario y cantidad.
Llena el array "productos" del JSON final con esos datos reales (no inventes precios).

Al finalizar (éxito o fallo) llama a la acción "done" con EXACTAMENTE este JSON:
{{
  "estado_final": "completado|parcial|bloqueado",
  "pasos_ok": <entero, cuántos de los {n_pasos} pasos del plan lograste>,
  "pasos_error": <entero>,
  "motivo_parada": "vacío si completado; si no, qué te detuvo",
  "productos": [
    {{"nombre": "...", "precio_unitario": 0.0, "cantidad": 1, "sku": "", "estado": "ok"}}
  ],
  "datos_extraidos": {{"clave": "valor relevante observado"}}
}}"""

    print(f"\n🤖 browser_use ejecutando: {objetivo}")
    print(f"   Sistemas: {origen} → {destino}\n")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    timeout_seg = int(os.getenv("AGENT_TIMEOUT_SEG", "300"))  # 5 min por defecto
    estado = "error"
    resultado_texto = ""
    reporte_agente = {}          # JSON auto-reportado por el agente (done action)
    errores_agente = []
    completado_agente = False
    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = loop.run_in_executor(pool, _run_browser_use_sync, task, api_key)
            info = await asyncio.wait_for(future, timeout=timeout_seg)

        resultado_texto   = info.get("final", "")
        errores_agente    = info.get("errores", [])
        completado_agente = info.get("completado", False)
        reporte_agente    = _extraer_json_balanceado(resultado_texto)

        if completado_agente:
            estado = "ok"
            print(f"\n✅ browser_use completó el proceso")
        else:
            estado = "parcial" if info.get("pasos_ok", 0) > 0 else "error"
            motivo = (reporte_agente.get("motivo_parada")
                      or (errores_agente[0] if errores_agente else "detenido sin completar"))
            print(f"\n⚠️  browser_use terminó sin completar — {motivo}")

        if resultado_texto:
            print(f"   Resultado: {resultado_texto[:200]}")

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

    # Datos estructurados auto-reportados por el agente (JSON balanceado)
    datos_extraidos = reporte_agente.get("datos_extraidos") or {}
    productos       = reporte_agente.get("productos") or []
    if not datos_extraidos and resultado_texto:
        datos_extraidos = {"resumen": resultado_texto[:500]}

    pasos = plan.get("pasos", [])
    n = len(pasos)
    if not pasos:
        return [{"paso": 1, "accion": "browser_use", "estado": estado,
                 "intencion": objetivo, "datos_extraidos": datos_extraidos,
                 "productos": productos}]

    # ── Mapeo honesto de estado por paso del PLAN (no por acciones del agente) ──
    if completado_agente:
        n_ok = n
    elif estado == "error":
        n_ok = 0
    else:  # parcial / timeout → usa los pasos_ok auto-reportados, acotado al plan
        n_ok = max(0, min(n - 1, int(reporte_agente.get("pasos_ok", 0) or 0)))

    resultados = []
    for i, p in enumerate(pasos):
        es_ultimo = (i == n - 1)
        if i < n_ok:
            paso_estado = "ok"
        elif i == n_ok and estado in ("timeout", "error", "parcial"):
            paso_estado = estado          # el paso donde se detuvo lleva la causa
        else:
            paso_estado = "error"
        resultados.append({
            "paso":            p["numero"],
            "accion":          p["accion"],
            "intencion":       p["intencion"],
            "estado":          paso_estado,
            "detalle_error":   (errores_agente[0][:200] if errores_agente and paso_estado != "ok" else ""),
            "datos_extraidos": datos_extraidos if es_ultimo else None,
            "productos":       productos if es_ultimo else None,
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

    # Productos reales auto-reportados por el agente (para el Excel de compras)
    productos = next((r["productos"] for r in resultados if r.get("productos")), [])

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
            "productos":       productos,
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
