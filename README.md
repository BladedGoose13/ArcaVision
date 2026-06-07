# ArcaVision ⚡
> Agente IA que automatiza la captura de órdenes de compra entre portales de clientes y el sistema interno de Arca Continental.

El agente observa al usuario realizar el proceso **una sola vez**, aprende el mapeo de campos sin reglas hardcodeadas, y lo ejecuta de forma autónoma con nuevos datos.

---

## Diagrams

![Arca AI Agent Workflow](diagrams/arca_ai_agent_workflow.png)
![Bayesian Confidence Scoring](diagrams/bayesian_confidence_scoring.png)

---

## Estructura del repo

```
ArcaVision/
├── backend/
│   └── api.py                  # FastAPI — conecta frontend HTML con el agente
├── browser_agent/
│   ├── agent.py                # Browser agent Playwright + Claude Vision fallback
│   └── grabador.py             # Grabador de pantalla + audio (mouse, teclado, screenshots)
├── core/
│   ├── procesar.py             # Cerebro: Fase A (análisis) + Fase B (completar plan)
│   └── workflow_generator.py   # Transcripción → workflow JSON + Bayesian confidence
├── database/
│   └── db.py                   # SQLite (compatible SQL Server) — historial + planes + mapeos
├── frontend/
│   ├── app.py                  # Streamlit UI (modo alternativo)
│   └── monte_carlo.py          # Simulación Monte Carlo — impacto económico IC 95%
├── frontend_web/
│   └── index.html              # UI corporativa Arca Continental (HTML/JS → FastAPI)
├── postprocessing/
│   └── pipeline.py             # Gemini + Solana audit trail + MongoDB + email
├── shared/
│   └── schemas.py              # Contrato JSON entre módulos — leer primero
├── data/
│   └── mock/
│       ├── mock_data.json      # Datos sintéticos para desarrollo
│       └── plan_ejemplo.json   # Plan real generado por el agente
├── arcavision.db                  # Base de datos (se genera automáticamente)
├── .env.example
└── requirements.txt
```

---

## Setup

```bash
git clone https://github.com/BladedGoose13/ArcaVision.git
cd ArcaVision
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Llena las variables en `.env` según `.env.example`.

---

## Uso

### UI corporativa (FastAPI + HTML)

```bash
uvicorn backend.api:app --reload --port 8000
```

Abre `http://localhost:8000` en el browser.

### Modo alternativo (Streamlit)

```bash
streamlit run frontend/app.py
```

---

## Flujo

```
1. Grabación    →  El usuario ejecuta el proceso y habla en voz alta
2. Análisis     →  Claude Opus analiza keyframes + audio (Fase A)
3. Preguntas    →  La IA pregunta solo lo que no pudo inferir
4. Revisión     →  El usuario edita mapeos con Bayesian confidence scores
5. Ejecución    →  Browser agent navega el portal con Playwright
6. Aprobación   →  Human-in-the-loop antes de registrar en Arca
7. Reporte      →  Dashboard Monte Carlo + Dashboard de errores
```

---

## Base de datos

SQLite embebida con schema compatible con SQL Server. Se genera automáticamente en `arcavision.db` al primer arranque.

| Tabla | Descripción |
|---|---|
| `planes` | Instrucciones aprendidas por portal |
| `mapeos` | Campos con confianza bayesiana actualizable |
| `sesiones` | Historial completo de ejecuciones |
| `errores` | Fallos por paso para análisis de ingeniería |

Para visualizar en VS Code: instalar extensión **SQLite Viewer** (Florian Klampfer).

Para migrar a SQL Server: cambiar `get_connection()` en `database/db.py`.

---

## División de trabajo

| Persona | Módulo | Archivos |
|---|---|---|
| 1 (Max) | Orquestación + Bayesian confidence | `core/workflow_generator.py` |
| 2 | Browser agent | `browser_agent/agent.py` + `grabador.py` |
| 3 | Post-procesamiento | `postprocessing/pipeline.py` |
| 4 | Frontend + Monte Carlo | `frontend_web/index.html` + `frontend/monte_carlo.py` |

---

## Lo que funciona

- Grabador de pantalla con captura de clicks, teclas y screenshots por evento
- Transcripción de audio vía Groq Whisper con fallback a Claude
- Análisis de sesión con Claude Opus Vision (keyframes + audio)
- Preguntas inteligentes de la IA al usuario antes de ejecutar
- Bayesian confidence scores en el mapeo de campos
- Browser agent con Playwright navegando sin selectores CSS hardcodeados
- Claude Vision fallback cuando el agente no reconoce un elemento de la UI
- UI corporativa Arca Continental
- Base de datos con historial de sesiones y aprendizaje incremental
- Dashboard Monte Carlo con IC 95%
- Dashboard de errores por tipo de acción

---

## Regla de oro

Todos los módulos se comunican a través de `shared/schemas.py`.  
Si cambias un schema, avisa al equipo. Las API keys van en `.env`, nunca en el código.
