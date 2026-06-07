"""
core/procesar.py
----------------
Fase A: analizar_sesion   → genera plan + preguntas (sin input(), devuelve al frontend)
Fase B: completar_plan    → recibe respuestas del frontend, cierra el plan
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


# ─── Transcripción ────────────────────────────────────────────────────────────

def transcribir_audio(audio_path: str) -> str:
    """Transcribe el audio con Groq Whisper. Si falla, devuelve cadena vacía."""
    if not audio_path or not Path(audio_path).exists():
        return ""
    try:
        from groq import Groq
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with open(audio_path, "rb") as f:
            transcript = groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                language="es",
            )
        return transcript.text.strip()
    except Exception as e:
        print(f"  ⚠️  Groq no disponible: {e}. Continuando sin audio.")
        return ""


# ─── Fase A: análisis ─────────────────────────────────────────────────────────

def analizar_sesion(eventos: list, audio_path: str) -> dict:
    """
    Analiza los eventos grabados y el audio.
    Devuelve {"plan": {...}, "preguntas": [...], "ya_se": [...]}
    SIN llamar a input() — las preguntas se muestran en el frontend.
    """
    transcripcion = transcribir_audio(audio_path)

    con_screenshot = [e for e in eventos if e.get("screenshot")]
    if not con_screenshot:
        raise ValueError("No hay screenshots en la grabación. ¿Se grabó correctamente?")

    # Seleccionar hasta 10 keyframes distribuidos uniformemente
    paso = max(1, len(con_screenshot) // 10)
    keyframes = con_screenshot[::paso][:10]

    # ── Paso 1: generar plan desde screenshots + audio ─────────────────────────
    contenido = []
    for i, evento in enumerate(keyframes):
        contenido.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": evento["screenshot"],
            },
        })
        contenido.append({
            "type": "text",
            "text": (
                f"Momento {i+1}: acción '{evento['tipo']}' "
                f"en coordenadas ({evento.get('x','?')}, {evento.get('y','?')})"
            ),
        })

    contexto_audio = (
        f'\nEl usuario explicó en voz alta mientras trabajaba:\n"{transcripcion}"\n'
        if transcripcion
        else "\n(No hay audio disponible — infiere el proceso solo desde las imágenes)\n"
    )

    contenido.append({
        "type": "text",
        "text": f"""{contexto_audio}
Analiza TODO y genera un plan ejecutable. El usuario trabajó con DOS sistemas:
- ORIGEN: de donde se extraen los datos (ERP, portal del proveedor, etc.)
- DESTINO: donde se registran (portal ARCFAST u otro sistema de Arca Continental)

REGLAS IMPORTANTES:
- Describe los elementos de forma VISUAL (no uses selectores CSS ni IDs)
- Usa el texto exacto visible en pantalla para identificar botones y campos
- Los campos pueden tener nombres distintos en cada sistema — aprende el mapeo real
- En "credenciales_necesarias" incluye SOLO datos que el bot NO puede ver en pantalla
  (contraseñas, tokens, datos que el usuario escribió fuera de cámara)

