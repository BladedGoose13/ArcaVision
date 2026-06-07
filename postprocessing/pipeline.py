"""
postprocessing/pipeline.py  —  PERSONA 3
------------------------------------------
Toma el AgentResult y corre el pipeline completo:
  1. Gemini extrae y estructura datos del PDF
  2. Solana registra hash de la orden (audit trail inmutable)
  3. MongoDB guarda la orden estructurada
  4. Envía email al usuario registrado
"""

from __future__ import annotations
import os
from shared.schemas import AgentResult
from postprocessing.solana_audit import registrar_en_solana_safe


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_pipeline(result: AgentResult, pdf_path: str, user_email: str) -> dict:
    """
    Entry point. Persona 4 llama esto después de generar el PDF.
    Devuelve las URLs del dashboard, el TX signature de Solana y el hash.
    """
    datos = extraer_con_gemini(pdf_path, result)
    solana_result = registrar_en_solana(datos)
    mongo_id = guardar_en_mongo(datos, solana_result)
    enviar_email(user_email, solana_result, mongo_id)

    return {
        "solana_tx_signature": solana_result["tx_signature"],
        "solana_hash":         solana_result["payload_hash"],
        "solana_explorer_url": solana_result["explorer_url"],
        "mongo_id":            mongo_id,
        "status":              "ok",
    }


# ---------------------------------------------------------------------------
# Paso 1 — Gemini extrae y normaliza datos de la orden
# ---------------------------------------------------------------------------

def extraer_con_gemini(pdf_path: str, result: AgentResult) -> dict:
    """
    Usa Gemini para leer el PDF y normalizar los datos de la orden.
    Combina con el AgentResult para tener el dataset completo.

    TODO Persona 3: integrar google-generativeai SDK con:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-1.5-flash")
        pdf_part = genai.upload_file(pdf_path, mime_type="application/pdf")
        response = model.generate_content([pdf_part, prompt])
    """
    # Estructura que se serializa para Solana y se guarda en Mongo
    return {
        "missing_products": [p.to_dict() for p in result.missing_products],
        "errores":          result.errores,
        "challenges":       result.challenges,
        "url_portal":       result.workflow.url_portal,
        "total_missing":    len(result.missing_products),
        "valor_estimado":   sum(
            p.precio_unitario * p.cantidad
            for p in result.missing_products
        ),
    }


# ---------------------------------------------------------------------------
# Paso 2 — Solana audit trail
# ---------------------------------------------------------------------------

def registrar_en_solana(datos: dict) -> dict:
    """
    Registra el hash SHA-256 del registro de compra-venta en Solana Devnet.

    En producción requiere SOLANA_PRIVATE_KEY en .env.
    Si la key no está presente usa fallback local (para dev/demo).

    Returns:
        {
          "tx_signature": str,   # Firma de la TX en Solana (audit trail)
          "payload_hash": str,   # SHA-256 hex del JSON de la orden
          "explorer_url": str,   # URL Solana Explorer para verificar
          "memo":         str,   # Memo embebido en la TX
        }
    """
    return registrar_en_solana_safe(datos, fallback_on_error=True)


# ---------------------------------------------------------------------------
# Paso 3 — MongoDB
# ---------------------------------------------------------------------------

def guardar_en_mongo(datos: dict, solana_result: dict) -> str:
    """
    Guarda la orden en MongoDB. Colección separada del ERP de Arca
    para no interferir con su formato interno.

    El documento incluye:
      - Todos los datos de la orden (missing_products, valor, etc.)
      - tx_signature de Solana → permite auditar la orden on-chain
      - payload_hash → permite re-verificar integridad sin ir a Solana

    Returns: _id del documento insertado

    TODO Persona 3: conectar con pymongo
        from pymongo import MongoClient
        client = MongoClient(os.getenv("MONGO_URI"))
        doc = {**datos, "solana": solana_result}
        result = client["arcfast"]["ordenes"].insert_one(doc)
        return str(result.inserted_id)
    """
    documento = {
        **datos,
        "solana_tx_signature": solana_result["tx_signature"],
        "solana_hash":         solana_result["payload_hash"],
        "solana_explorer_url": solana_result.get("explorer_url"),
    }
    print(f"[MONGO] Documento a insertar:\n  {documento}")
    return "mock_mongo_id_abc123"


# ---------------------------------------------------------------------------
# Paso 4 — Email
# ---------------------------------------------------------------------------

def enviar_email(user_email: str, solana_result: dict, mongo_id: str):
    """
    Envía el reporte al email del usuario registrado.
    Adjunta el PDF y linkea al dashboard y al Solana Explorer.

    TODO Persona 3: SendGrid o smtplib
        import sendgrid
        from sendgrid.helpers.mail import Mail
        sg = sendgrid.SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
        msg = Mail(from_email="arcfast@arca.mx", to_emails=user_email, ...)
        sg.send(msg)
    """
    print(f"[EMAIL] Enviando reporte a {user_email}")
    print(f"  Solana TX:      {solana_result['tx_signature']}")
    print(f"  Hash orden:     {solana_result['payload_hash']}")
    if solana_result.get("explorer_url"):
        print(f"  Explorer:       {solana_result['explorer_url']}")
    print(f"  MongoDB ID:     {mongo_id}")
