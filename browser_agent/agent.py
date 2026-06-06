"""
browser_agent/agent.py  —  PERSONA 2
--------------------------------------
Toma un WorkflowConfirmado, entra al portal del cliente,
extrae la base de datos y detecta missing products.

Dependencias: playwright, anthropic (Vision fallback)
"""

from shared.schemas import WorkflowConfirmado, MissingProduct, AgentResult


def ejecutar_en_portal(workflow: WorkflowConfirmado) -> AgentResult:
    """
    Entry point principal. Persona 1 llama esto después de la confirmación.

    Flujo interno:
    1. Playwright abre el navegador y navega a workflow.url_portal
    2. Sigue workflow.pasos para localizar la tabla de productos
    3. Usa workflow.mapeos para extraer cada campo
    4. Si no reconoce un elemento UI → fallback Vision (ver vision_fallback)
    5. Compara contra catálogo Arca → detecta missing_products
    6. Devuelve AgentResult con todo lo encontrado + errores
    """
    # TODO Persona 2: implementar con Playwright
    raise NotImplementedError("Implementar con Playwright")


def vision_fallback(screenshot_b64: str, descripcion_elemento: str) -> dict:
    """
    Cuando el agente no reconoce un elemento de la UI,
    manda el screenshot a Claude Vision y le pregunta dónde está el campo.

    Returns:
        { "x": int, "y": int, "descripcion": str }
    """
    import anthropic
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
                {
                    "type": "text",
                    "text": f"""En esta captura de pantalla de un portal web,
¿dónde está el elemento: '{descripcion_elemento}'?
Responde SOLO con JSON: {{"x": int, "y": int, "descripcion": "texto breve"}}"""
                },
            ],
        }],
    )

    import json
    return json.loads(response.content[0].text)


def resultado_mock() -> AgentResult:
    """
    Devuelve un AgentResult desde el mock para que Persona 1 y 4
    puedan integrar sin esperar la implementación real.
    """
    import json, os
    mock_path = os.path.join(os.path.dirname(__file__), "../data/mock/mock_data.json")
    with open(mock_path) as f:
        data = json.load(f)

    from core.workflow_generator import workflow_desde_mock
    workflow = workflow_desde_mock()

    missing = [
        MissingProduct(**p) for p in data["missing_products_mock"]
    ]

    return AgentResult(
        workflow=workflow,
        missing_products=missing,
        errores=[],
        challenges=["El portal tardó 4s en cargar la tabla de productos"],
    )
