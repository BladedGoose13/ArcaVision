import asyncio
import json
import base64
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
from io import BytesIO

from PIL import Image
from playwright.async_api import async_playwright
from anthropic import Anthropic
from dotenv import load_dotenv
import os

load_dotenv()
client = Anthropic()


async def analizar_pagina_completa(page, intencion: str) -> dict:
    """
    Analiza la página combinando HTML + screenshot para encontrar elementos.
    Como un humano que lee y ve al mismo tiempo — resistente a cambios de UI.
    """
    # Capturar screenshot
    screenshot = await page.screenshot()
    img = Image.open(BytesIO(screenshot))
    img.thumbnail((1280, 720))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=75)
    screenshot_b64 = base64.b64encode(buf.getvalue()).decode()

    # Extraer HTML simplificado (solo elementos interactivos)
    html_simplificado = await page.evaluate("""() => {
        const elementos = [];
        const selectores = 'input, button, a, select, textarea, [role="button"], [onclick]';
        document.querySelectorAll(selectores).forEach((el, i) => {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                elementos.push({
                    tag: el.tagName.toLowerCase(),
                    tipo: el.type || '',
                    texto: (el.textContent || el.value || el.placeholder || '').trim().substring(0, 50),
                    nombre: el.name || el.id || el.className.split(' ')[0] || '',
                    placeholder: el.placeholder || '',
                    x: Math.round(rect.x + rect.width/2),
                    y: Math.round(rect.y + rect.height/2),
                    visible: rect.top >= 0 && rect.bottom <= window.innerHeight
                });
            }
        });
        return JSON.stringify(elementos.slice(0, 30));
    }""")

    vp = page.viewport_size or {"width": 1280, "height": 720}

    respuesta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": screenshot_b64
                    }
                },
                {
                    "type": "text",
                    "text": f"""Pantalla {vp['width']}x{vp['height']}px.

Elementos interactivos detectados en el HTML:
{html_simplificado}

Tarea: {intencion}

Usa TANTO la imagen como el HTML para encontrar el elemento correcto.
El elemento puede tener nombres distintos (login/iniciar sesión, submit/enviar, etc).
Elige el elemento que mejor cumple la intención, sin importar idioma o posición.

Responde SOLO JSON:
{{"encontrado": true/false, "x": <int>, "y": <int>, "confianza": <0.0-1.0>, "descripcion": "<qué encontraste y por qué>"}}"""
                }
            ]
        }]
    )

    raw = respuesta.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


async def ejecutar_paso(page, paso: dict, credenciales: dict) -> dict:
    """Ejecuta un paso del plan con reintentos y análisis HTML."""
    accion = paso["accion"]
    intencion = paso["intencion"]
    valor = paso.get("valor", "")

    # Reemplazar credenciales
    for key, val in {**credenciales, **credenciales.get("credenciales_obtenidas", {})}.items():
        if isinstance(val, str):
            valor = valor.replace(f"{{{key}}}", val)

    resultado = {"paso": paso["numero"], "accion": accion, "estado": "pendiente"}

    for intento in range(1, 4):
        try:
            if accion == "navegar":
                await page.goto(valor, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1500)
                resultado["estado"] = "ok"
                break

            elif accion in ("click", "escribir", "seleccionar"):
                loc = await analizar_pagina_completa(page, intencion)

                if not loc.get("encontrado") or loc.get("confianza", 0) < 0.5:
                    print(f"    ⚠️  Intento {intento}: no encontré '{intencion[:50]}'")
                    await page.wait_for_timeout(1500)
                    continue

                x, y = loc["x"], loc["y"]
                print(f"    👁  {loc['descripcion'][:60]} → ({x},{y}) {loc['confianza']:.0%}")

                if accion == "click":
                    await page.mouse.click(x, y)
                elif accion == "escribir":
                    await page.mouse.click(x, y)
                    await page.keyboard.press("Meta+a")
                    await page.keyboard.type(valor, delay=50)
                elif accion == "seleccionar":
                    await page.mouse.click(x, y)
                    await page.wait_for_timeout(400)
                    if valor:
                        op = await analizar_pagina_completa(page, f"opción '{valor}' en dropdown abierto")
                        if op.get("encontrado"):
                            await page.mouse.click(op["x"], op["y"])

                resultado["estado"] = "ok"
                break

            elif accion == "verificar":
                loc = await analizar_pagina_completa(page, intencion)
                resultado["estado"] = "ok" if loc.get("encontrado") else "advertencia"
                break

            elif accion == "extraer":
                # Extraer texto visible de la página
                texto = await page.evaluate("""() => document.body.innerText.substring(0, 2000)""")
                resultado["datos_extraidos"] = texto
                resultado["estado"] = "ok"
                break

            elif accion == "esperar":
                await page.wait_for_timeout(int(valor or 1) * 1000)
                resultado["estado"] = "ok"
                break

            await page.wait_for_timeout(800)

        except Exception as e:
            print(f"    ❌ Intento {intento}: {e}")
            if intento < 3:
                await page.wait_for_timeout(2000)

    icono = "✅" if resultado["estado"] == "ok" else "⚠️ " if resultado["estado"] == "advertencia" else "❌"
    print(f"  {icono} Paso {paso['numero']}: {intencion[:65]}")
    return resultado


