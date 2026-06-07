"""
core/procesar.py — shim de compatibilidad
------------------------------------------
Redirige al módulo unificado brain/procesar.py.
Mantener este archivo evita romper imports externos que no se hayan migrado.
"""
from brain.procesar import (          # noqa: F401  re-export
    analizar_sesion,
    completar_plan,
    procesar_sesion_cli as procesar_sesion,
    transcribir_audio,
    SESIONES_DIR,
)
