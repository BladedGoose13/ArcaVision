"""
core/procesar.py — usado por backend/api.py (frontend HTML)
------------------------------------------------------------
Fase A: analizar_sesion   → screenshots + audio → plan + preguntas para el frontend
Fase B: completar_plan    → recibe respuestas del HTML → cierra el plan
"""
import json
import os
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

_api_key = os.getenv("ANTHROPIC_API_KEY")
if not _api_key:
    raise RuntimeError("ANTHROPIC_API_KEY no está configurada en el entorno")
client = Anthropic(api_key=_api_key)


# ─── Utilidad: parseo robusto de JSON de Claude ───────────────────────────────

def _parsear_json(raw: str) -> dict:
    """
    Extrae el primer objeto JSON completo de la respuesta de Claude.
    Balancea llaves (soporta JSON anidado) e ignora texto, code fences o
    comentarios alrededor. Reemplaza el frágil split('```')+lstrip('json'),
    que removía caracteres sueltos y fallaba si había texto extra.
    """
    if not raw:
        return {}
    inicio = raw.find("{")
    while inicio != -1:
        nivel = 0
        en_str = False
        escape = False
        for i in range(inicio, len(raw)):
            c = raw[i]
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
                        return json.loads(raw[inicio:i + 1])
                    except json.JSONDecodeError:
                        break
        inicio = raw.find("{", inicio + 1)
    return {}


# ─── Audio ────────────────────────────────────────────────────────────────────

def transcribir_audio(audio_path: str) -> str:
    if not audio_path or not Path(audio_path).exists():
        return ""
    try:
        from groq import Groq
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with open(audio_path, "rb") as f:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3", file=f, language="es",
            )
        return transcript.text.strip()
    except Exception as e:
        print(f"  ⚠️  Groq no disponible: {e}")
        return ""


# ─── Fase A ───────────────────────────────────────────────────────────────────

def analizar_sesion(eventos: list, audio_path: str) -> dict:
    """
    Retorna {"plan": {...}, "preguntas": [...], "ya_se": [...]}
    para que el frontend HTML los muestre. Nunca llama input().
    """
    transcripcion = transcribir_audio(audio_path)

    con_screenshot = [e for e in eventos if e.get("screenshot")]
    if not con_screenshot:
        raise ValueError("No hay screenshots en la grabación. ¿Se grabó correctamente?")

    paso = max(1, len(con_screenshot) // 10)
    keyframes = con_screenshot[::paso][:10]

    # ── Paso 1: Claude analiza screenshots + audio y genera el plan ───────────
    contenido = []
    for i, evento in enumerate(keyframes):
        contenido.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": evento["screenshot"]},
        })
        contenido.append({
            "type": "text",
            "text": f"Momento {i+1}: {evento['tipo']} en ({evento.get('x','')}, {evento.get('y','')})",
        })

    contexto_audio = (
        f'\nEl usuario explicó mientras trabajaba:\n"{transcripcion}"\n'
        if transcripcion
        else "\n(Sin audio — infiere el proceso solo desde las imágenes)\n"
    )

    contenido.append({"type": "text", "text": f"""{contexto_audio}
Analiza TODO y genera el plan. El usuario trabajó con DOS sistemas:
- ORIGEN: donde están los datos
- DESTINO: donde se registran los datos

Los campos pueden tener nombres DISTINTOS en cada sistema — aprende el mapeo real.
NUNCA uses selectores CSS ni IDs. Describe elementos visualmente.
En "credenciales_necesarias" incluye SOLO datos que el bot NO puede ver en pantalla
(contraseñas, tokens, campos que aparecen con asteriscos o que el usuario escribió
sin que la cámara lo capturara).

Responde SOLO este JSON sin texto adicional:
{{
  "plataforma_origen": "nombre del sistema origen",
  "plataforma_destino": "nombre del sistema destino",
  "objetivo": "qué logra este proceso",
  "mapeo_campos": [
    {{
      "campo_origen": "nombre en origen",
      "campo_destino": "nombre en destino",
      "descripcion": "qué representa",
      "confianza": 0.95
    }}
  ],
  "credenciales_necesarias": ["UN item por credencial, ej: 'usuario_arcfast', 'password_arcfast'"],
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
  "excepciones": [{{"situacion": "qué puede salir mal", "accion": "qué hacer"}}],
  "reporte_incluir": ["datos a incluir en el reporte"]
}}"""})

    resp_plan = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": contenido}],
    )

    plan = _parsear_json(resp_plan.content[0].text)
    if not plan:
        raise ValueError("Claude no devolvió un plan JSON válido")

    # ── Paso 2: preguntas inteligentes (inspirado en cerebro/procesar.py) ──────
    analisis = hacer_preguntas_inteligentes(plan, transcripcion)

    return {
        "plan":      plan,
        "preguntas": analisis["preguntas"],
        "ya_se":     analisis.get("ya_se", []),
    }


