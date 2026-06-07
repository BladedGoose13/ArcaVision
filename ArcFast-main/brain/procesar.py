"""
brain/procesar.py  —  Cerebro unificado de ArcFast
----------------------------------------------------
Reemplaza cerebro/procesar.py y core/procesar.py (eran idénticos).

Cambios respecto al original:
  - Totalmente async (compatible con FastAPI sin asyncio.run())
  - JSON parsing robusto con regex + retry automático al modelo
  - Sin input() — las preguntas se devuelven como datos, no se hacen por consola
  - analizar_sesion devuelve las preguntas reales (no [] forzado vacío)
  - completar_plan devuelve solo el plan (no una tupla que rompe si cambia)
  - Path de sesiones relativo al archivo, no al CWD
  - Credenciales NO se guardan en el plan persistido (seguridad)
  - Retry con back-off exponencial en llamadas a la API
  - Keyframe sampling mejorado: garantiza diversidad temporal
  - Transcripción con fallback a texto vacío (no bloquea por consola)
  - Modo CLI opcional solo vía argumento explícito
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic, APIStatusError, APIConnectionError
from dotenv import load_dotenv

load_dotenv()

# Cliente async — no necesita api_key explícita (lee ANTHROPIC_API_KEY del env)
_client = AsyncAnthropic()

# Directorio de sesiones siempre relativo a este archivo
SESIONES_DIR = Path(__file__).parent.parent / "sesiones"

# Modelos
MODEL_VISION   = "claude-opus-4-5"
MODEL_PREGUNTAS = "claude-opus-4-5"

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extraer_json(texto: str) -> Any:
    """
    Extrae el primer bloque JSON válido del texto del modelo.
    Soporta:
      - JSON puro
      - ```json ... ```
      - ```...```
      - JSON embebido con texto antes/después
    Lanza ValueError si no encuentra nada parseable.
    """
    # 1. Intentar parsear directo
    try:
        return json.loads(texto.strip())
    except json.JSONDecodeError:
        pass

    # 2. Extraer bloque de código (```json ... ``` o ``` ... ```)
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", texto)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Buscar el primer { ... } o [ ... ] balanceado en el texto
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        idx = texto.find(start_char)
        if idx == -1:
            continue
        depth = 0
        for i, ch in enumerate(texto[idx:], idx):
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(texto[idx:i+1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"No se encontró JSON válido en la respuesta del modelo:\n{texto[:300]}")


async def _llamar_con_retry(
    *,
    messages: list[dict],
    model: str,
    max_tokens: int,
    system: str | None = None,
    max_intentos: int = 3,
    etiqueta: str = "llamada",
) -> str:
    """
    Llama a la API de Anthropic con retry y back-off exponencial.
    Devuelve el texto de la primera respuesta de texto.
    """
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, messages=messages)
    if system:
        kwargs["system"] = system

    ultimo_error: Exception | None = None
    for intento in range(1, max_intentos + 1):
        try:
            resp = await _client.messages.create(**kwargs)
            # Extraer primer bloque de texto
            for bloque in resp.content:
                if bloque.type == "text":
                    return bloque.text
            raise ValueError("La respuesta del modelo no contiene texto")
        except (APIStatusError, APIConnectionError) as e:
            ultimo_error = e
            espera = 2 ** intento          # 2s, 4s, 8s
            print(f"  ⚠️  {etiqueta} intento {intento}/{max_intentos} falló ({e}). Reintentando en {espera}s…")
            await asyncio.sleep(espera)
        except Exception as e:
            raise RuntimeError(f"{etiqueta}: error inesperado — {e}") from e

    raise RuntimeError(f"{etiqueta}: todos los intentos fallaron. Último error: {ultimo_error}") from ultimo_error


async def _llamar_json_con_retry(
    *,
    messages: list[dict],
    model: str,
    max_tokens: int,
    system: str | None = None,
    max_intentos: int = 3,
    etiqueta: str = "llamada",
) -> Any:
    """
    Como _llamar_con_retry pero extrae y parsea JSON.
    Si el modelo no devuelve JSON válido, reintenta pidiéndole que corrija.
    """
    historial = list(messages)

    for intento in range(1, max_intentos + 1):
        texto = await _llamar_con_retry(
            messages=historial,
            model=model,
            max_tokens=max_tokens,
            system=system,
            max_intentos=2,
            etiqueta=f"{etiqueta} intento {intento}",
        )
        try:
            return _extraer_json(texto)
        except ValueError:
            if intento == max_intentos:
                raise ValueError(
                    f"{etiqueta}: el modelo no devolvió JSON válido tras {max_intentos} intentos.\n"
                    f"Última respuesta:\n{texto[:500]}"
                )
            # Pedir corrección sin reiniciar el contexto
            historial.append({"role": "assistant", "content": texto})
            historial.append({
                "role": "user",
                "content": (
                    "Tu respuesta anterior no es JSON válido. "
                    "Responde ÚNICAMENTE con el JSON solicitado, sin texto adicional, "
                    "sin backticks, sin explicaciones."
                ),
            })
            await asyncio.sleep(1)


# ─── Transcripción de audio ───────────────────────────────────────────────────

async def transcribir_audio(audio_path: str, cli_fallback: bool = False) -> str:
    """
    Transcribe audio usando Groq Whisper (async via executor).
    Si falla y cli_fallback=True, pide al usuario texto por consola (solo CLI).
    Si falla y cli_fallback=False, devuelve cadena vacía.
    """
    print("  🎤 Transcribiendo audio con Groq Whisper…")
    try:
        from groq import Groq
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        def _transcribir() -> str:
            with open(audio_path, "rb") as f:
                t = groq_client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=f,
                    language="es",
                )
            return t.text

        texto = await asyncio.get_event_loop().run_in_executor(None, _transcribir)
        return texto

    except Exception as e:
        print(f"  ⚠️  Error transcribiendo: {e}")
        if cli_fallback:
            print("  Ingresa manualmente lo que explicaste:")
            return input("  Transcripción: ").strip()
        return ""


# ─── Keyframe sampling ────────────────────────────────────────────────────────

def _seleccionar_keyframes(eventos: list[dict], n: int = 10) -> list[dict]:
    """
    Selecciona hasta n keyframes con screenshots de forma temporalmente uniforme.
    Garantiza que con 1 screenshot se devuelve 1 (no el mismo repetido n veces).
    Con k < n screenshots devuelve los k disponibles sin repetir.
    """
    con_screenshot = [e for e in eventos if e.get("screenshot")]
    if not con_screenshot:
        return []

    total = len(con_screenshot)
    if total <= n:
        return con_screenshot           # devuelve todos, sin duplicar

    # Distribución uniforme de índices
    indices = [int(round(i * (total - 1) / (n - 1))) for i in range(n)]
    # Deduplica manteniendo orden
    vistos = set()
    resultado = []
    for idx in indices:
        if idx not in vistos:
            vistos.add(idx)
            resultado.append(con_screenshot[idx])
    return resultado


# ─── Fase A: analizar sesión ──────────────────────────────────────────────────

async def analizar_sesion(eventos: list[dict], audio_path: str) -> dict:
    """
    Analiza la sesión grabada y devuelve:
    {
        "plan": { ... },
        "preguntas": [ {campo, pregunta, por_que}, ... ],
        "ya_se": [ ... ]
    }

    No hace input() ni bloquea. Las preguntas se devuelven para que
    el frontend las presente al usuario.
    """
    print("\n🧠 Analizando sesión…")

    transcripcion = await transcribir_audio(audio_path, cli_fallback=False)
    if transcripcion:
        print(f"  ✅ Transcripción: '{transcripcion[:100]}{'…' if len(transcripcion) > 100 else ''}'")
    else:
        print("  ⚠️  Sin transcripción — analizando solo por imágenes")

    keyframes = _seleccionar_keyframes(eventos, n=10)
    if not keyframes:
        raise ValueError("No hay screenshots en la sesión. ¿Se grabó correctamente?")

    print(f"  📸 {len(keyframes)} keyframes de {len(eventos)} eventos totales")

    # Construir contenido multimodal
    contenido: list[dict] = []
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
                f"Momento {i+1}/{len(keyframes)}: "
                f"{evento.get('tipo','evento')} "
                f"en ({evento.get('x', '?')}, {evento.get('y', '?')})"
            ),
        })

    contenido.append({
        "type": "text",
        "text": f"""
