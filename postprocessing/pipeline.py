"""
postprocessing/pipeline.py
--------------------------
Toma el AgentResult y corre el pipeline de post-procesamiento:
  1. Gemini extrae y estructura datos del PDF
  2. Solana registra el hash de la orden (audit trail inmutable → integridad)
  3. MongoDB guarda la orden estructurada (cifrada → confidencialidad)
  4. Envía email al usuario registrado (TLS en tránsito)

Seguridad de datos financieros:
  - postprocessing/crypto.py     → confidencialidad (cifrado Fernet en reposo)
  - postprocessing/solana_audit  → integridad (hash anclado on-chain)
"""

from __future__ import annotations

from shared.schemas import AgentResult
from postprocessing.solana_audit import registrar_en_solana_safe
from postprocessing import crypto


def run_pipeline(result: AgentResult, pdf_path: str, user_email: str) -> dict:
    """
    Entry point. Devuelve el TX signature de Solana, el hash y el id de Mongo.
    """
    datos = extraer_con_gemini(pdf_path, result)
    solana_result = registrar_en_solana_safe(datos, fallback_on_error=True)
    mongo_id = guardar_en_mongo(datos, solana_result)
    enviar_email(user_email, solana_result, mongo_id)

    return {
        "solana_tx_signature": solana_result["tx_signature"],
        "solana_hash":         solana_result["payload_hash"],
        "solana_explorer_url": solana_result.get("explorer_url"),
        "mongo_id":            mongo_id,
        "status":              "ok",
    }


def extraer_con_gemini(pdf_path: str, result: AgentResult) -> dict:
    """
    Normaliza los datos de la orden combinando el PDF y el AgentResult.
    TODO: integrar google-generativeai SDK para leer el PDF.
    """
    return {
        "missing_products": [p.to_dict() for p in result.missing_products],
        "errores":          result.errores,
        "challenges":       result.challenges,
        "url_portal":       result.workflow.url_portal,
        "total_missing":    len(result.missing_products),
        "valor_estimado":   sum(p.precio_unitario * p.cantidad
                                for p in result.missing_products),
    }


def guardar_en_mongo(datos: dict, solana_result: dict) -> str:
    """
    Guarda la orden en MongoDB. El detalle financiero (missing_products,
    valor_estimado) se cifra antes de persistir; el hash de Solana queda en
    claro para poder auditar la integridad on-chain.

    TODO: conectar con pymongo:
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGO_URI"))
        result = client["arcavision"]["ordenes"].insert_one(documento)
        return str(result.inserted_id)
    """
    documento = {
        # Campos financieros sensibles → cifrados en reposo
        "detalle_cifrado":     crypto.cifrar_json({
            "missing_products": datos.get("missing_products", []),
            "valor_estimado":   datos.get("valor_estimado", 0),
        }),
        # Metadatos no sensibles + integridad → en claro
        "url_portal":          datos.get("url_portal", ""),
        "total_missing":       datos.get("total_missing", 0),
        "solana_tx_signature": solana_result["tx_signature"],
        "solana_hash":         solana_result["payload_hash"],
        "solana_explorer_url": solana_result.get("explorer_url"),
    }
    print(f"  [MONGO] Documento (detalle financiero cifrado: "
          f"{crypto.esta_cifrado(documento['detalle_cifrado'])})")
    return "mock_mongo_id_abc123"


def enviar_email(user_email: str, solana_result: dict, mongo_id: str):
    """
    Envía el reporte al usuario. El cuerpo viaja cifrado en tránsito (TLS) vía
    el SMTP_SSL de postprocessing.reporte.enviar_ticket(); aquí solo se reporta
    el anclaje de integridad en Solana.

    TODO: integrar SendGrid o smtplib para el envío real desde este path.
    """
    print(f"  [EMAIL] Enviando reporte a {user_email}")
    print(f"    Solana TX:   {solana_result['tx_signature']}")
    print(f"    Hash orden:  {solana_result['payload_hash']}")
    if solana_result.get("explorer_url"):
        print(f"    Explorer:    {solana_result['explorer_url']}")
    print(f"    MongoDB ID:  {mongo_id}")
