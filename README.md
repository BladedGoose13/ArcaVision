# ArcaVision ⚡
> Agente IA que automatiza la captura de órdenes de compra entre portales de clientes y el sistema interno de Arca Continental.

El agente observa al usuario realizar el proceso **una sola vez**, aprende el mapeo de campos sin reglas hardcodeadas, y lo ejecuta de forma autónoma con nuevos datos — abriendo el navegador, navegando el portal y cerrándolo solo al terminar.

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
│   ├── agent.py                # Browser agent (browser_use + Claude) con auto-cierre
│   └── grabador.py             # Grabador de pantalla + audio (mouse, teclado, screenshots)
├── core/
│   ├── procesar.py             # Cerebro: Fase A (análisis) + Fase B (completar plan)
│   └── workflow_generator.py   # Transcripción → workflow JSON + Bayesian confidence
├── database/
│   └── db.py                   # SQLite (compatible SQL Server) — sesiones + planes + pedidos
├── frontend/
│   ├── app.py                  # Streamlit UI (modo alternativo)
│   └── monte_carlo.py          # Simulación Monte Carlo — impacto económico IC 95%
├── frontend_web/
│   └── index.html              # UI corporativa Arca Continental (HTML/JS → FastAPI)
├── postprocessing/
│   ├── reporte.py              # Reportes Excel/PDF + sistema de tickets por email + Sheets
│   └── pipeline.py             # Pipeline de post-procesamiento auxiliar
├── shared/
│   └── schemas.py              # Contrato JSON entre módulos — leer primero
├── data/
│   └── mock/
│       ├── mock_data.json      # Datos sintéticos para desarrollo
│       └── plan_ejemplo.json   # Plan real generado por el agente
├── reportes/                   # Salidas: compras.xlsx, errores.xlsx, reporte_ia.pdf, ticket.html
├── arcavision.db               # Base de datos (se genera automáticamente)
├── .env.example
└── requirements.txt
```

---

## Setup

```bash
git clone https://github.com/BladedGoose13/ArcaVision.git
cd ArcaVision
pip install -r requirements.txt
cp .env.example .env
```

Llena las variables en `.env` según `.env.example`. El agente usa **browser_use**, que
descarga su propio navegador la primera vez que corre — no necesitas instalar Playwright.

---

## Uso

### UI corporativa (FastAPI + HTML)

```bash
uvicorn backend.api:app --reload --port 8000
```

Abre `http://localhost:8000` en el browser. Todo el flujo (captura, preguntas,
revisión, ejecución y reportes) ocurre en la interfaz HTML — nada en la terminal.

### Modo alternativo (Streamlit)

```bash
streamlit run frontend/app.py
```

---

## Flujo

```
1. Grabación    →  El usuario ejecuta el proceso y habla en voz alta
2. Análisis     →  Claude Opus analiza keyframes + audio (Fase A)
3. Preguntas    →  La IA pregunta solo lo que no pudo inferir (en el frontend)
4. Revisión     →  El usuario edita mapeos con Bayesian confidence scores
5. Ejecución    →  Browser agent navega el portal con browser_use (DOM, sin vision)
6. Auto-cierre  →  El navegador se cierra solo al completar la tarea
7. Reporte      →  Excel de compras + PDF reporte IA + Excel de errores + ticket por email
```

---

## El cerebro

- **Fase A** (`analizar_sesion`): Claude Opus Vision interpreta keyframes + audio y
  genera el plan con mapeo de campos origen → destino, sin selectores CSS.
- **Fase B** (`completar_plan`): integra las respuestas del usuario y filtra los pasos
  finales que son artefactos del grabador (volver a la app para detener la grabación).
- **Parseo robusto**: extractor de JSON balanceado por llaves que tolera texto,
  code fences y JSON anidado en las respuestas del modelo.
- **Ejecución decidida**: el agente usa `use_vision=False` (navegación por DOM en vez
  de coordenadas), `max_failures=2` y un timeout externo para tomar decisiones rápido
  y evitar loops de scroll.

---

## Reportes y tickets

Al terminar la ejecución se generan automáticamente:

| Archivo | Contenido |
|---|---|
| `reportes/compras_arcavision.xlsx` | Registro de compras con gráficas |
| `reportes/reporte_ia_arcavision.pdf` | Reporte ejecutivo del desempeño de la IA |
| `reportes/errores_arcavision.xlsx` | Análisis de fallos por paso |
| `reportes/ticket.html` | Ticket de pedido con branding Arca |

El ticket se envía por email (SMTP Gmail) y, opcionalmente, el pedido se registra en
Google Sheets si configuras `GOOGLE_CREDENTIALS_PATH` y `GOOGLE_SHEET_ID` en `.env`.

---

## Base de datos

SQLite embebida con schema compatible con SQL Server. Se genera automáticamente en `arcavision.db` al primer arranque.

| Tabla | Descripción |
|---|---|
| `planes` | Instrucciones aprendidas por portal |
| `mapeos` | Campos con confianza bayesiana actualizable |
| `sesiones` | Historial completo de ejecuciones |
| `pedidos` | Órdenes capturadas (productos, totales, estado del ticket) |
| `errores` | Fallos por paso para análisis de ingeniería |

Para visualizar en VS Code: instalar extensión **SQLite Viewer** (Florian Klampfer).

Para migrar a SQL Server: cambiar `get_connection()` en `database/db.py`.

---

## División de trabajo

| Persona | Módulo | Archivos |
|---|---|---|
| 1 (Max) | Orquestación + Bayesian confidence | `core/workflow_generator.py` |
| 2 | Browser agent | `browser_agent/agent.py` + `grabador.py` |
| 3 | Post-procesamiento + tickets | `postprocessing/reporte.py` + `pipeline.py` |
| 4 | Frontend + Monte Carlo | `frontend_web/index.html` + `frontend/monte_carlo.py` |

---

## Lo que funciona

- Grabador de pantalla con captura de clicks, teclas y screenshots por evento
- Transcripción de audio vía Groq Whisper con fallback a Claude
- Análisis de sesión con Claude Opus Vision (keyframes + audio)
- Preguntas inteligentes de la IA al usuario, mostradas en el frontend HTML
- Filtro automático de pasos-artefacto del grabador antes de ejecutar
- Bayesian confidence scores en el mapeo de campos
- Browser agent con browser_use navegando por DOM, sin selectores CSS hardcodeados
- Auto-cierre del navegador al completar la tarea
- Decisiones rápidas del agente con límites de fallos y timeout para evitar loops
- UI corporativa Arca Continental con sidebar (Workflow / Historial / Perfil)
- Base de datos con historial de sesiones, pedidos y aprendizaje incremental
- Generación automática de Excel de compras, PDF reporte IA y Excel de errores
- Sistema de tickets por email + registro opcional en Google Sheets
- Dashboard Monte Carlo con IC 95%
- Dashboard de errores por tipo de acción

---
