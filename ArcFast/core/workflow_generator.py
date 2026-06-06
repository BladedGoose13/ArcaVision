"""
core/workflow_generator.py  —  PERSONA 1 (Max)
------------------------------------------------
Toma la transcripción de Whisper y produce un WorkflowConfirmado
con Bayesian confidence scores por campo.
"""

import json
import anthropic
from shared.schemas import FieldMapping, WorkflowConfirmado

client = anthropic.Anthropic()

UMBRAL_DEFAULT = 0.70   # Campos bajo este umbral se marcan como flag


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


def generar_workflow(transcripcion: str, url_portal: str, umbral: float = UMBRAL_DEFAULT) -> WorkflowConfirmado:
    """
    Llama a Claude con la transcripción y devuelve un WorkflowConfirmado.
    Los campos bajo el umbral se marcan como flag automáticamente.
    """
    prompt = PROMPT_TEMPLATE.format(
        transcripcion=transcripcion,
        url_portal=url_portal,
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = json.loads(response.content[0].text)

    mapeos = [
        FieldMapping(
            campo_origen=m["campo_origen"],
            campo_destino=m["campo_destino"],
            confianza=m["confianza"],
            flag=m["confianza"] < umbral,
        )
        for m in raw["mapeos"]
    ]

    return WorkflowConfirmado(
        url_portal=url_portal,
        pasos=raw["pasos"],
        mapeos=mapeos,
    )


def workflow_desde_mock() -> WorkflowConfirmado:
    """
    Devuelve un WorkflowConfirmado desde el mock — útil para desarrollo
    sin necesidad de llamar a la API ni tener la grabación lista.
    """
    import json, os
    mock_path = os.path.join(os.path.dirname(__file__), "../data/mock/mock_data.json")
    with open(mock_path) as f:
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
