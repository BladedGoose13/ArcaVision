"""
browser_agent/agent.py
-----------------------
Agente principal usando browser_use exclusivamente.
Corre en un thread separado con su propio event loop para evitar
el NotImplementedError de asyncio en Windows con uvicorn.
"""

import asyncio
import concurrent.futures
import json
import os
import random
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Detección de agente trabado ──────────────────────────────────────────────

def _agente_trabado(info: dict) -> bool:
    """True si el agente terminó sin completar nada útil."""
    return (
        not info.get("completado")
        and info.get("pasos_ok", 0) == 0
        and info.get("pasos_error", 0) >= 2
    )


def _run_browser_use_sync(task: str, api_key: str, modo_agresivo: bool = False,
                          max_steps: int = 25) -> dict:
    """
    Ejecuta browser_use Agent en un thread con su propio event loop.
    Retorna dict con estado real extraído del AgentHistoryList.
    modo_agresivo=True inyecta reglas estocásticas más fuertes para sacar al agente
    de loops de scroll cuando el primer intento no avanzó.
    max_steps escala con el tamaño del plan: un registro de compra (login +
    navegar + varios productos + formulario de orden) necesita más de 25 pasos,
    y al agotarlos a mitad del registro el agente parecía "trabado".
    """
    from browser_use import Agent
    from langchain_anthropic import ChatAnthropic

    task_final = task
    if modo_agresivo:
        # Prefijo de "modo forzado": instruye al modelo a comprometerse con clicks
        # aunque tenga incertidumbre, imitando una política epsilon-greedy.
        seed = random.randint(1000, 9999)   # rompe cualquier cache/memoria del LLM
        task_final = f"""[MODO DECISIÓN FORZADA #{seed}]
REGLA ÚNICA: En cada paso DEBES hacer click en el elemento más probable.
- Prohibido scrollear más de 1 vez por paso.
- Si ves el elemento o uno similar → click inmediato, sin verificar.
- Si la página no cambió tras un click → siguiente paso.
- Prefiere fallar en un click que no hacer nada.

""" + task

    async def _inner():
        llm   = ChatAnthropic(model="claude-opus-4-5", api_key=api_key)
        agent = Agent(
            task=task_final,
            llm=llm,
            max_failures=2,
            use_vision=False,
        )
        try:
            result = await agent.run(max_steps=max_steps)
        finally:
            # Cierre explícito del browser — browser_use NO lo cierra solo
            # al terminar run(). Probamos las APIs de varias versiones.
            await _cerrar_browser(agent)

        errores = result.errors() if hasattr(result, "errors") else []
        errores = [str(e) for e in errores if e]

        final = ""
        if hasattr(result, "final_result"):
            final = result.final_result() or ""
        if not final:
            # fallback: último extracted_content no vacío
            for r in reversed(result.action_results() if hasattr(result, "action_results") else []):
                if getattr(r, "extracted_content", None):
                    final = str(r.extracted_content)
                    break

        completado = result.is_done() if hasattr(result, "is_done") else False
        pasos_ok    = sum(1 for r in (result.action_results() if hasattr(result, "action_results") else [])
                         if getattr(r, "error", None) is None)
        pasos_error = sum(1 for r in (result.action_results() if hasattr(result, "action_results") else [])
                         if getattr(r, "error", None) is not None)

        return {
            "completado":   completado,
            "final":        final,
            "errores":      errores,
            "pasos_ok":     pasos_ok,
            "pasos_error":  pasos_error,
        }

    return asyncio.run(_inner())


def _run_browser_use_sync_agresivo(task: str, api_key: str) -> dict:
    """Atajo para ThreadPoolExecutor (no admite kwargs)."""
    return _run_browser_use_sync(task, api_key, modo_agresivo=True)


async def _cerrar_browser(agent) -> None:
    """
    Cierra la sesión de browser que browser_use deja abierta tras run().
    Compatible con distintas versiones: prueba agent.close(),
    agent.browser_session, agent.browser y sus métodos close/stop/kill.
    """
    import inspect

    async def _intentar(fn):
        try:
            res = fn()
            if inspect.isawaitable(res):
                await res
            return True
        except Exception:
            return False

    # 1) API moderna: agent.close() cierra todo el stack
    if hasattr(agent, "close"):
        if await _intentar(agent.close):
            print("  🔒 Browser cerrado (agent.close)")
            return

    # 2) Sesión de browser expuesta directamente
    for attr in ("browser_session", "browser", "_browser_session", "_browser"):
        sesion = getattr(agent, attr, None)
        if sesion is None:
            continue
        for metodo in ("close", "stop", "kill"):
            fn = getattr(sesion, metodo, None)
            if fn and await _intentar(fn):
                print(f"  🔒 Browser cerrado ({attr}.{metodo})")
                return

    print("  ⚠️  No se pudo cerrar el browser automáticamente")


