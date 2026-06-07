"""
brain/workflow_generator.py
----------------------------
Genera un WorkflowConfirmado con Bayesian confidence scores
a partir de la transcripción del usuario.

Fixes:
  - Nombre de modelo corregido (era claude-sonnet-4-20250514, inválido)
  - Usa AsyncAnthropic y _llamar_json_con_retry del mismo módulo
  - Sin api_key explícita (antipatrón)
"""

from __future__ import annotations

import json
import os

from anthropic import AsyncAnthropic
from shared.schemas import FieldMapping, WorkflowConfirmado
from brain.procesar import _llamar_json_con_retry

UMBRAL_DEFAULT = 0.70

PROMPT_TEMPLATE = """
Eres un asistente que analiza la descripción verbal de un proceso
entre dos sistemas web y extrae el mapeo de campos entre ellos.

Transcripción del usuario:
{transcripcion}

URL del portal del cliente: {url_portal}

Devuelve ÚNICAMENTE un JSON con esta estructura exacta,
sin texto adicional, sin backticks, sin explicaciones:
{{
  "pasos": ["paso 1", "paso 2", "..."],
  "mapeos": [
    {{
      "campo_origen": "nombre exacto del campo en el portal del cliente",
      "campo_destino": "nombre del campo correspondiente en sistema Arca",
      "confianza": 0.00
    }}
  ]
}}

Reglas para calcular confianza:
- 0.90+ : el usuario lo mencionó explícitamente y el mapeo es inequívoco
- 0.70-0.89 : se infiere con seguridad razonable desde el contexto
- 0.50-0.69 : hay ambigüedad — el campo podría ser otra cosa
- < 0.50   : el usuario no dejó claro a qué corresponde en Arca
"""


async def generar_workflow(
    transcripcion: str,
    url_portal: str,
    umbral: float = UMBRAL_DEFAULT,
) -> WorkflowConfirmado:
    """
    Llama a Claude con la transcripción y devuelve un WorkflowConfirmado.
    Los campos bajo el umbral se marcan como flag automáticamente.
    """
    prompt = PROMPT_TEMPLATE.format(
        transcripcion=transcripcion,
        url_portal=url_portal,
    )

    raw = await _llamar_json_con_retry(
        messages=[{"role": "user", "content": prompt}],
        model="claude-opus-4-5",
        max_tokens=2000,
        etiqueta="generar_workflow",
    )

    mapeos = [
        FieldMapping(
            campo_origen=m["campo_origen"],
            campo_destino=m["campo_destino"],
            confianza=m["confianza"],
            flag=m["confianza"] < umbral,
        )
        for m in raw.get("mapeos", [])
    ]

    return WorkflowConfirmado(
        url_portal=url_portal,
        pasos=raw.get("pasos", []),
        mapeos=mapeos,
    )


def workflow_desde_mock() -> WorkflowConfirmado:
    """
    Devuelve un WorkflowConfirmado desde el mock — útil para desarrollo.
    """
    import os
    mock_path = os.path.join(os.path.dirname(__file__), "../data/mock/mock_data.json")
    with open(mock_path, encoding="utf-8") as f:
        data = json.load(f)

    m = data["workflow_mock"]
    mapeos = [
        FieldMapping(
            campo_origen=x["campo_origen"],
            campo_destino=x["campo_destino"],
            confianza=x["confianza"],
            flag=x["flag"],
        )
        for x in m["mapeos"]
    ]
    return WorkflowConfirmado(
        url_portal=m["url_portal"],
        pasos=m["pasos"],
        mapeos=mapeos,
    )
