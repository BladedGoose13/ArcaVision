"""
backend/api.py
--------------
FastAPI que conecta el frontend HTML con el agente Python.
Corre con: uvicorn backend.api:app --reload --port 8000
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
from database.db import (guardar_plan, guardar_sesion, cargar_plan_activo,
                          obtener_historial, obtener_estadisticas,
                          guardar_pedido, obtener_pedidos)

app = FastAPI(title="ArcaVision API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir el frontend estático
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend_web")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# ─── Estado en memoria (una sesión a la vez para el hack) ─────────────────────
session = {
    "grabador":   None,
    "sesion":     None,
    "fase_a":     None,
    "plan":       None,
    "plan_id":    None,
    "url_portal": "",
    "email":      "",
    "t_inicio":   None,
}


# ─── Modelos ──────────────────────────────────────────────────────────────────
class IniciarGrabacionReq(BaseModel):
    url_portal: str
    email: Optional[str] = ""

class CompletarReq(BaseModel):
    respuestas: dict

class EjecutarReq(BaseModel):
    plan: dict
    credenciales: dict
    email: Optional[str] = ""


# ─── Frontend ─────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse(os.path.join(frontend_path, "index.html"))


# ─── Auth ─────────────────────────────────────────────────────────────────────
class LoginReq(BaseModel):
    email: str
    password: str
    rol: Optional[str] = None

class RegisterReq(BaseModel):
    email: str
    password: str
    rol: str
    empresa: str

@app.post("/auth/login")
def auth_login(req: LoginReq):
    from database.db import login
    user = login(req.email, req.password)
    if not user:
        return {"error": "Email o contraseña incorrectos"}
    if req.rol and user["rol"] != req.rol:
        return {"error": f"Esta cuenta no tiene acceso al portal de {req.rol}"}
    return {
        "id":      user["id"],
        "email":   user["email"],
        "rol":     user["rol"],
        "empresa": user["empresa"],
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
def grabar_iniciar(req: IniciarGrabacionReq):
    from browser_agent.grabador import Grabador
    if session["grabador"]:
        try:
            session["grabador"].detener()
        except Exception as e:
            print(f"  ⚠️  Error deteniendo grabador anterior: {e}")

    g = Grabador()
    g.iniciar()
    session["grabador"]   = g
    session["url_portal"] = req.url_portal
    session["email"]      = req.email
    session["sesion"]     = None
    session["fase_a"]     = None
    session["plan"]       = None
    return {"ok": True}


@app.post("/grabar/pausar")
def grabar_pausar():
    g = session.get("grabador")
    if not g:
        return {"ok": False, "error": "No hay grabación activa"}
    try:
        g.mouse_listener.stop()
        g.keyboard_listener.stop()
    except Exception as e:
        print(f"  ⚠️  Error pausando listeners: {e}")
    return {"ok": True}


@app.post("/grabar/continuar")
def grabar_continuar():
    g = session.get("grabador")
    if not g:
        return {"ok": False, "error": "No hay grabación activa"}
    from pynput import mouse, keyboard
    g.mouse_listener = mouse.Listener(on_click=g.on_click)
    g.keyboard_listener = keyboard.Listener(on_press=g.on_key)
    g.mouse_listener.start()
    g.keyboard_listener.start()
    return {"ok": True}


@app.post("/grabar/reiniciar")
def grabar_reiniciar(req: IniciarGrabacionReq):
    from browser_agent.grabador import Grabador
    if session["grabador"]:
        try:
            session["grabador"].detener()
        except Exception as e:
            print(f"  ⚠️  Error deteniendo grabador anterior: {e}")
    g = Grabador()
    g.iniciar()
    session["grabador"]   = g
    session["url_portal"] = req.url_portal
    session["email"]      = req.email
    return {"ok": True}


@app.post("/grabar/terminar")
def grabar_terminar():
    g = session.get("grabador")
    if not g:
        return {"error": "No hay grabación activa"}

    try:
        sesion_data = g.detener()
        session["sesion"]  = sesion_data
        session["grabador"] = None
    except Exception as e:
        return {"error": f"Error deteniendo grabación: {e}"}

    if len(sesion_data.get("eventos", [])) == 0:
        return {"error": "No se grabaron eventos. Intenta de nuevo."}

    try:
        from core.procesar import analizar_sesion
        resultado = analizar_sesion(sesion_data["eventos"], sesion_data["audio_path"])
        resultado["plan"]["url_portal"] = session["url_portal"]
        session["fase_a"] = resultado
        return resultado
    except Exception as e:
        return {"error": f"Error analizando sesión: {e}"}


# ─── Completar plan ───────────────────────────────────────────────────────────
@app.post("/completar")
def completar(req: CompletarReq):
    fase_a = session.get("fase_a")
    if not fase_a:
        return {"error": "No hay sesión analizada"}
    try:
        from core.procesar import completar_plan
        plan, errores = completar_plan(fase_a, req.respuestas)
        session["plan"] = plan
        # Guardar plan en DB
        plan_id = guardar_plan(plan)
        session["plan_id"] = plan_id
        session["t_inicio"] = time.time()
        return plan
    except Exception as e:
        return {"error": f"Error completando plan: {e}"}


# ─── Ejecutar agente ──────────────────────────────────────────────────────────
@app.post("/ejecutar")
async def ejecutar_agente(req: EjecutarReq):
    try:
        from browser_agent.agent import ejecutar
        resultados = await ejecutar(req.plan, req.credenciales, req.email or "")
        duracion = time.time() - (session.get("t_inicio") or time.time())
        guardar_sesion(
            plan=req.plan,
            resultados=resultados,
            email=req.email or session.get("email", ""),
            duracion_seg=round(duracion, 2),
            plan_id=session.get("plan_id"),
        )
        return {"resultados": resultados, "ok": True}
    except Exception as e:
        print(f"  ❌ Error en /ejecutar: {e}")
        return {"error": str(e), "resultados": [], "ok": False}


# ─── Health check ─────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "sesion_activa": session["grabador"] is not None}


# ─── Historial, estadísticas y pedidos ───────────────────────────────────────
@app.get("/historial")
def historial(limit: int = 20):
    return obtener_historial(limit)


@app.get("/pedidos")
def pedidos(limit: int = 50):
    return obtener_pedidos(limit)


@app.get("/ticket")
def ticket_html():
    from fastapi.responses import HTMLResponse
    ticket_path = "reportes/ticket.html"
    if not __import__("pathlib").Path(ticket_path).exists():
        return HTMLResponse("<p>No hay ticket generado aún.</p>")
    return HTMLResponse(open(ticket_path, encoding="utf-8").read())


@app.get("/estadisticas")
def estadisticas():
    return obtener_estadisticas()


@app.get("/plan/{url_portal:path}")
def plan_activo(url_portal: str):
    plan = cargar_plan_activo(url_portal)
    if not plan:
        return {"error": "No hay plan guardado para este portal"}
    return plan
