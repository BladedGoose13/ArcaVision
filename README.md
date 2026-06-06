# ArcFast ⚡
Agente IA que automatiza la captura de órdenes de compra entre portales de clientes y el sistema interno de Arca Continental.

## Estructura del repo

```
ArcFast/
├── shared/
│   └── schemas.py              # Contrato JSON entre módulos — leer primero
├── core/
│   ├── workflow_generator.py   # PERSONA 1 — transcripción → workflow JSON + Bayesian confidence
│   └── procesar.py             # Procesamiento de sesión grabada (Claude Vision + audio)
├── browser_agent/
│   ├── agent.py                # Browser agent Playwright + Claude Vision fallback
│   └── grabador.py             # Grabador de pantalla + audio (mouse, teclado, screenshots)
├── postprocessing/
│   └── pipeline.py             # Gemini + Solana audit trail + MongoDB + email
├── frontend/
│   ├── app.py                  # Streamlit UI principal (5 etapas)
│   └── monte_carlo.py          # Monte Carlo impacto económico (diferenciador IFI)
├── data/
│   └── mock/
│       ├── mock_data.json      # Datos sintéticos para desarrollo
│       └── plan_ejemplo.json   # Plan real generado por el agente
├── .env.example
└── requirements.txt
```

## Setup rápido

```bash
git clone https://github.com/BladedGoose13/ArcFast.git
cd ArcFast
pip install -r requirements.txt
playwright install chromium
cp .env.example .env       # llenar API keys
```

## Modos de uso

### Modo CLI (prototipo base — funciona hoy)
```bash
python -m core.procesar   # grabar y procesar workflow
# o directamente desde main del proyecto hack4her:
python hack4her/main.py
```

### Modo Streamlit (UI completa)
```bash
streamlit run frontend/app.py
```
## Diagrams

![Arca AI Agent Workflow](diagrams/arca_ai_agent_workflow.png)

![Bayesian Confidence Scoring](diagrams/bayesian_confidence_scoring.png)


## División de trabajo (hackathon 24h)

| Persona | Módulo | Archivo | Estado |
|---|---|---|---|
| 1 (Max) | Orquestación + Bayesian confidence | `core/workflow_generator.py` | Listo |
| 2 | Browser agent | `browser_agent/agent.py` + `grabador.py` | **FUNCIONAL** |
| 3 | Post-procesamiento | `postprocessing/pipeline.py` | Esqueleto (TODO) |
| 4 | Frontend + Monte Carlo | `frontend/app.py` + `monte_carlo.py` | Esqueleto (TODO) |

## Lo que ya funciona (browser_agent)

- Grabador de pantalla con captura de clicks, teclas y screenshots por evento
- Transcripción de audio vía Claude
- Procesamiento de sesión con Claude Vision (keyframes + audio)
- Browser agent con Playwright que navega sin selectores CSS
- Fallback de Claude Haiku para localizar elementos por visión cuando falla el HTML
- Envío de reporte por email

## Regla de oro

Todos los módulos se comunican a través de `shared/schemas.py`.
Si cambias un schema, avisa al equipo. La `ANTHROPIC_API_KEY` va en `.env`, nunca en el código.
