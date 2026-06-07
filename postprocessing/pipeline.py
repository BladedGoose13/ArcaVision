"""
postprocessing/pipeline.py  —  PERSONA 3
------------------------------------------
Toma el AgentResult y corre el pipeline completo:
  1. Gemini extrae y estructura datos del PDF
  2. Solana registra hash de la orden (audit trail)
  3. MongoDB guarda la orden estructurada
  4. Envía email al usuario registrado
"""

from shared.schemas import AgentResult


def run_pipeline(result: AgentResult, pdf_path: str, user_email: str) -> dict:
    """
    Entry point. Persona 4 llama esto después de generar el PDF.
    Devuelve las URLs del dashboard y el hash de Solana.
    """
    datos = extraer_con_gemini(pdf_path, result)
    solana_hash = registrar_en_solana(datos)
    mongo_id = guardar_en_mongo(datos, solana_hash)
    enviar_email(user_email, solana_hash, mongo_id)

    return {
        "solana_hash": solana_hash,
        "mongo_id": mongo_id,
        "status": "ok",
    }


def extraer_con_gemini(pdf_path: str, result: AgentResult) -> dict:
    """
    Usa Gemini para leer el PDF y normalizar los datos de la orden.
    Combina con el AgentResult para tener el dataset completo.

    TODO Persona 3: integrar google-generativeai SDK
    """
    # Estructura que se guarda en Mongo y se hashea en Solana
    return {
        "missing_products": [p.to_dict() for p in result.missing_products],
        "errores": result.errores,
        "challenges": result.challenges,
        "url_portal": result.workflow.url_portal,
        "total_missing": len(result.missing_products),
        "valor_estimado": sum(
            p.precio_unitario * p.cantidad
            for p in result.missing_products
        ),
    }


def registrar_en_solana(datos: dict) -> str:
    """
    Genera un hash SHA-256 local. Pendiente: enviar a Solana devnet via solana-py.
    Returns: hash SHA-256 del payload (mock hasta integración real)
    """
    import hashlib
    import json as _json
    payload = _json.dumps(datos, sort_keys=True).encode()
    local_hash = hashlib.sha256(payload).hexdigest()
    print(f"  [Solana] Hash generado localmente (sin enviar): {local_hash[:16]}...")
    return local_hash


def guardar_en_mongo(datos: dict, solana_hash: str) -> str:
    """
    Pendiente: conectar con pymongo para persistencia real.
    Returns: _id del documento (mock hasta integración real)
    """
    print(f"  [MongoDB] Guardado pendiente de integración. Datos: {list(datos.keys())}")
    return "mock_mongo_id_abc123"


def enviar_email(user_email: str, solana_hash: str, mongo_id: str):
    """
    Pendiente: integrar SendGrid o smtplib para envío real.
    """
    print(f"  [Email] Envío pendiente de integración → {user_email}")
    print(f"    Solana hash: {solana_hash}")
    print(f"    MongoDB ID:  {mongo_id}")
