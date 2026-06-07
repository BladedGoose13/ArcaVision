"""
postprocessing/solana_audit.py  —  Audit Trail en Solana (ArcaVision)
---------------------------------------------------------------------
Registra el hash SHA-256 del registro de compra-venta en Solana Devnet
como prueba inmutable de la orden. El dato NO se guarda on-chain en claro
(por privacidad y costo); solo el hash va a la blockchain.

Capa de INTEGRIDAD (complementa al cifrado de postprocessing/crypto.py):
  - crypto.py  → confidencialidad (nadie sin la llave lee el registro)
  - este módulo → integridad (nadie puede alterar el registro sin que se note)

Flujo:
  1. Serializar los datos de la orden (dict) → JSON canónico
  2. SHA-256 del payload → payload_hash (32 bytes)
  3. Construir memo instruction con el hash como string hex
  4. Firmar y enviar la transacción a Solana Devnet
  5. Retornar el signature de la transacción

Dependencias:
    pip install solders solana base58

Variables de entorno:
    SOLANA_PRIVATE_KEY   Base58 o JSON array de la keypair del pagador
    SOLANA_RPC_URL       (opcional) default: https://api.devnet.solana.com
"""

import hashlib
import json
import os

SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"  # Memo v2

# Prefijo para identificar registros ArcaVision en el memo on-chain
ARCAVISION_PREFIX = "ARCAVISION:v1:"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _serialize_orden(datos: dict) -> bytes:
    """
    Serialización canónica del registro de compra-venta.
    sort_keys=True garantiza que el mismo dict siempre produce el mismo hash.
    """
    return json.dumps(datos, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _sha256_hex(payload: bytes) -> str:
    """SHA-256 del payload como hex (64 chars)."""
    return hashlib.sha256(payload).hexdigest()


def _load_keypair():
    """Carga la keypair del pagador desde SOLANA_PRIVATE_KEY (JSON array o Base58)."""
    from solders.keypair import Keypair  # type: ignore

    raw = os.getenv("SOLANA_PRIVATE_KEY", "").strip()
    if not raw:
        raise EnvironmentError(
            "SOLANA_PRIVATE_KEY no está definida. Agrega la keypair del pagador "
            "en formato JSON array o Base58.")

    try:
        byte_list = json.loads(raw)
        if isinstance(byte_list, list):
            return Keypair.from_bytes(bytes(byte_list))
    except (json.JSONDecodeError, ValueError):
        pass

    try:
        import base58  # type: ignore
        return Keypair.from_bytes(base58.b58decode(raw))
    except Exception:
        pass

    raise ValueError("SOLANA_PRIVATE_KEY inválida (usa JSON array de 64 bytes o Base58).")


# ─── Función principal ────────────────────────────────────────────────────────

def registrar_orden_en_solana(datos: dict) -> dict:
    """
    Registra el hash SHA-256 del registro de compra-venta en Solana Devnet.
    Devuelve dict con tx_signature, payload_hash, rpc_url, explorer_url, memo.
    """
    from solana.rpc.api import Client  # type: ignore
    from solana.transaction import Transaction  # type: ignore
    from solders.pubkey import Pubkey  # type: ignore
    from solders.instruction import Instruction, AccountMeta  # type: ignore

    payload_bytes = _serialize_orden(datos)
    payload_hash = _sha256_hex(payload_bytes)
    memo_text = f"{ARCAVISION_PREFIX}{payload_hash}"

    payer = _load_keypair()

    memo_pubkey = Pubkey.from_string(MEMO_PROGRAM_ID)
    memo_ix = Instruction(
        program_id=memo_pubkey,
        accounts=[AccountMeta(pubkey=payer.pubkey(), is_signer=True, is_writable=False)],
        data=memo_text.encode("utf-8"),
    )

    client = Client(SOLANA_RPC_URL)
    recent_blockhash = client.get_latest_blockhash().value.blockhash

    txn = Transaction()
    txn.add(memo_ix)
    txn.recent_blockhash = recent_blockhash
    txn.fee_payer = payer.pubkey()
    txn.sign(payer)

    response = client.send_transaction(txn, payer)
    if response.value is None:
        raise RuntimeError(f"Solana rechazó la transacción: {response}")

    tx_signature = str(response.value)
    return {
        "tx_signature": tx_signature,
        "payload_hash": payload_hash,
        "rpc_url": SOLANA_RPC_URL,
        "explorer_url": f"https://explorer.solana.com/tx/{tx_signature}?cluster=devnet",
        "memo": memo_text,
    }


# ─── Fallback local (sin red) ─────────────────────────────────────────────────

def registrar_orden_local_fallback(datos: dict) -> dict:
    """
    Fallback offline: genera el hash SHA-256 sin enviarlo a la red.
    Mantiene el mismo schema para no romper el pipeline.
    """
    payload_hash = _sha256_hex(_serialize_orden(datos))
    return {
        "tx_signature": f"LOCAL_FALLBACK_{payload_hash[:16]}",
        "payload_hash": payload_hash,
        "rpc_url": "local",
        "explorer_url": None,
        "memo": f"{ARCAVISION_PREFIX}{payload_hash}",
    }


# ─── Wrapper con retry + fallback ─────────────────────────────────────────────

def registrar_en_solana_safe(datos: dict, fallback_on_error: bool = True) -> dict:
    """Wrapper resistente: usa fallback local si Solana no está disponible."""
    try:
        result = registrar_orden_en_solana(datos)
        print(f"  [SOLANA] ✅ TX confirmada: {result['tx_signature']}")
        print(f"  [SOLANA]    Hash: {result['payload_hash']}")
        print(f"  [SOLANA]    Explorer: {result['explorer_url']}")
        return result
    except EnvironmentError as e:
        print(f"  [SOLANA] ⚠️  Config: {e}")
        if fallback_on_error:
            print("  [SOLANA]    Usando fallback local…")
            return registrar_orden_local_fallback(datos)
        raise
    except Exception as e:
        print(f"  [SOLANA] ❌ Error: {e}")
        if fallback_on_error:
            print("  [SOLANA]    Usando fallback local…")
            return registrar_orden_local_fallback(datos)
        raise


if __name__ == "__main__":
    datos_demo = {
        "missing_products": [
            {"sku_arca": "CC-2L-001", "nombre": "Coca-Cola 2L", "cantidad": 48, "precio_unitario": 28.50},
        ],
        "valor_estimado": 1368.0,
    }
    print("=== ArcaVision — Solana Audit Trail Demo ===\n")
    for k, v in registrar_en_solana_safe(datos_demo).items():
        print(f"  {k}: {v}")