def _extraer_json_balanceado(texto: str) -> dict:
    """
    Extrae el primer objeto JSON completo del texto balanceando llaves.
    Reemplaza el regex anterior que no soportaba JSON anidado.
    """
    if not texto:
        return {}
    inicio = texto.find("{")
    while inicio != -1:
        nivel = 0
        en_str = False
        escape = False
        for i in range(inicio, len(texto)):
            c = texto[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                en_str = not en_str
                continue
            if en_str:
                continue
            if c == "{":
                nivel += 1
            elif c == "}":
                nivel -= 1
                if nivel == 0:
                    try:
                        return json.loads(texto[inicio:i + 1])
                    except json.JSONDecodeError:
                        break  # objeto malformado: busca el siguiente "{"
        inicio = texto.find("{", inicio + 1)
    return {}


async def ejecutar_con_browser_use(plan: dict, credenciales: dict, email_reporte: str) -> list:
    todas   = {**credenciales, **plan.get("credenciales_obtenidas", {})}
    origen  = plan.get("plataforma_origen", "")
    destino = plan.get("plataforma_destino", "")
    objetivo = plan.get("objetivo", "Ejecutar el proceso aprendido")

    creds_texto = "\n".join([f"- {k}: {v}" for k, v in todas.items() if v])
    mapeo_texto = "\n".join([
        f"- '{m['campo_origen']}' en {origen} → '{m['campo_destino']}' en {destino}"
        for m in plan.get("mapeo_campos", [])
    ]) or "Aprende el mapeo observando la página"

    pasos_texto = "\n".join([
        f"{p['numero']}. [{p['accion'].upper()}] {p['intencion']}"
        + (f" → valor: {p['valor']}" if p.get('valor') else "")
        for p in plan.get("pasos", [])
    ])

    n_pasos = len(plan.get("pasos", []))
    task = f"""Eres un agente que automatiza procesos entre dos sistemas web para Arca Continental.

OBJETIVO: {objetivo}
SISTEMAS: Origen={origen} → Destino={destino}

CREDENCIALES:
{creds_texto or "Ninguna — infiere del contexto"}

MAPEO DE CAMPOS:
{mapeo_texto}

PASOS A EJECUTAR ({n_pasos} en total — guíate por la intención, no por coordenadas):
{pasos_texto}

CÓMO ACTUAR — PROTOCOLO DE DECISIÓN ESTOCÁSTICA:
1. USA el texto/label/placeholder del elemento DOM. Si el objetivo aparece en la lista → click inmediato. No scrollees "por si acaso".
2. CONTADOR DE SCROLL: lleva mentalmente la cuenta de scrolls consecutivos sin click.
   - 1-2 scrolls seguidos → permitido si el elemento no estaba visible.
   - 3 scrolls seguidos sin click → PARA. Elige el elemento más parecido al objetivo y haz click, aunque no estés seguro al 100%. Un click imperfecto vale más que 5 scrolls perfectos.
   - 5+ scrolls en el mismo paso → el elemento no está en esta página. Avanza al siguiente paso.
3. COMPROMISO FORZADO: si dudas entre dos elementos, elige el primero que contenga alguna palabra clave del paso actual y haz click sin más análisis.
4. Si un click no cambia la página → no lo repitas. Prueba el siguiente elemento candidato una vez; si tampoco, avanza al siguiente paso.
5. Si 2 pasos seguidos fallan, o aparece captcha/login inesperado, o la página no carga → TERMINA y reporta el motivo.
6. Cuando completes todos los pasos → termina de inmediato.

PROTOCOLO ANTI-ESPIRAL PARA FORMULARIOS (OBLIGATORIO — sin excepciones):
- ANTES de tocar cualquier campo, lee el formulario completo y enumera mentalmente todos los campos visibles.
- Llena en orden de arriba a abajo. Por cada campo: (1) click UNA vez, (2) escribe el valor, (3) presiona Tab para avanzar. Solo Tab — NUNCA vuelvas a hacer click en ese campo.
- NUNCA hagas click en un campo que ya tiene texto escrito. Si ya tiene el valor correcto → salta al siguiente.
- NUNCA uses backspace/delete para borrar lo que escribiste. Si cometiste un error en un campo → déjalo y continúa; anótalo en "datos_extraidos".
- NUNCA vuelvas a recorrer el formulario para "verificar". Llenado lineal, solo hacia adelante.
- Para dropdowns/selects: click para abrir → click en la primera opción que contenga la palabra clave → avanza. Máximo 1 intento.
- Al terminar el último campo → busca el botón guardar/registrar/confirmar → click → espera confirmación → termina.
- Si tras 1 intento un campo obligatorio rechaza el valor → anótalo en "datos_extraidos" y continúa; no bloquees el proceso entero.
- CONTADOR ANTI-LOOP: si estás en el mismo formulario y llevas más de 3 acciones seguidas sin avanzar de campo → detente, reporta estado parcial y llama a done.

REGISTRO DE COMPRAS (crítico para el reporte):
Cada vez que agregues un producto al carrito/orden, anota nombre exacto, precio unitario y cantidad.
Llena el array "productos" del JSON final con esos datos reales (no inventes precios).

Al finalizar (éxito o fallo) llama a la acción "done" con EXACTAMENTE este JSON:
{{
  "estado_final": "completado|parcial|bloqueado",
  "pasos_ok": <entero, cuántos de los {n_pasos} pasos del plan lograste>,
  "pasos_error": <entero>,
  "motivo_parada": "vacío si completado; si no, qué te detuvo",
  "productos": [
    {{"nombre": "...", "precio_unitario": 0.0, "cantidad": 1, "sku": "", "estado": "ok"}}
  ],
  "datos_extraidos": {{"clave": "valor relevante observado"}}
}}"""

    print(f"\n🤖 browser_use ejecutando: {objetivo}")
    print(f"   Sistemas: {origen} → {destino}\n")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    timeout_seg = int(os.getenv("AGENT_TIMEOUT_SEG", "300"))  # 5 min por defecto
    # ~5 acciones de browser por paso del plan; piso 30, techo configurable con
    # AGENT_MAX_STEPS (por defecto 120 — suficiente para login + navegación +
    # formulario de 10+ campos + confirmación sin agotar el presupuesto a mitad).
    _max_cap = int(os.getenv("AGENT_MAX_STEPS", "120"))
    max_steps = max(30, min(_max_cap, n_pasos * 5 + 15))
    estado = "error"
    resultado_texto = ""
    reporte_agente = {}          # JSON auto-reportado por el agente (done action)
    errores_agente = []
    completado_agente = False

    async def _lanzar(fn_sync):
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = loop.run_in_executor(pool, fn_sync)
            return await asyncio.wait_for(future, timeout=timeout_seg)

    try:
        # ── Intento 1: modo normal ────────────────────────────────────────────
        import functools
        info = await _lanzar(functools.partial(_run_browser_use_sync, task, api_key,
                                               False, max_steps))

        # ── Reintento estocástico si el agente se trabó (0 pasos útiles) ─────
        if _agente_trabado(info):
            print("\n🎲 Agente trabado — relanzando en modo decisión forzada...")
            try:
                info2 = await _lanzar(
                    functools.partial(_run_browser_use_sync, task, api_key, True, max_steps)
                )
                # Usa el reintento solo si mejoró
                if info2.get("pasos_ok", 0) >= info.get("pasos_ok", 0):
                    info = info2
                    print("   Modo forzado produjo mejor resultado")
                else:
                    print("   Modo normal fue mejor — usando primer resultado")
            except Exception as e2:
                print(f"   Reintento forzado falló: {e2} — usando primer resultado")

        resultado_texto   = info.get("final", "")
        errores_agente    = info.get("errores", [])
        completado_agente = info.get("completado", False)
        reporte_agente    = _extraer_json_balanceado(resultado_texto)

        if completado_agente:
            estado = "ok"
            print(f"\n✅ browser_use completó el proceso")
        else:
            estado = "parcial" if info.get("pasos_ok", 0) > 0 else "error"
            motivo = (reporte_agente.get("motivo_parada")
                      or (errores_agente[0] if errores_agente else "detenido sin completar"))
            print(f"\n⚠️  browser_use terminó sin completar — {motivo}")

        if resultado_texto:
            print(f"   Resultado: {resultado_texto[:200]}")

    except asyncio.TimeoutError:
        resultado_texto = f"Timeout: el agente superó {timeout_seg}s sin terminar"
        print(f"\n⏱️  Timeout — agente detenido tras {timeout_seg}s")
        estado = "timeout"
    except Exception as e:
        resultado_texto = f"Error: {e}"
        print(f"\n❌ Error en browser_use: {e}")
        estado = "error"

    # Guardar reporte JSON
    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/reporte.json", "w", encoding="utf-8") as f:
        json.dump({"objetivo": objetivo, "origen": origen, "destino": destino,
                   "resultado": resultado_texto, "fecha": datetime.now().isoformat(),
                   "motor": "browser_use"}, f, indent=2, ensure_ascii=False)

    # Datos estructurados auto-reportados por el agente (JSON balanceado)
    datos_extraidos = reporte_agente.get("datos_extraidos") or {}
    productos       = reporte_agente.get("productos") or []
    if not datos_extraidos and resultado_texto:
        datos_extraidos = {"resumen": resultado_texto[:500]}

    pasos = plan.get("pasos", [])
    n = len(pasos)
    if not pasos:
        return [{"paso": 1, "accion": "browser_use", "estado": estado,
                 "intencion": objetivo, "datos_extraidos": datos_extraidos,
                 "productos": productos}]

    # ── Mapeo honesto de estado por paso del PLAN (no por acciones del agente) ──
    if completado_agente:
        n_ok = n
    elif estado == "error":
        n_ok = 0
    else:  # parcial / timeout → usa los pasos_ok auto-reportados, acotado al plan
        n_ok = max(0, min(n - 1, int(reporte_agente.get("pasos_ok", 0) or 0)))

    resultados = []
    for i, p in enumerate(pasos):
        es_ultimo = (i == n - 1)
        if i < n_ok:
            paso_estado = "ok"
        elif i == n_ok and estado in ("timeout", "error", "parcial"):
            paso_estado = estado          # el paso donde se detuvo lleva la causa
        else:
            paso_estado = "error"
        resultados.append({
            "paso":            p["numero"],
            "accion":          p["accion"],
            "intencion":       p["intencion"],
            "estado":          paso_estado,
            "detalle_error":   (errores_agente[0][:200] if errores_agente and paso_estado != "ok" else ""),
            "datos_extraidos": datos_extraidos if es_ultimo else None,
            "productos":       productos if es_ultimo else None,
        })
    return resultados


# ─── Entry point ─────────────────────────────────────────────────────────────

async def ejecutar(plan: dict, credenciales: dict, email_reporte: str) -> list:
    """
    Ejecuta el plan usando browser_use y luego genera reportes, guarda en SQLite
    y envía email.
    """
    print(f"\n🤖 Ejecutando: {plan.get('objetivo')}")

    resultados = await ejecutar_con_browser_use(plan, credenciales, email_reporte)
    motor = "browser_use"

    ok = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\n{'─'*50}")
    print(f"  Motor   : {motor}")
    print(f"  Resultado: {ok}/{len(resultados)} pasos exitosos")

    datos_extraidos = {
        f"paso_{r.get('paso', i)}": r["datos_extraidos"]
        for i, r in enumerate(resultados) if r.get("datos_extraidos")
    }

    # Productos reales auto-reportados por el agente (para el Excel de compras)
    productos = next((r["productos"] for r in resultados if r.get("productos")), [])

    # Guardar en SQLite
    try:
        from database.db import guardar_sesion
        guardar_sesion(
            plan=plan,
            resultados=resultados,
            email=email_reporte,
            duracion_seg=None,
        )
        print("  💾 Guardado en SQLite")
    except Exception as e:
        print(f"  ⚠️  SQLite no disponible: {e}")

    # Generar los tres reportes: Excel compras, PDF IA, Excel errores
    rutas = {}
    datos_reporte = {
        "objetivo":        plan.get("objetivo", "Proceso"),
        "origen":          plan.get("plataforma_origen", ""),
        "destino":         plan.get("plataforma_destino", ""),
        "resultados":      resultados,
        "datos_extraidos": datos_extraidos,
        "productos":       productos,
        "email":           email_reporte,
        "fecha":           datetime.now().isoformat(),
        "motor":           motor,
        "iteraciones":     len(resultados),
        "plan":            plan,
    }
    try:
        from postprocessing.reporte import generar_todos_los_reportes
        rutas = generar_todos_los_reportes(datos_reporte)
        print(f"  📦 Excel compras : {rutas.get('excel_compras')}")
        print(f"  📄 PDF reporte IA: {rutas.get('pdf_reporte')}")
        print(f"  📊 Excel errores : {rutas.get('excel_errores')}")
    except Exception as e:
        print(f"  ⚠️  Reportes no generados: {e}")

    # Pipeline completo de ticket: extrae pedido, SQLite, historial, Sheets, email
    try:
        from postprocessing.reporte import procesar_ticket_completo
        ticket_info = procesar_ticket_completo(
            datos_reporte=datos_reporte,
            email_cliente=email_reporte,
            excel_path=rutas.get("excel_compras"),
            sesion_id=None,
        )
        print(f"  🎫 Ticket: {ticket_info.get('ticket_path')}")
    except Exception as e:
        print(f"  ⚠️  Ticket no generado: {e}")

    return resultados


# _enviar_email reemplazado por procesar_ticket_completo en postprocessing/reporte.py