Responde ÚNICAMENTE este JSON (sin texto adicional, sin backticks):
{{
  "plataforma_origen": "nombre del sistema de origen",
  "plataforma_destino": "nombre del sistema de destino",
  "objetivo": "descripción concisa de lo que logra este proceso",
  "mapeo_campos": [
    {{
      "campo_origen": "nombre visible en origen",
      "campo_destino": "nombre visible en destino",
      "descripcion": "qué representa este dato",
      "confianza": 0.95
    }}
  ],
  "credenciales_necesarias": ["lista de datos que el bot necesitará pero no vio"],
  "pasos": [
    {{
      "numero": 1,
      "sistema": "origen|destino",
      "intencion": "descripción visual de qué hacer y dónde",
      "accion": "navegar|click|escribir|seleccionar|verificar|esperar|extraer",
      "valor": "URL o texto a escribir, vacío si no aplica",
      "validacion": "cómo saber que el paso funcionó"
    }}
  ],
  "excepciones": [
    {{"situacion": "qué puede salir mal", "accion": "qué hacer en ese caso"}}
  ],
  "reporte_incluir": ["datos que deben aparecer en el reporte final al usuario"]
}}""",
    })

    resp_plan = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": contenido}],
    )

    raw = resp_plan.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    plan = json.loads(raw)

    # ── Paso 2: generar preguntas coherentes ──────────────────────────────────
    preguntas_data = _generar_preguntas(plan, transcripcion)

    return {
        "plan":      plan,
        "preguntas": preguntas_data["preguntas"],
        "ya_se":     preguntas_data["ya_se"],
    }


def _generar_preguntas(plan: dict, transcripcion: str) -> dict:
    """
    Genera preguntas COHERENTES sobre lo que el agente realmente necesita
    y no puede inferir. Devuelve dict con 'preguntas' y 'ya_se'.
    """
    credenciales_declaradas = plan.get("credenciales_necesarias", [])
    pasos_str = json.dumps(plan.get("pasos", []), ensure_ascii=False, indent=2)
    mapeo_str = json.dumps(plan.get("mapeo_campos", []), ensure_ascii=False, indent=2)

    resp = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""Eres el agente ArcFast. Acabas de aprender un proceso observando al usuario.

PLAN GENERADO:
- Origen: {plan.get("plataforma_origen")}
- Destino: {plan.get("plataforma_destino")}
- Objetivo: {plan.get("objetivo")}

PASOS:
{pasos_str}

MAPEO DE CAMPOS:
{mapeo_str}

CREDENCIALES QUE YA DETECTÉ COMO NECESARIAS: {credenciales_declaradas}

LO QUE EL USUARIO EXPLICÓ: "{transcripcion or '(sin audio)'}"

Tu tarea: determina qué datos necesitas pedirle al usuario para ejecutar este proceso.

REGLAS ESTRICTAS:
1. NO preguntes sobre navegación, botones ni menús — los ves en pantalla
2. NO preguntes datos que son visibles en los screenshots (nombres de productos, fechas, cantidades)
3. SÍ pregunta: contraseñas, tokens de autenticación, datos que el usuario escribió
   sin que la cámara lo capturara claramente (ej: campos con asteriscos)
4. Si el plan ya lista credenciales_necesarias, genera una pregunta por cada una
5. Máximo 4 preguntas. Si no falta nada crítico, deja "preguntas" vacío
6. Las preguntas deben ser en español, claras y específicas al sistema detectado

Responde ÚNICAMENTE este JSON:
{{
  "preguntas": [
    {{
      "campo": "nombre_interno_sin_espacios",
      "pregunta": "Pregunta clara dirigida al usuario",
      "por_que": "Explicación breve de por qué no puedes inferirlo",
      "es_password": true
    }}
  ],
  "ya_se": [
    "Dato concreto que aprendí sin necesitar preguntarlo"
  ]
}}""",
        }],
    )

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"preguntas": [], "ya_se": []}

    # Garantizar que el campo es_password exista en cada pregunta
    for p in data.get("preguntas", []):
        if "es_password" not in p:
            p["es_password"] = any(
                w in p.get("campo", "").lower()
                for w in ["password", "contraseña", "clave", "pass", "token", "secret"]
            )

    return data


# ─── Fase B: completar plan con respuestas del usuario ────────────────────────

def completar_plan(resultado_fase_a: dict, respuestas_usuario: dict) -> tuple:
    """
    Recibe el resultado de analizar_sesion y las respuestas del frontend.
    Devuelve (plan_completo, lista_de_advertencias).
    """
    plan = resultado_fase_a.get("plan", resultado_fase_a)

    advertencias = []
    preguntas = resultado_fase_a.get("preguntas", [])
    for p in preguntas:
        campo = p["campo"]
        if campo not in respuestas_usuario or not respuestas_usuario[campo]:
            advertencias.append(f"Falta respuesta para: {p['pregunta']}")

    plan["credenciales_obtenidas"] = respuestas_usuario

    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/plan.json", "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    return plan, advertencias