El usuario explicó mientras trabajaba:
"{transcripcion}"

Analiza TODO y genera el plan. El usuario trabajó con DOS sistemas:
- ORIGEN: donde están los datos del cliente
- DESTINO: donde se registran los datos (sistema Arca Continental)

Los campos pueden tener nombres DISTINTOS en cada sistema — aprende el mapeo real.
NUNCA uses selectores CSS ni IDs. Describe elementos visualmente.

Responde SOLO este JSON (sin texto adicional, sin backticks):
{{
  "plataforma_origen": "nombre del sistema origen",
  "plataforma_destino": "nombre del sistema destino",
  "objetivo": "qué logra este proceso en una oración",
  "mapeo_campos": [
    {{
      "campo_origen": "nombre en origen",
      "campo_destino": "nombre en destino",
      "descripcion": "qué representa",
      "confianza": 0.0
    }}
  ],
  "credenciales_necesarias": ["lista de datos que el bot necesita pero no vio en pantalla"],
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
}}""",
    })

    print("  🤖 Claude analizando keyframes + audio…")
    plan = await _llamar_json_con_retry(
        messages=[{"role": "user", "content": contenido}],
        model=MODEL_VISION,
        max_tokens=16000,
        etiqueta="analizar_sesion/plan",
    )

    # Fase de preguntas inteligentes
    print("\n🤔 Determinando qué información falta…")
    analisis = await _llamar_json_con_retry(
        messages=[{
            "role": "user",
            "content": f"""Eres un agente que aprendió un proceso web observando a un usuario.

