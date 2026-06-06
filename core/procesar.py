import json
import base64
import os
from datetime import datetime
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic()

UMBRAL_CONFIANZA = 0.70


# ─── Utilidades ───────────────────────────────────────────────────────────────

def parsear_con_reintento(texto: str, max_intentos: int = 2) -> dict:
    raw = texto.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if max_intentos == 0:
            raise
        correccion = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"Este JSON está malformado. Corrígelo y devuelve SOLO el JSON válido, sin backticks:\n{raw}"
            }]
        )
        return parsear_con_reintento(correccion.content[0].text, max_intentos - 1)


def validar_plan(plan: dict) -> list:
    errores = []
    if not plan.get("plataforma_origen") or "N/A" in plan.get("plataforma_origen", ""):
        errores.append("No se identificó plataforma origen")
    if not plan.get("plataforma_destino"):
        errores.append("No se identificó plataforma destino")
    if not plan.get("mapeo_campos"):
        errores.append("No hay mapeo de campos entre sistemas")
    if len(plan.get("pasos", [])) < 2:
        errores.append("Plan con menos de 2 pasos — probablemente incompleto")
    return errores


# ─── Transcripción ────────────────────────────────────────────────────────────

def transcribir_audio(audio_path: str) -> str:
    """Groq Whisper para transcripción — más rápido y barato que Opus."""
    try:
        from groq import Groq
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with open(audio_path, "rb") as f:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                language="es"
            )
        return transcript.text
    except Exception as e:
        # Fallback a Claude si Groq no está disponible
        try:
            with open(audio_path, "rb") as f:
                audio_data = base64.standard_b64encode(f.read()).decode("utf-8")
            respuesta = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "audio/wav",
                                "data": audio_data
                            }
                        },
                        {
                            "type": "text",
                            "text": "Transcribe exactamente lo que dice esta grabación en español. Solo la transcripción, sin comentarios."
                        }
                    ]
                }]
            )
            return respuesta.content[0].text.strip()
        except Exception as e2:
            raise RuntimeError(f"Error transcribiendo audio: {e} / {e2}")


# ─── FASE A: Analizar sesión + detectar qué falta ────────────────────────────

def analizar_sesion(eventos: list, audio_path: str) -> dict:
    """
    FASE A — Llama a Claude con screenshots + audio.
    Devuelve el plan inicial + las preguntas que tiene la IA.
    No hace input() — el frontend muestra las preguntas.
    """
    transcripcion = transcribir_audio(audio_path)

    con_screenshot = [e for e in eventos if e.get("screenshot")]
    if not con_screenshot:
        raise ValueError("No hay screenshots en la grabación.")

    paso = max(1, len(con_screenshot) // 10)
    keyframes = con_screenshot[::paso][:10]

    contenido = []
    for i, evento in enumerate(keyframes):
        contenido.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": evento["screenshot"]}
        })
        contenido.append({
            "type": "text",
            "text": f"Momento {i+1}: {evento['tipo']} en ({evento.get('x','')}, {evento.get('y','')})"
        })

    contenido.append({
        "type": "text",
        "text": f"""
El usuario explicó mientras trabajaba:
"{transcripcion}"

Analiza TODO y genera el plan. El usuario trabajó con DOS sistemas:
- ORIGEN: donde están los datos
- DESTINO: donde se registran los datos

Los campos pueden tener nombres DISTINTOS en cada sistema.
NUNCA uses selectores CSS ni IDs. Describe elementos visualmente.
Para cada campo del mapeo incluye tu nivel de confianza (0.0-1.0).

Responde SOLO este JSON sin backticks:
{{
  "plataforma_origen": "nombre del sistema origen",
  "plataforma_destino": "nombre del sistema destino",
  "objetivo": "qué logra este proceso",
  "mapeo_campos": [
    {{
      "campo_origen": "nombre en origen",
      "campo_destino": "nombre en destino",
      "descripcion": "qué representa",
      "confianza": 0.0
    }}
  ],
  "credenciales_necesarias": ["datos que el bot necesita pero no vio"],
  "pasos": [
    {{
      "numero": 1,
      "sistema": "origen o destino",
      "intencion": "descripción visual de qué hacer",
      "accion": "navegar|click|escribir|seleccionar|verificar|esperar|extraer",
      "valor": "URL o texto si aplica",
      "validacion": "cómo saber que funcionó"
    }}
  ],
  "excepciones": [
    {{"situacion": "qué puede salir mal", "accion": "qué hacer"}}
  ],
  "reporte_incluir": ["datos a incluir en el reporte"]
}}"""
    })

    respuesta = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": contenido}]
    )
    plan_inicial = parsear_con_reintento(respuesta.content[0].text)

    # Flag campos con baja confianza
    for campo in plan_inicial.get("mapeo_campos", []):
        campo["flag"] = campo.get("confianza", 1.0) < UMBRAL_CONFIANZA

    # Detectar qué preguntas tiene la IA (Sonnet — no necesita visión)
    resp_preguntas = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Eres un agente que aprendió un proceso web observando a un usuario.

Plan generado:
{json.dumps(plan_inicial, indent=2, ensure_ascii=False)}

El usuario explicó: "{transcripcion}"

Identifica QUÉ información genuinamente te falta para ejecutar este proceso.

REGLAS:
- NO preguntes sobre botones, menús, navegación — eso lo ves en pantalla
- SÍ pregunta sobre: credenciales, datos específicos que el usuario escribió y no se veían
- Máximo 3 preguntas. Si no falta nada, deja preguntas vacío.

Responde SOLO JSON sin backticks:
{{
  "preguntas": [
    {{
      "campo": "nombre interno del dato",
      "pregunta": "pregunta clara para el usuario",
      "por_que": "por qué no pudiste inferirlo",
      "es_password": false
    }}
  ],
  "ya_se": ["cosas que aprendiste sin preguntar"]
}}"""
        }]
    )
    analisis = parsear_con_reintento(resp_preguntas.content[0].text)

    # Guardar metadata
    plan_inicial["_meta"] = {
        "transcripcion":     transcripcion,
        "n_eventos":         len(eventos),
        "n_keyframes":       len(keyframes),
        "campos_flaggeados": len([c for c in plan_inicial.get("mapeo_campos", []) if c.get("flag")]),
        "timestamp":         datetime.now().isoformat(),
    }

    return {
        "plan":     plan_inicial,
        "preguntas": analisis.get("preguntas", []),
        "ya_se":    analisis.get("ya_se", []),
    }


# ─── FASE B: Completar el plan con las respuestas del usuario ────────────────

def completar_plan(resultado_fase_a: dict, respuestas_usuario: dict) -> dict:
    """
    FASE B — Recibe el plan de fase A + las respuestas que dio el usuario
    en el Streamlit. Inyecta las respuestas y guarda el plan final.
    """
    plan = resultado_fase_a["plan"]
    plan["credenciales_obtenidas"] = respuestas_usuario

    errores = validar_plan(plan)

    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/plan.json", "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    return plan, errores