def enviar_reporte(destinatario: str, plan: dict, resultados: list, datos_extraidos: dict):
    remitente = os.getenv("EMAIL_REMITENTE", "")
    password_email = os.getenv("EMAIL_PASSWORD", "")

    ok = sum(1 for r in resultados if r["estado"] == "ok")
    total = len(resultados)

    reporte = {
        "plan": plan,
        "resultados": resultados,
        "datos": datos_extraidos,
        "resumen": f"{ok}/{total} pasos exitosos",
        "fecha": datetime.now().isoformat()
    }

    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/reporte.json", "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)

    if not remitente or not password_email:
        print(f"  📄 Reporte guardado: sesiones/reporte.json")
        return

    cuerpo = f"""
Hack4Her — Always on Shelf
Reporte de ejecución automática

Proceso: {plan.get('objetivo', '')}
Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Resultado: {ok}/{total} pasos exitosos

Datos extraídos:
{json.dumps(datos_extraidos, indent=2, ensure_ascii=False)}
"""
    msg = MIMEMultipart()
    msg["From"] = remitente
    msg["To"] = destinatario
    msg["Subject"] = f"Reporte Bot — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    msg.attach(MIMEText(cuerpo, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(remitente, password_email)
            server.sendmail(remitente, destinatario, msg.as_string())
        print(f"  📧 Reporte enviado a {destinatario}")
    except Exception as e:
        print(f"  ⚠️  Email no enviado: {e} — reporte guardado localmente")


async def ejecutar(plan: dict, credenciales: dict, email_reporte: str):
    print(f"\n🤖 Ejecutando: {plan.get('objetivo')}")
    print(f"   Pasos: {len(plan.get('pasos', []))}\n")

    resultados = []
    datos_extraidos = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        for paso in plan.get("pasos", []):
            resultado = await ejecutar_paso(page, paso, credenciales)
            resultados.append(resultado)

            # Guardar datos extraídos
            if resultado.get("datos_extraidos"):
                datos_extraidos[f"paso_{paso['numero']}"] = resultado["datos_extraidos"]

            # Solo abortar en errores críticos (primeros pasos)
            if resultado["estado"] == "error" and paso["numero"] <= 3:
                print(f"\n  🚨 Error crítico en paso {paso['numero']} — abortando")
                break

        await browser.close()

    ok = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\n{'─'*50}")
    print(f"  Resultado: {ok}/{len(resultados)} pasos exitosos")

    enviar_reporte(email_reporte, plan, resultados, datos_extraidos)
    return resultados