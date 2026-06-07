"""
core/workflow_generator.py — shim de compatibilidad
-----------------------------------------------------
Redirige al módulo unificado brain/workflow_generator.py.
"""
from brain.workflow_generator import (  # noqa: F401  re-export
    generar_workflow,
    workflow_desde_mock,
    UMBRAL_DEFAULT,
)