Plan generado:
{json.dumps(plan, indent=2, ensure_ascii=False)}

El usuario explicó: "{transcripcion}"

Identifica QUÉ información genuinamente te falta para ejecutar este proceso.

REGLAS:
- NO preguntes sobre botones, menús, navegación — eso lo ves en pantalla
- NO preguntes si "iniciar sesión" es "login" — eso lo sabes
- SÍ pregunta sobre: credenciales, datos específicos que el usuario escribió y no se veían en pantalla
- Máximo 3 preguntas. Si no falta nada crítico, deja preguntas vacío.

Responde SOLO JSON (sin texto adicional, sin backticks):
{{
  "preguntas": [
    {{
      "campo": "nombre_interno_del_dato",
      "pregunta": "pregunta clara para el usuario",
      "por_que": "por qué no pudiste inferirlo de las imágenes"
    }}
  ],
  "ya_se": ["lista de cosas que aprendiste sin preguntar"]
}}""",
        }],
        model=MODEL_PREGUNTAS,
        max_tokens=2000,
        etiqueta="analizar_sesion/preguntas",
    )

    preguntas = analisis.get("preguntas", [])
    ya_se     = analisis.get("ya_se", [])

    if ya_se:
        print(f"\n  ✅ Aprendí sin preguntar ({len(ya_se)}):")
        for cosa in ya_se[:5]:
            print(f"     • {cosa}")

    if preguntas:
        print(f"\n  ❓ Necesito {len(preguntas)} dato(s) del usuario antes de ejecutar")
    else:
        print("\n  ✅ Entendí todo — no necesito preguntar nada más")

    # Guardar plan SIN credenciales (se añaden en completar_plan al ejecutar)
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = SESIONES_DIR / "plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    _imprimir_resumen(plan)

    return {
        "plan": plan,
        "preguntas": preguntas,
        "ya_se": ya_se,
    }


# ─── Fase B: completar plan con respuestas del usuario ───────────────────────

def completar_plan(resultado_fase_a: dict, respuestas_usuario: dict) -> dict:
    """
    Combina el plan de la Fase A con las respuestas del usuario.
    Devuelve solo el plan enriquecido (no una tupla).
    Las credenciales NO se persisten en disco — solo viven en memoria
    durante la sesión de ejecución para no guardar passwords en SQLite.
    """
    plan = resultado_fase_a.get("plan", resultado_fase_a)
    # Copia para no mutar el original
    plan_ejecucion = {**plan, "credenciales_obtenidas": respuestas_usuario}
    return plan_ejecucion


# ─── Helpers de presentación ─────────────────────────────────────────────────

def _imprimir_resumen(plan: dict) -> None:
    sep = "─" * 52
    print(f"\n{sep}")
    print(f"  Origen  : {plan.get('plataforma_origen', '?')}")
    print(f"  Destino : {plan.get('plataforma_destino', '?')}")
    print(f"  Pasos   : {len(plan.get('pasos', []))}")
    print(f"  Mapeo   : {len(plan.get('mapeo_campos', []))} campos")
    print(f"{sep}")


# ─── Entrypoint CLI (solo cuando se usa desde main.py) ───────────────────────

async def procesar_sesion_cli(eventos: list[dict], audio_path: str) -> dict:
    """
    Variante CLI de analizar_sesion:
    - Usa transcripción con fallback a input() si Groq falla
    - Hace las preguntas directamente por consola
    - Devuelve el plan con credenciales ya incorporadas
    Solo para uso desde main.py, nunca desde FastAPI.
    """
    print("\n🧠 Procesando sesión (modo CLI)…")

    transcripcion = await transcribir_audio(audio_path, cli_fallback=True)
    if transcripcion:
        print(f"  ✅ '{transcripcion[:100]}{'…' if len(transcripcion) > 100 else ''}'")

    keyframes = _seleccionar_keyframes(eventos, n=10)
    if not keyframes:
        raise ValueError("No hay screenshots. ¿Se grabó correctamente?")

    print(f"  📸 {len(keyframes)} keyframes de {len(eventos)} eventos")

    # Reusar analizar_sesion (sin cli_fallback ya resuelto arriba)
    resultado = await analizar_sesion(eventos, audio_path)
    plan      = resultado["plan"]
    preguntas = resultado["preguntas"]

    credenciales: dict = {}
    if preguntas:
        print(f"\n  ❓ Necesito algunos datos que no pude ver:\n")
        for p in preguntas:
            print(f"  Por qué lo necesito: {p['por_que']}")
            import getpass
            campo = p["campo"]
            es_pass = any(w in campo.lower() for w in ["password", "contraseña", "clave", "pass"])
            valor = getpass.getpass(f"  {p['pregunta']}: ") if es_pass else input(f"  {p['pregunta']}: ").strip()
            credenciales[campo] = valor
            print()

    return completar_plan({"plan": plan}, credenciales)
