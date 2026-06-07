"""
postprocessing/crypto.py  —  Cifrado de datos sensibles (ArcaVision)
--------------------------------------------------------------------
Provee cifrado simétrico autenticado (Fernet = AES-128-CBC + HMAC-SHA256)
para proteger **registros financieros** y **correos** en reposo.

¿Por qué Fernet y no solo un hash?
  - SHA-256 (solana_audit) da INTEGRIDAD (detecta manipulación) pero NO
    confidencialidad: el hash es irreversible, no oculta el dato si ya lo tienes.
  - Fernet da CONFIDENCIALIDAD: cifra el contenido y solo quien tiene la llave
    puede leerlo. Las dos capas son complementarias.

Gestión de llave (en orden de prioridad):
  1. Variable de entorno  ARCAVISION_ENC_KEY  (llave Fernet base64 url-safe, 44 chars)
  2. Archivo local        ~/.arcavision/enc.key  (se genera solo, NO se versiona)

Generar una llave para producción:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # pégala en .env como  ARCAVISION_ENC_KEY=...

Formato de los tokens: se antepone el marcador  "enc:v1:"  para poder
distinguir un valor cifrado de uno en claro (retro-compatibilidad con datos
viejos sin cifrar).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

_PREFIJO = "enc:v1:"
_KEY_FILE = Path(os.path.expanduser("~/.arcavision/enc.key"))

# Cache del objeto Fernet para no recargar la llave en cada llamada
_fernet = None
_intentado = False


# ─── Carga / generación de llave ──────────────────────────────────────────────

def _resolver_llave() -> Optional[bytes]:
    """Obtiene la llave Fernet de la env var o del archivo local; genera una si falta."""
    env = os.getenv("ARCAVISION_ENC_KEY", "").strip()
    if env:
        return env.encode()

    if _KEY_FILE.exists():
        contenido = _KEY_FILE.read_text(encoding="utf-8").strip()
        if contenido:
            return contenido.encode()

    # Generar una llave nueva y persistirla con permisos restrictivos
    try:
        from cryptography.fernet import Fernet
        nueva = Fernet.generate_key()
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(nueva.decode(), encoding="utf-8")
        try:
            os.chmod(_KEY_FILE, 0o600)
        except OSError:
            pass
        print(f"  🔐 Llave de cifrado generada en {_KEY_FILE} "
              f"(respáldala; sin ella no podrás descifrar los registros)")
        return nueva
    except Exception as e:
        print(f"  ⚠️  No se pudo generar llave de cifrado: {e}")
        return None


def _get_fernet():
    """Devuelve un objeto Fernet inicializado, o None si el cifrado no está disponible."""
    global _fernet, _intentado
    if _fernet is not None:
        return _fernet
    if _intentado:
        return None
    _intentado = True
    try:
        from cryptography.fernet import Fernet
        llave = _resolver_llave()
        if not llave:
            return None
        _fernet = Fernet(llave)
        return _fernet
    except ImportError:
        print("  ⚠️  Paquete 'cryptography' no instalado — los datos NO se cifrarán. "
              "Instala con: pip install cryptography")
        return None
    except Exception as e:
        print(f"  ⚠️  Cifrado no disponible ({e}) — los datos NO se cifrarán")
        return None


def cifrado_disponible() -> bool:
    """True si hay una llave válida y el paquete cryptography está instalado."""
    return _get_fernet() is not None


def esta_cifrado(valor: Any) -> bool:
    """Indica si un valor es un token cifrado por este módulo."""
    return isinstance(valor, str) and valor.startswith(_PREFIJO)


# ─── API pública ──────────────────────────────────────────────────────────────

def cifrar_texto(texto: str) -> str:
    """
    Cifra una cadena. Devuelve un token  'enc:v1:<base64>'.
    Si el cifrado no está disponible devuelve el texto en claro (degradación
    elegante para entornos de demo sin llave).
    """
    if texto is None:
        return texto
    f = _get_fernet()
    if f is None:
        return texto
    token = f.encrypt(texto.encode("utf-8")).decode("ascii")
    return _PREFIJO + token


def descifrar_texto(valor: str) -> str:
    """
    Descifra un token producido por cifrar_texto().
    Si el valor no está cifrado (datos legados), lo devuelve tal cual.
    """
    if not esta_cifrado(valor):
        return valor
    f = _get_fernet()
    if f is None:
        raise RuntimeError(
            "Hay datos cifrados pero no se pudo cargar la llave de descifrado. "
            "Define ARCAVISION_ENC_KEY o restaura ~/.arcavision/enc.key")
    token = valor[len(_PREFIJO):].encode("ascii")
    return f.decrypt(token).decode("utf-8")


def cifrar_json(obj: Any) -> str:
    """Serializa a JSON y cifra. Útil para guardar dicts/listas financieras."""
    return cifrar_texto(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def descifrar_json(valor: str) -> Any:
    """Inverso de cifrar_json(). Acepta también JSON en claro (datos legados)."""
    texto = descifrar_texto(valor)
    return json.loads(texto)


def cifrar_bytes(datos: bytes) -> bytes:
    """Cifra bytes crudos (p.ej. el Excel adjunto al correo)."""
    f = _get_fernet()
    if f is None:
        return datos
    return f.encrypt(datos)


def descifrar_bytes(datos: bytes) -> bytes:
    """Descifra bytes producidos por cifrar_bytes()."""
    f = _get_fernet()
    if f is None:
        raise RuntimeError("Cifrado no disponible para descifrar bytes")
    return f.decrypt(datos)


# ─── Verificación / diagnóstico ───────────────────────────────────────────────

def verificar_db(db_path: Optional[str] = None) -> None:
    """
    Inspecciona la tabla `pedidos` en SQLite y reporta cuántos registros
    financieros están cifrados en reposo. Lee el blob CRUDO (sin descifrar)
    directamente de la columna para mostrar la verdad de lo que hay en disco.
    """
    import sqlite3
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), "..", "arcavision.db")

    print(f"\n🔎 Inspeccionando {os.path.abspath(db_path)}")
    if not os.path.exists(db_path):
        print("   (la base de datos aún no existe — no hay pedidos guardados)")
        return

    conn = sqlite3.connect(db_path)
    existe = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pedidos'").fetchone()
    if not existe:
        conn.close()
        print("   (la tabla 'pedidos' aún no existe — arranca la app o registra un pedido)")
        return
    rows = conn.execute(
        "SELECT id, productos_json FROM pedidos ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()

    if not rows:
        print("   (no hay pedidos registrados todavía)")
        return

    cif = sum(1 for _, blob in rows if esta_cifrado(blob))
    print(f"   {cif}/{len(rows)} registros financieros recientes están CIFRADOS en disco\n")
    for pid, blob in rows:
        estado = "🔐 CIFRADO " if esta_cifrado(blob) else "⚠️  EN CLARO"
        print(f"   pedido #{pid}: {estado} → {str(blob)[:46]}…")


# ─── CLI de prueba ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "verificar":
        print("=== ArcaVision — Verificación de cifrado ===")
        print("Cifrado disponible (llave cargada):", cifrado_disponible())
        verificar_db()
    else:
        print("=== ArcaVision — Cifrado de datos sensibles ===\n")
        print("Cifrado disponible:", cifrado_disponible())
        pedido = {"cliente": "Walmart", "total": 1704.0,
                  "productos": [{"sku": "CC-2L", "precio": 28.5, "cant": 48}]}
        tok = cifrar_json(pedido)
        print("\nRegistro cifrado:\n ", tok)
        print("\nDescifrado:\n ", descifrar_json(tok))
        print("\n💡 Para verificar la base de datos real corre:")
        print("   python -m postprocessing.crypto verificar")
