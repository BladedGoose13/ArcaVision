"""
browser_agent/agent.py
-----------------------
Agente principal usando browser_use — más robusto que Playwright puro.
Fallback a Playwright+Vision si browser_use no está disponible.

Fixes:
  - Sin asyncio.run() interno — el caller es responsable del event loop
  - Credenciales nunca se loguean ni guardan en el reporte JSON en disco
  - Timeout configurable via env AGENT_TIMEOUT_STEPS
"""

from __future__ import annotations

import asyncio
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

MAX_STEPS = int(os.getenv("AGENT_TIMEOUT_STEPS", "50"))


# ─── Motor principal: browser_use ────────────────────────────────────────────

async def ejecutar_con_browser_use(plan: dict, credenciales: dict, email_reporte: str) -> list:
    from browser_use import Agent
    from langchain_anthropic import ChatAnthropic

    todas = {**credenciales, **plan.get("credenciales_obtenidas", {})}
    origen   = plan.get("plataforma_origen", "")
    destino  = plan.get("plataforma_destino", "")
    objetivo = plan.get("objetivo", "Ejecutar el proceso aprendido")

    # Nunca loguear credenciales
    creds_texto = "\n".join([f"- {k}: [PROTEGIDO]" if any(w in k.lower() for w in ["pass","clave","secret","token"]) else f"- {k}: {v}" for k, v in todas.items() if v])

    mapeo = plan.get("mapeo_campos", [])
    mapeo_texto = "\n".join([
        f"- '{m['campo_origen']}' en {origen} → '{m['campo_destino']}' en {destino}"
        for m in mapeo
    ]) if mapeo else "Aprende el mapeo observando la página"

    pasos_texto = "\n".join([
        f"{p['numero']}. [{p['accion'].upper()}] {p['intencion']}"
        + (f" → valor: {p['valor']}" if p.get("valor") else "")
        for p in plan.get("pasos", [])
    ])

    task = f"""
Eres un agente que automatiza procesos entre dos sistemas web para Arca Continental.

OBJETIVO: {objetivo}

SISTEMAS:
- Origen: {origen}
- Destino: {destino}

CREDENCIALES:
{creds_texto if creds_texto else "Ninguna — infiere del contexto"}

MAPEO DE CAMPOS:
{mapeo_texto}

PASOS APRENDIDOS (guíate por la intención, no por coordenadas):
{pasos_texto}

INSTRUCCIONES:
1. Ejecuta el proceso completo de principio a fin
2. Si un elemento no está visible, haz scroll
3. Si algo falla, intenta una alternativa razonable
4. Al terminar, extrae los datos más importantes del resultado
5. NO pares hasta completar el objetivo o agotar opciones razonables
6. Reporta cada acción importante

Al finalizar, resume en JSON qué hiciste y qué datos extrajiste.
"""

    print(f"\n🤖 browser_use ejecutando: {objetivo}")
    print(f"   Sistemas: {origen} → {destino}\n")

    llm = ChatAnthropic(model="claude-opus-4-5")   # lee ANTHROPIC_API_KEY del env

    agent = Agent(task=task, llm=llm)

    try:
        result = await agent.run(max_steps=MAX_STEPS)
        resultado_texto = str(result)
        print(f"\n✅ browser_use completó el proceso")
        print(f"   {resultado_texto[:200]}...")
        estado = "ok"
    except Exception as e:
        resultado_texto = f"Error: {e}"
        print(f"\n❌ Error en browser_use: {e}")
        estado = "error"

    # Reporte sin credenciales
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


# ─── Fallback: Playwright + Vision ────────────────────────────────────────────

