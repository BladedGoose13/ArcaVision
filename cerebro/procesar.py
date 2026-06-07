import json
import base64
import os
import wave
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

_api_key = os.getenv("ANTHROPIC_API_KEY")
if not _api_key:
    raise RuntimeError("ANTHROPIC_API_KEY no está configurada en el entorno")
client = Anthropic(api_key=_api_key)


def transcribir_audio(audio_path: str) -> str:
    """Transcribe el audio usando Groq Whisper."""
    print("  🎤 Transcribiendo audio con Groq Whisper...")
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
        print(f"  ⚠️  Error transcribiendo: {e}")
        print("  Ingresa manualmente lo que explicaste:")
        return input("  Transcripción: ").strip()


def hacer_preguntas_inteligentes(plan_inicial: dict, transcripcion: str) -> dict:
    print("\n🤔 Analizando qué información falta...")
    respuesta = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""Eres un agente inteligente que aprendió un proceso web observando a un usuario.

Plan generado:
{json.dumps(plan_inicial, indent=2, ensure_ascii=False)}

El usuario explicó: "{transcripcion}"

Identifica QUÉ información genuinamente te falta para ejecutar este proceso.

REGLAS:
- NO preguntes sobre botones, menús, navegación — eso lo ves en pantalla
- NO preguntes si "iniciar sesión" es "login" — eso lo sabes
- SÍ pregunta sobre: credenciales, datos específicos que el usuario escribió y no se veían
- Máximo 3 preguntas. Si no falta nada, deja preguntas vacío.

Responde SOLO JSON:
{{
  "preguntas": [
    {{
      "campo": "nombre interno del dato",
      "pregunta": "pregunta clara para el usuario",
      "por_que": "por qué no pudiste inferirlo"
    }}
  ],
  "ya_se": ["cosas que aprendiste sin preguntar"]
}}"""
        }]
    )
    raw = respuesta.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


def procesar_sesion(eventos: list, audio_path: str) -> dict:
    print("\n🧠 Procesando sesión...")

    transcripcion = transcribir_audio(audio_path)
    print(f"  ✅ '{transcripcion[:100]}{'...' if len(transcripcion) > 100 else ''}'")

    con_screenshot = [e for e in eventos if e.get("screenshot")]
    if not con_screenshot:
        raise ValueError("No hay screenshots. ¿Se grabó correctamente?")

    paso = max(1, len(con_screenshot) // 10)
    keyframes = con_screenshot[::paso][:10]
    print(f"  📸 {len(keyframes)} screenshots de {len(eventos)} eventos")

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

Los campos pueden tener nombres DISTINTOS en cada sistema — aprende el mapeo real.
NUNCA uses selectores CSS ni IDs. Describe elementos visualmente.

Responde SOLO este JSON:
{{
  "plataforma_origen": "nombre del sistema origen",
  "plataforma_destino": "nombre del sistema destino",
  "objetivo": "qué logra este proceso",
  "mapeo_campos": [
    {{
      "campo_origen": "nombre en origen",
      "campo_destino": "nombre en destino",
      "descripcion": "qué representa"
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
  "reporte_incluir": ["datos a incluir en el reporte por correo"]
}}"""
    })

    print("  🤖 Claude analizando...")
    respuesta = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": contenido}]
    )

    raw = respuesta.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    plan_inicial = json.loads(raw)

    analisis = hacer_preguntas_inteligentes(plan_inicial, transcripcion)

    if analisis.get("ya_se"):
        print(f"\n  ✅ Aprendí sin preguntar:")
        for cosa in analisis["ya_se"]:
            print(f"     • {cosa}")

    credenciales_obtenidas = {}
    preguntas = analisis.get("preguntas", [])

    if preguntas:
        print(f"\n  ❓ Necesito algunos datos que no pude ver:\n")
        for p in preguntas:
            print(f"  Por qué lo necesito: {p['por_que']}")
            valor = input(f"  {p['pregunta']}: ").strip()
            credenciales_obtenidas[p["campo"]] = valor
            print()
        plan_inicial["credenciales_obtenidas"] = credenciales_obtenidas
    else:
        print("\n  ✅ Entendí todo — no necesito preguntar nada más")

    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/plan.json", "w", encoding="utf-8") as f:
        json.dump(plan_inicial, f, indent=2, ensure_ascii=False)

    print(f"\n{'─'*50}")
    print(f"  Origen  : {plan_inicial.get('plataforma_origen')}")
    print(f"  Destino : {plan_inicial.get('plataforma_destino')}")
    print(f"  Pasos   : {len(plan_inicial.get('pasos', []))}")
    print(f"  Mapeo   : {len(plan_inicial.get('mapeo_campos', []))} campos")
    print(f"{'─'*50}")

    return plan_inicial