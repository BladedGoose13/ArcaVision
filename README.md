# ArcFast ⚡
Agente IA que automatiza la captura de órdenes de compra entre portales de clientes y el sistema interno de Arca Continental. El agente observa al usuario realizar el proceso una sola vez, aprende el mapeo de campos sin reglas hardcodeadas, y lo ejecuta de forma autónoma con nuevos datos.

## Arquitectura

```
ArcFast/
├── backend/
│   └── api.py                  # FastAPI — conecta frontend HTML con el agente Python
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
├── arcfast.db                  # Base de datos SQLite (se genera automáticamente)
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

## Variables de entorno

```env
ANTHROPIC_API_KEY=sk-ant-...   # obligatoria — Claude Vision + análisis
GROQ_API_KEY=gsk_...           # opcional — Whisper para transcripción más rápida
```

## Modo de uso principal (FastAPI + UI corporativa)

```bash
# Exportar variables de entorno (PowerShell)
$env:ANTHROPIC_API_KEY="sk-ant-..."
$env:GROQ_API_KEY="gsk_..."

# Arrancar el servidor
uvicorn backend.api:app --reload --port 8000
```

Luego abrir `http://localhost:8000` en el browser.

## Modo alternativo (Streamlit)

```bash
streamlit run frontend/app.py
```

## Flujo completo

```
1. Grabación      → El usuario ejecuta el proceso en su browser y habla en voz alta
2. Análisis       → Claude Opus analiza keyframes + transcripción de audio (Fase A)
3. Preguntas      → La IA pregunta solo lo que no pudo inferir (máx. 3 preguntas)
4. Revisión       → El usuario edita mapeos con Bayesian confidence scores
5. Ejecución      → Browser agent navega el portal autónomamente con Playwright
6. Aprobación     → Human-in-the-loop antes de registrar en Arca
7. Reporte        → PDF + Dashboard Monte Carlo + Dashboard de errores
```

## Base de datos

SQLite embebida, schema compatible con SQL Server. Se crea automáticamente en `arcfast.db`.

| Tabla | Descripción |
|---|---|
| `planes` | Instrucciones aprendidas por portal (con versioning) |
| `mapeos` | Campos mapeados con confianza bayesiana actualizable |
| `sesiones` | Historial de cada ejecución del agente |
| `errores` | Fallos específicos por paso para análisis de ingeniería |

Para visualizar en VS Code: instalar extensión **SQLite Viewer** (Florian Klampfer).

Para migrar a SQL Server en producción: cambiar `get_connection()` en `database/db.py`:
```python
import pyodbc
return pyodbc.connect('DRIVER={SQL Server};SERVER=tu_servidor;DATABASE=arcfast;')
```

## Endpoints API

| Método | Endpoint | Descripción |
|---|---|---|
| `POST` | `/grabar/iniciar` | Inicia grabación de pantalla + audio |
| `POST` | `/grabar/pausar` | Pausa la grabación |
| `POST` | `/grabar/continuar` | Reanuda la grabación |
| `POST` | `/grabar/reiniciar` | Reinicia grabación desde cero |
| `POST` | `/grabar/terminar` | Detiene y analiza con Claude (Fase A) |
| `POST` | `/completar` | Inyecta respuestas del usuario al plan (Fase B) |
| `POST` | `/ejecutar` | Corre el browser agent en el portal |
| `GET`  | `/historial` | Últimas N sesiones de la base de datos |
| `GET`  | `/estadisticas` | Tasa de éxito global + top portales |
| `GET`  | `/plan/{url}` | Carga plan guardado para un portal |
| `GET`  | `/health` | Estado del servidor |

## Diferenciadores técnicos

**Bayesian confidence scoring** — cada campo mapeado lleva una probabilidad de confianza (0.0–1.0). Campos bajo el umbral (default 0.70) se marcan automáticamente para revisión humana. La confianza se actualiza incrementalmente con cada confirmación o corrección del usuario.

**Monte Carlo (diferenciador IFI)** — el reporte ejecutivo incluye una estimación probabilística del impacto económico de los productos faltantes sobre el valor de la orden, con intervalo de confianza al 95% calculado con N=5,000 simulaciones sobre el histórico de órdenes.

**Claude Vision fallback** — cuando el browser agent no reconoce un elemento de la UI, toma un screenshot y consulta Claude Vision para localizar el elemento antes de actuar. Sin selectores CSS hardcodeados.

## Lo que funciona hoy

- Grabador de pantalla con captura de clicks, teclas y screenshots por evento
- Transcripción de audio vía Groq Whisper (fallback a Claude)
- Análisis de sesión con Claude Opus Vision (keyframes + audio)
- Preguntas inteligentes de la IA al usuario antes de ejecutar
- Bayesian confidence scores en el mapeo de campos
- Browser agent con Playwright navegando sin selectores CSS
- UI corporativa Arca Continental (rojo #C8102E, Bebas Neue)
- Base de datos SQLite con historial de sesiones y aprendizaje incremental
- Dashboard Monte Carlo con IC 95% en el reporte ejecutivo
- Dashboard de errores por tipo de acción para ingenieros

## Regla de oro

Todos los módulos se comunican a través de `shared/schemas.py`.
Si cambias un schema, avisa al equipo. Las API keys van en `.env`, nunca en el código.
