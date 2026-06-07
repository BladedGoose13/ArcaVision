"""
backend/api.py
--------------
FastAPI que conecta el frontend HTML con el agente Python.
Corre con: uvicorn backend.api:app --reload --port 8000

Fixes respecto al original:
  - Endpoints críticos son async def (elimina asyncio.run() que podía deadlockear)
  - Estado de sesión aislado por session_id (no un dict global mutable)
  - Credenciales no se guardan en la DB (solo en memoria durante ejecución)
  - Endpoints de grabación/ejecución requieren autenticación básica
  - /grabar/terminar usa analizar_sesion del brain unificado
  - completar_plan devuelve un dict limpio (no tupla)
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from database.db import (
    guardar_plan, guardar_sesion, cargar_plan_activo,
    obtener_historial, obtener_estadisticas, login,
)

app = FastAPI(title="ArcFast API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend_web")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# ─── Estado de sesión por session_id ─────────────────────────────────────────
# Cada petición de grabación genera un session_id único.
# Elimina la colisión entre usuarios concurrentes.

_sessions: dict[str, dict] = {}

def _nueva_sesion() -> tuple[str, dict]:
    sid = str(uuid.uuid4())
    _sessions[sid] = {
        "grabador":   None,
        "sesion":     None,
        "fase_a":     None,
        "plan":       None,
        "plan_id":    None,
        "url_portal": "",
        "email":      "",
        "user_id":    None,
        "t_inicio":   None,
    }
    return sid, _sessions[sid]

def _get_sesion(session_id: str) -> dict:
    s = _sessions.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Sesión '{session_id}' no encontrada")
    return s


# ─── Auth simple via token de sesión ─────────────────────────────────────────
# El login devuelve un "token" = user_id serializado.
# Los endpoints protegidos leen el user_id desde el header Authorization.

security = HTTPBearer(auto_error=False)

def _usuario_opcional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    if not creds:
        return None
    # Token = "user_id:email" en base64 simplificado
    import base64
    try:
        decoded = base64.b64decode(creds.credentials).decode()
        uid_str, email = decoded.split(":", 1)
        return {"id": int(uid_str), "email": email}
    except Exception:
        return None

def _usuario_requerido(
    user: Optional[dict] = Depends(_usuario_opcional),
) -> dict:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
        )
    return user


# ─── Modelos Pydantic ─────────────────────────────────────────────────────────

class LoginReq(BaseModel):
    email: str
    password: str
    rol: Optional[str] = None

class RegisterReq(BaseModel):
    email: str
    password: str
    rol: str
    empresa: str

class IniciarGrabacionReq(BaseModel):
    url_portal: str
    email: Optional[str] = ""

class CompletarReq(BaseModel):
    session_id: str
    respuestas: dict

class EjecutarReq(BaseModel):
    session_id: str
    plan: dict
    credenciales: dict
    email: Optional[str] = ""


# ─── Frontend ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(os.path.join(frontend_path, "index.html"))


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/auth/login")
def auth_login(req: LoginReq):
    import base64
    user = login(req.email, req.password)
    if not user:
        return {"error": "Email o contraseña incorrectos"}
    if req.rol and user["rol"] != req.rol:
        return {"error": f"Esta cuenta no tiene acceso al portal de {req.rol}"}
    token = base64.b64encode(f"{user['id']}:{user['email']}".encode()).decode()
    return {
        "id":      user["id"],
        "email":   user["email"],
        "rol":     user["rol"],
        "empresa": user["empresa"],
        "token":   token,
    }

@app.post("/auth/register")
def auth_register(req: RegisterReq):
    from database.db import registrar_usuario
    try:
        user = registrar_usuario(req.email, req.password, req.rol, req.empresa)
        return user
    except ValueError as e:
        return {"error": str(e)}


# ─── Grabación ────────────────────────────────────────────────────────────────

@app.post("/grabar/iniciar")
def grabar_iniciar(
    req: IniciarGrabacionReq,
    user: dict = Depends(_usuario_requerido),
):
    from browser_agent.grabador import Grabador
    sid, s = _nueva_sesion()
    g = Grabador()
    g.iniciar()
    s["grabador"]   = g
    s["url_portal"] = req.url_portal
    s["email"]      = req.email or user["email"]
    s["user_id"]    = user["id"]
    return {"ok": True, "session_id": sid}


@app.post("/grabar/pausar")
def grabar_pausar(session_id: str, user: dict = Depends(_usuario_requerido)):
    s = _get_sesion(session_id)
    g = s.get("grabador")
    if not g:
        return {"ok": False, "error": "No hay grabación activa"}
    try:
        g.mouse_listener.stop()
        g.keyboard_listener.stop()
    except Exception:
        pass
    return {"ok": True}


@app.post("/grabar/continuar")
def grabar_continuar(session_id: str, user: dict = Depends(_usuario_requerido)):
    s = _get_sesion(session_id)
    g = s.get("grabador")
    if not g:
        return {"ok": False, "error": "No hay grabación activa"}
    from pynput import mouse, keyboard
    g.mouse_listener = mouse.Listener(on_click=g.on_click)
    g.keyboard_listener = keyboard.Listener(on_press=g.on_key)
    g.mouse_listener.start()
    g.keyboard_listener.start()
    return {"ok": True}


@app.post("/grabar/reiniciar")
def grabar_reiniciar(
    req: IniciarGrabacionReq,
    session_id: str,
    user: dict = Depends(_usuario_requerido),
):
    from browser_agent.grabador import Grabador
    s = _get_sesion(session_id)
    if s["grabador"]:
        try:
            s["grabador"].detener()
        except Exception:
            pass
    g = Grabador()
    g.iniciar()
    s["grabador"]   = g
    s["url_portal"] = req.url_portal
    s["email"]      = req.email or user["email"]
    return {"ok": True}


@app.post("/grabar/terminar")
async def grabar_terminar(
    session_id: str,
    user: dict = Depends(_usuario_requerido),
):
    s = _get_sesion(session_id)
    g = s.get("grabador")
    if not g:
        return {"error": "No hay grabación activa"}

    try:
        sesion_data = g.detener()
        s["sesion"]   = sesion_data
        s["grabador"] = None
    except Exception as e:
        return {"error": f"Error deteniendo grabación: {e}"}

    if not sesion_data.get("eventos"):
        return {"error": "No se grabaron eventos. Intenta de nuevo."}

    try:
        from brain.procesar import analizar_sesion
        resultado = await analizar_sesion(
            sesion_data["eventos"],
            sesion_data["audio_path"],
        )
        resultado["plan"]["url_portal"] = s["url_portal"]
        s["fase_a"] = resultado
        return resultado
    except Exception as e:
        return {"error": f"Error analizando sesión: {e}"}


# ─── Completar plan ───────────────────────────────────────────────────────────

@app.post("/completar")
def completar(req: CompletarReq, user: dict = Depends(_usuario_requerido)):
    s = _get_sesion(req.session_id)
    fase_a = s.get("fase_a")
    if not fase_a:
        return {"error": "No hay sesión analizada para esta sesión"}
    try:
        from brain.procesar import completar_plan
        plan = completar_plan(fase_a, req.respuestas)
        # Guardar plan SIN credenciales en la DB
        plan_sin_creds = {k: v for k, v in plan.items() if k != "credenciales_obtenidas"}
        plan_id = guardar_plan(plan_sin_creds, usuario_id=user["id"])
        s["plan"]     = plan
        s["plan_id"]  = plan_id
        s["t_inicio"] = time.time()
        return plan_sin_creds          # No devolver credenciales al frontend
    except Exception as e:
        return {"error": f"Error completando plan: {e}"}


# ─── Ejecutar agente ──────────────────────────────────────────────────────────

@app.post("/ejecutar")
async def ejecutar_agente(
    req: EjecutarReq,
    user: dict = Depends(_usuario_requerido),
):
    s = _get_sesion(req.session_id)
    try:
        from browser_agent.agent import ejecutar
        resultados = await ejecutar(req.plan, req.credenciales, req.email or "")
        duracion = time.time() - (s.get("t_inicio") or time.time())
        # Guardar sesión sin credenciales
        plan_sin_creds = {k: v for k, v in req.plan.items() if k != "credenciales_obtenidas"}
        guardar_sesion(
            plan=plan_sin_creds,
            resultados=resultados,
            email=req.email or s.get("email", ""),
            duracion_seg=round(duracion, 2),
            plan_id=s.get("plan_id"),
            usuario_id=user["id"],
        )
        return {"resultados": resultados, "ok": True}
    except Exception as e:
        return {"error": f"Error en ejecución: {e}", "resultados": []}


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    sesiones_activas = sum(1 for s in _sessions.values() if s["grabador"] is not None)
    return {"status": "ok", "sesiones_activas": sesiones_activas}


# ─── Historial y estadísticas ─────────────────────────────────────────────────

@app.get("/historial")
def historial(limit: int = 20, user: dict = Depends(_usuario_requerido)):
    return obtener_historial(limit)

@app.get("/estadisticas")
def estadisticas(user: dict = Depends(_usuario_requerido)):
    return obtener_estadisticas()

@app.get("/plan/{url_portal:path}")
def plan_activo(url_portal: str, user: dict = Depends(_usuario_requerido)):
    plan = cargar_plan_activo(url_portal)
    if not plan:
        return {"error": "No hay plan guardado para este portal"}
    return plan
