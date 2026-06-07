"""
postprocessing/solana_audit.py  —  Audit Trail en Solana
---------------------------------------------------------
Registra el hash SHA-256 del registro de compra-venta en Solana Devnet
como prueba inmutable de la orden. El dato NO se guarda on-chain en claro
(por privacidad y costo); solo el hash va a la blockchain.

Flujo:
  1. Serializar los datos de la orden (dict) → JSON canónico
  2. SHA-256 del payload → local_hash (32 bytes)
  3. Construir memo instruction con el hash como string hex
  4. Firmar y enviar la transacción a Solana Devnet
  5. Retornar el signature de la transacción (TX signature)

Dependencias:
    pip install solders solana anchorpy-core

Variables de entorno necesarias:
    SOLANA_PRIVATE_KEY   Base58 o JSON array de la keypair del pagador
    SOLANA_RPC_URL       (opcional) default: https://api.devnet.solana.com
"""

import hashlib
import json
import os
import base64
from typing import Optional


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"  # Memo v2

# Prefijo para identificar registros ArcFast en el memo
ARCFAST_PREFIX = "ARCFAST:v1:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_orden(datos: dict) -> bytes:
    """
    Serialización canónica del registro de compra-venta.
    sort_keys=True garantiza que el mismo dict siempre produce el mismo hash,
    independientemente del orden de inserción.
    """
    return json.dumps(datos, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _sha256_hex(payload: bytes) -> str:
    """Retorna el SHA-256 del payload como string hexadecimal (64 chars)."""
    return hashlib.sha256(payload).hexdigest()


def _load_keypair():
    """
    Carga la keypair del pagador desde la variable de entorno SOLANA_PRIVATE_KEY.

    Formatos soportados:
      - Array JSON de 64 bytes:  "[12,34,56,...]"
      - Base58 string de 64 bytes (solana-keygen output)

    Returns:
        solders.keypair.Keypair
    """
    from solders.keypair import Keypair  # type: ignore

    raw = os.getenv("SOLANA_PRIVATE_KEY", "").strip()
    if not raw:
        raise EnvironmentError(
            "SOLANA_PRIVATE_KEY no está definida en el entorno. "
            "Agrega la keypair del pagador en formato JSON array o Base58."
        )

    # Intento 1: JSON array de bytes
    try:
        byte_list = json.loads(raw)
        if isinstance(byte_list, list):
            return Keypair.from_bytes(bytes(byte_list))
    except (json.JSONDecodeError, ValueError):
        pass

    # Intento 2: Base58
    try:
        import base58  # type: ignore
        decoded = base58.b58decode(raw)
        return Keypair.from_bytes(decoded)
    except Exception:
        pass

    raise ValueError(
        "SOLANA_PRIVATE_KEY tiene formato inválido. "
        "Usa JSON array de 64 bytes o string Base58."
    )


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def registrar_orden_en_solana(datos: dict) -> dict:
    """
    Registra el hash SHA-256 del registro de compra-venta en Solana Devnet.

    Args:
        datos: dict con los campos de la orden (output de extraer_con_gemini).
              Estructura esperada:
                {
                  "missing_products": [...],
                  "errores": [...],
                  "challenges": [...],
                  "url_portal": str,
                  "total_missing": int,
                  "valor_estimado": float,
                }

    Returns:
        {
          "tx_signature": str,    # Firma de la transacción Solana (audit trail)
          "payload_hash": str,    # SHA-256 hex del JSON de la orden
          "rpc_url": str,         # RPC usado
          "explorer_url": str,    # URL al explorador para verificar on-chain
          "memo": str,            # Memo embebido en la TX
        }

    Raises:
        EnvironmentError: Si falta SOLANA_PRIVATE_KEY
        RuntimeError:     Si la transacción falla
    """
    from solana.rpc.api import Client  # type: ignore
    from solana.transaction import Transaction  # type: ignore
    from solders.pubkey import Pubkey  # type: ignore
    from solders.instruction import Instruction, AccountMeta  # type: ignore

    # 1. Hash del payload
    payload_bytes = _serialize_orden(datos)
    payload_hash = _sha256_hex(payload_bytes)

    # 2. Memo string: prefijo + hash (≤566 bytes max del Memo program)
    memo_text = f"{ARCFAST_PREFIX}{payload_hash}"

    # 3. Cargar keypair del pagador
    payer = _load_keypair()

    # 4. Construir Memo instruction
    memo_pubkey = Pubkey.from_string(MEMO_PROGRAM_ID)
    memo_ix = Instruction(
        program_id=memo_pubkey,
        accounts=[
            AccountMeta(pubkey=payer.pubkey(), is_signer=True, is_writable=False)
        ],
        data=memo_text.encode("utf-8"),
    )

    # 5. Conectar al RPC y obtener blockhash reciente
    client = Client(SOLANA_RPC_URL)
    blockhash_resp = client.get_latest_blockhash()
    recent_blockhash = blockhash_resp.value.blockhash

    # 6. Construir y firmar la transacción
    txn = Transaction()
    txn.add(memo_ix)
    txn.recent_blockhash = recent_blockhash
    txn.fee_payer = payer.pubkey()
    txn.sign(payer)

    # 7. Enviar la transacción
    response = client.send_transaction(txn, payer)

    if response.value is None:
        raise RuntimeError(
            f"Solana rechazó la transacción: {response}"
        )

    tx_signature = str(response.value)
    explorer_url = f"https://explorer.solana.com/tx/{tx_signature}?cluster=devnet"

    return {
        "tx_signature": tx_signature,
        "payload_hash": payload_hash,
        "rpc_url": SOLANA_RPC_URL,
        "explorer_url": explorer_url,
        "memo": memo_text,
    }


# ---------------------------------------------------------------------------
# Fallback local (sin conexión a Solana)
# ---------------------------------------------------------------------------

def registrar_orden_local_fallback(datos: dict) -> dict:
    """
    Fallback cuando Solana no está disponible (tests, CI, demo offline).
    Genera el hash SHA-256 local sin enviarlo a la red.
    Retorna el mismo schema que registrar_orden_en_solana() para que
    el pipeline no rompa.
    """
    payload_bytes = _serialize_orden(datos)
    payload_hash = _sha256_hex(payload_bytes)
    memo_text = f"{ARCFAST_PREFIX}{payload_hash}"

    return {
        "tx_signature": f"LOCAL_FALLBACK_{payload_hash[:16]}",
        "payload_hash": payload_hash,
        "rpc_url": "local",
        "explorer_url": None,
        "memo": memo_text,
    }


# ---------------------------------------------------------------------------
# Función con retry automático + fallback
# ---------------------------------------------------------------------------

def registrar_en_solana_safe(datos: dict, fallback_on_error: bool = True) -> dict:
    """
    Wrapper con manejo de errores y fallback automático.
    Usar esta función desde pipeline.py en lugar de registrar_orden_en_solana()
    para entornos de desarrollo/demo donde Solana puede no estar disponible.

    Args:
        datos:             dict de la orden
        fallback_on_error: Si True, usa fallback local en caso de error de red

    Returns:
        dict con tx_signature, payload_hash, explorer_url, etc.
    """
    try:
        result = registrar_orden_en_solana(datos)
        print(f"[SOLANA] ✅ TX confirmada: {result['tx_signature']}")
        print(f"[SOLANA]    Hash:  {result['payload_hash']}")
        print(f"[SOLANA]    Explorer: {result['explorer_url']}")
        return result

    except EnvironmentError as e:
        print(f"[SOLANA] ⚠️  Config error: {e}")
        if fallback_on_error:
            print("[SOLANA]    Usando fallback local...")
            return registrar_orden_local_fallback(datos)
        raise

    except Exception as e:
        print(f"[SOLANA] ❌ Error al registrar en Solana: {e}")
        if fallback_on_error:
            print("[SOLANA]    Usando fallback local...")
            return registrar_orden_local_fallback(datos)
        raise


# ---------------------------------------------------------------------------
# CLI para testing rápido
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    datos_demo = {
        "missing_products": [
            {"sku_arca": "CC-2L-001", "nombre": "Coca-Cola 2L", "cantidad": 48, "precio_unitario": 28.50},
            {"sku_arca": "SP-600-003", "nombre": "Sprite 600ml", "cantidad": 24, "precio_unitario": 14.00},
        ],
        "errores": [],
        "challenges": [],
        "url_portal": "https://www.saucedemo.com",
        "total_missing": 2,
        "valor_estimado": 1704.0,
    }

    print("=== ArcFast — Solana Audit Trail Demo ===\n")
    resultado = registrar_en_solana_safe(datos_demo, fallback_on_error=True)

    print("\n--- Resultado ---")
    for k, v in resultado.items():
        print(f"  {k}: {v}")
