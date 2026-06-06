# ArcFast ⚡
Agente IA que automatiza la captura de órdenes de compra entre portales de clientes y el sistema interno de Arca Continental.

## Estructura del repo

```
ArcFast/
├── shared/
│   └── schemas.py          # Contrato JSON entre módulos — leer primero
├── core/
│   └── workflow_generator.py   # PERSONA 1 — transcripción → workflow JSON
├── browser_agent/
│   └── agent.py            # PERSONA 2 — Playwright + Vision fallback
├── postprocessing/
│   └── pipeline.py         # PERSONA 3 — Gemini + Solana + MongoDB + email
├── frontend/
│   ├── app.py              # PERSONA 4 — Streamlit UI principal
│   └── monte_carlo.py      # PERSONA 4 — estimación de impacto económico
├── data/
│   └── mock/mock_data.json # Datos mock para desarrollo sin dependencias
├── .env.example
└── requirements.txt
```

## Setup

```bash
git clone https://github.com/tu-usuario/ArcFast.git
cd ArcFast
pip install -r requirements.txt
cp .env.example .env      # llena tus API keys
playwright install chromium
streamlit run frontend/app.py
```
## Diagrams

![Arca AI Agent Workflow](arca_ai_agent_workflow.png)

![Bayesian Confidence Scoring](diagrams/bayesian_confidence_scoring.png)


## División de trabajo (hackathon 24h)

| Persona | Módulo | Archivo principal |
|---|---|---|
| 1 (Max) | Orquestación + Bayesian confidence | `core/workflow_generator.py` |
| 2 | Browser agent | `browser_agent/agent.py` |
| 3 | Post-procesamiento | `postprocessing/pipeline.py` |
| 4 | Frontend + Monte Carlo | `frontend/app.py`, `frontend/monte_carlo.py` |

## Regla de oro

Todos los módulos se comunican **únicamente** a través de los schemas definidos en `shared/schemas.py`.
Si necesitas cambiar un schema, avisa al equipo antes.

## Modo mock

Activa el toggle "Usar datos mock" en el sidebar de Streamlit para desarrollar
sin necesidad de API keys ni conexión a portales externos.