def hacer_preguntas_inteligentes(plan_inicial: dict, transcripcion: str) -> dict:
    """
    Identifica qué información genuinamente falta para ejecutar el proceso.
    Retorna {"preguntas": [...], "ya_se": [...]} — sin llamar input().
    Cada pregunta es UN solo dato (nunca mezcla usuario y contraseña en una).
    """
    respuesta = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": f"""Eres un agente inteligente que aprendió un proceso web observando a un usuario.

Plan generado:
{json.dumps(plan_inicial, indent=2, ensure_ascii=False)}

El usuario explicó: "{transcripcion or '(sin audio)'}"

Identifica QUÉ información genuinamente te falta para ejecutar este proceso.

REGLAS:
- NO preguntes sobre botones, menús ni navegación — eso lo ves en pantalla
- NO preguntes datos que son visibles en los screenshots (nombres de producto, fechas, cantidades)
- SÍ pregunta sobre: credenciales, datos que el usuario escribió y no se veían (campos con asteriscos)
- Cada pregunta cubre UN SOLO dato — nunca preguntes "usuario y contraseña" juntos
- Si el plan lista credenciales_necesarias, genera una pregunta por cada item de esa lista
- Máximo 4 preguntas. Si no falta nada, deja preguntas vacío.
- Indica es_password: true para contraseñas, tokens y claves secretas

Responde SOLO JSON:
{{
  "preguntas": [
    {{
      "campo": "nombre_interno_sin_espacios",
      "pregunta": "Pregunta clara y específica al sistema detectado",
      "por_que": "por qué no pudiste inferirlo de los screenshots",
      "es_password": false
    }}
  ],
  "ya_se": ["dato concreto que aprendí sin necesitar preguntar"]
}}"""}],
    )

    data = _parsear_json(respuesta.content[0].text)
    if not data:
        data = {"preguntas": [], "ya_se": []}
    data.setdefault("preguntas", [])
    data.setdefault("ya_se", [])

    # Asegurar es_password por nombre del campo si Claude no lo incluyó
    for p in data.get("preguntas", []):
        if "es_password" not in p:
            p["es_password"] = any(
                w in p.get("campo", "").lower()
                for w in ["password", "contraseña", "clave", "pass", "token", "secret", "pwd"]
            )

    return data


# ─── Fase B ───────────────────────────────────────────────────────────────────

def completar_plan(resultado_fase_a: dict, respuestas_usuario: dict) -> tuple:
    """
    Recibe las respuestas del frontend HTML y las integra en el plan.
    Retorna (plan_completo, lista_de_advertencias).
    """
    plan = resultado_fase_a.get("plan", resultado_fase_a)

    advertencias = []
    for p in resultado_fase_a.get("preguntas", []):
        if not respuestas_usuario.get(p["campo"]):
            advertencias.append(f"Falta respuesta para: {p['pregunta']}")

    plan["credenciales_obtenidas"] = respuestas_usuario

    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/plan.json", "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    return plan, advertencias