async def ejecutar_con_playwright(plan: dict, credenciales: dict, email_reporte: str) -> list:
    import base64
    from io import BytesIO
    from PIL import Image
    from playwright.async_api import async_playwright
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()

    async def analizar_pagina(page, intencion: str) -> dict:
        screenshot = await page.screenshot()
        img = Image.open(BytesIO(screenshot))
        img.thumbnail((1280, 720))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=75)
        sc_b64 = base64.b64encode(buf.getvalue()).decode()

        html = await page.evaluate("""() => {
            const els = [];
            document.querySelectorAll('input,button,a,select,textarea,[role="button"]').forEach((el,i) => {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0)
                    els.push({tag:el.tagName.toLowerCase(),texto:(el.textContent||el.value||el.placeholder||'').trim().slice(0,40),
                              nombre:el.name||el.id||'',x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
            });
            return JSON.stringify(els.slice(0,25));
        }""")

        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": sc_b64}},
                {"type": "text", "text": f"Elementos: {html}\nTarea: {intencion}\nResponde SOLO JSON: {{\"encontrado\":bool,\"x\":int,\"y\":int,\"confianza\":float}}"},
            ]}],
        )
        from brain.procesar import _extraer_json
        return _extraer_json(resp.content[0].text)

    resultados = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        todas = {**credenciales, **plan.get("credenciales_obtenidas", {})}

        for paso in plan.get("pasos", []):
            accion    = paso["accion"]
            intencion = paso["intencion"]
            valor     = paso.get("valor", "")
            for k, v in todas.items():
                if isinstance(v, str):
                    valor = valor.replace(f"{{{k}}}", v)

            res = {"paso": paso["numero"], "accion": accion, "estado": "error"}
            try:
                if accion == "navegar":
                    await page.goto(valor, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(1500)
                    res["estado"] = "ok"
                elif accion in ("click", "escribir", "seleccionar"):
                    loc = await analizar_pagina(page, intencion)
                    if loc.get("encontrado") and loc.get("confianza", 0) >= 0.5:
                        x, y = loc["x"], loc["y"]
                        if accion == "click":
                            await page.mouse.click(x, y)
                        elif accion == "escribir":
                            await page.mouse.click(x, y)
                            await page.keyboard.press("Control+a")
                            await page.keyboard.type(valor, delay=40)
                        res["estado"] = "ok"
                    else:
                        res["estado"] = "advertencia"
                elif accion == "extraer":
                    texto = await page.evaluate("() => document.body.innerText.substring(0,2000)")
                    res["datos_extraidos"] = texto
                    res["estado"] = "ok"
                elif accion == "esperar":
                    await page.wait_for_timeout(int(valor or 1) * 1000)
                    res["estado"] = "ok"
                elif accion == "verificar":
                    loc = await analizar_pagina(page, intencion)
                    res["estado"] = "ok" if loc.get("encontrado") else "advertencia"
            except Exception as e:
                print(f"    ❌ Paso {paso['numero']}: {e}")

            icono = "✅" if res["estado"] == "ok" else "⚠️ " if res["estado"] == "advertencia" else "❌"
            print(f"  {icono} Paso {paso['numero']}: {intencion[:65]}")
            resultados.append(res)

            if res["estado"] == "error" and paso["numero"] <= 2:
                print("  🚨 Error crítico — abortando")
                break

        await browser.close()

    return resultados


# ─── Entry point ─────────────────────────────────────────────────────────────

async def ejecutar(plan: dict, credenciales: dict, email_reporte: str) -> list:
    print(f"\n🤖 Ejecutando: {plan.get('objetivo')}")

    try:
        import browser_use  # noqa
        resultados = await ejecutar_con_browser_use(plan, credenciales, email_reporte)
        motor = "browser_use"
    except ImportError:
        print("  ℹ️  browser_use no instalado — usando Playwright+Vision")
        resultados = await ejecutar_con_playwright(plan, credenciales, email_reporte)
        motor = "playwright"

    ok = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\n{'─'*50}")
    print(f"  Motor    : {motor}")
    print(f"  Resultado: {ok}/{len(resultados)} pasos exitosos")

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
        print(f"  ⚠️  SQLite no disponible: {e}")

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
        print(f"  ⚠️  Reportes no generados: {e}")

    _enviar_email(email_reporte, plan, resultados, datos_extraidos, excel_path)

    return resultados


def _enviar_email(
    destinatario: str,
    plan: dict,
    resultados: list,
    datos: dict,
    excel_path: str = None,
):
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
