import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import streamlit as st
import pandas as pd

st.set_page_config(page_title="ArcaVision", layout="wide", page_icon="⚡")

st.markdown("""
<style>
.grabando-badge {
    background:#ff4444;color:white;padding:6px 14px;border-radius:20px;
    font-weight:600;font-size:14px;display:inline-block;animation:pulse 1.2s infinite;
}
.pausado-badge {
    background:#f5a623;color:white;padding:6px 14px;border-radius:20px;
    font-weight:600;font-size:14px;display:inline-block;
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
</style>
""", unsafe_allow_html=True)


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("ArcaVision ⚡")
    st.caption("Agente IA para Arca Continental")
    st.divider()
    user_email = st.text_input("Email del usuario", placeholder="usuario@arca.com")
    url_portal = st.text_input("URL del portal", placeholder="https://portal.walmart.com.mx")
    umbral = st.slider("Umbral de confianza", 0.50, 0.95, 0.70, 0.05,
                       help="Campos bajo este umbral requieren revisión humana")
    st.divider()
    st.caption(f"Etapa: **{st.session_state.get('etapa', 'captura')}**")
    if st.button("↺ Reiniciar todo", use_container_width=True):
        if st.session_state.get("grabador"):
            try: st.session_state.grabador.detener()
            except: pass
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


# ─── Estado ───────────────────────────────────────────────────────────────────
# Etapas: captura → preguntas → revision → ejecucion → aprobacion → resultado
for k, v in {
    "etapa": "captura", "grabando": False,
    "pausado": False,   "grabador": None,
    "fase_a": None,     "plan": None,
    "plan_confirmado": None, "resultados": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 1 — Grabación
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.etapa == "captura":
    st.title("Captura del workflow")
    st.write("Habla en voz alta mientras ejecutas el proceso en tu browser.")

    if url_portal:
        st.info(f"Portal: **{url_portal}**")
    else:
        st.warning("Ingresa la URL del portal en el sidebar antes de grabar.")

    st.divider()

    if not st.session_state.grabando:
        if st.button("🔴 Iniciar grabación", type="primary", use_container_width=True):
            if not url_portal:
                st.error("Ingresa la URL del portal primero.")
                st.stop()
            from browser_agent.grabador import Grabador
            g = Grabador()
            g.iniciar()
            st.session_state.grabador = g
            st.session_state.grabando = True
            st.session_state.pausado = False
            st.rerun()
    else:
        if not st.session_state.pausado:
            st.markdown('<div class="grabando-badge">🔴 GRABANDO</div>', unsafe_allow_html=True)
            st.caption("Ejecuta el proceso en tu browser y explica en voz alta lo que haces.")
        else:
            st.markdown('<div class="pausado-badge">⏸ PAUSADO</div>', unsafe_allow_html=True)
            st.caption("Grabación pausada.")

        st.divider()
        col1, col2, col3 = st.columns(3)

        with col1:
            if not st.session_state.pausado:
                if st.button("⏸ Pausar", use_container_width=True):
                    try:
                        st.session_state.grabador.mouse_listener.stop()
                        st.session_state.grabador.keyboard_listener.stop()
                    except: pass
                    st.session_state.pausado = True
                    st.rerun()
            else:
                if st.button("▶ Continuar", use_container_width=True, type="primary"):
                    from pynput import mouse, keyboard
                    g = st.session_state.grabador
                    g.mouse_listener = mouse.Listener(on_click=g.on_click)
                    g.keyboard_listener = keyboard.Listener(on_press=g.on_key)
                    g.mouse_listener.start()
                    g.keyboard_listener.start()
                    st.session_state.pausado = False
                    st.rerun()

        with col2:
            if st.button("🔄 Reiniciar grabación", use_container_width=True):
                try: st.session_state.grabador.detener()
                except: pass
                from browser_agent.grabador import Grabador
                g = Grabador()
                g.iniciar()
                st.session_state.grabador = g
                st.session_state.pausado = False
                st.rerun()

        with col3:
            if st.button("⏹ Terminar y analizar", use_container_width=True, type="primary"):
                g = st.session_state.grabador
                with st.spinner("Deteniendo grabación..."):
                    sesion = g.detener()
                    st.session_state.grabando = False
                    st.session_state.grabador = None

                if len(sesion.get("eventos", [])) == 0:
                    st.error("No se grabaron eventos. Intenta de nuevo.")
                    st.stop()

                with st.spinner("🧠 Claude analizando screenshots y audio..."):
                    from core.procesar import analizar_sesion
                    try:
                        resultado = analizar_sesion(sesion["eventos"], sesion["audio_path"])
                        resultado["plan"]["url_portal"] = url_portal
                        st.session_state.fase_a = resultado

                        # Si no hay preguntas, saltar directo a revisión
                        if not resultado["preguntas"]:
                            from core.procesar import completar_plan
                            plan, _ = completar_plan(resultado, {})
                            st.session_state.plan = plan
                            st.session_state.etapa = "revision"
                        else:
                            st.session_state.etapa = "preguntas"
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error analizando sesión: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 2 — Preguntas de la IA al usuario
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "preguntas":
    fase_a = st.session_state.fase_a

    st.title("El agente tiene preguntas")
    st.write("Hay información que no pude ver durante la grabación. Responde para que pueda ejecutar el proceso correctamente.")

    if fase_a.get("ya_se"):
        with st.expander("✅ Lo que aprendí sin preguntar"):
            for cosa in fase_a["ya_se"]:
                st.write(f"• {cosa}")

    st.divider()

    respuestas = {}
    for p in fase_a["preguntas"]:
        st.markdown(f"**{p['pregunta']}**")
        st.caption(f"*Por qué lo necesito: {p['por_que']}*")
        es_pass = p.get("es_password", False) or any(
            w in p["campo"].lower() for w in ["password", "contraseña", "clave", "pass"]
        )
        val = st.text_input(
            label=p["campo"],
            type="password" if es_pass else "default",
            key=f"preg_{p['campo']}",
            label_visibility="collapsed"
        )
        respuestas[p["campo"]] = val
        st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("← Volver a grabar", use_container_width=True):
            st.session_state.etapa = "captura"
            st.rerun()
    with col_b:
        if st.button("Confirmar respuestas →", type="primary", use_container_width=True):
            vacias = [p["campo"] for p in fase_a["preguntas"] if not respuestas.get(p["campo"])]
            if vacias:
                st.error(f"Faltan respuestas: {', '.join(vacias)}")
                st.stop()
            from core.procesar import completar_plan
            plan, errores = completar_plan(fase_a, respuestas)
            if errores:
                for e in errores:
                    st.warning(e)
            st.session_state.plan = plan
            st.session_state.etapa = "revision"
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 3 — Revisión del plan
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "revision":
    plan = st.session_state.plan

    st.title("Revisa el workflow detectado")

    col1, col2, col3 = st.columns(3)
    col1.metric("Origen",  plan.get("plataforma_origen", "—"))
    col2.metric("Destino", plan.get("plataforma_destino", "—"))
    col3.metric("Pasos",   len(plan.get("pasos", [])))
    st.caption(f"Portal: **{plan.get('url_portal', url_portal or '—')}**")
    st.caption(f"Objetivo: *{plan.get('objetivo', '')}*")

    st.divider()
    st.subheader("Pasos detectados")
    iconos = {"navegar":"🌐","click":"🖱","escribir":"⌨️","seleccionar":"☑️",
              "extraer":"📋","verificar":"🔍","esperar":"⏳"}
    for paso in plan.get("pasos", []):
        ic = iconos.get(paso.get("accion", ""), "▸")
        st.write(f"{paso['numero']}. {ic} {paso['intencion']}")

    st.divider()
    st.subheader("Mapeo de campos")
    st.caption("Edita los campos incorrectos antes de continuar.")

    mapeos_editados = []
    for i, campo in enumerate(plan.get("mapeo_campos", [])):
        p = campo.get("confianza", 1.0)
        if p >= umbral:          color, estado = "green",  "Actúa sola"
        elif p >= umbral - 0.15: color, estado = "orange", "Revisar"
        else:                    color, estado = "red",     "Requiere corrección"

        c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
        with c1: origen  = st.text_input("Origen",      value=campo["campo_origen"],  key=f"o_{i}")
        with c2: destino = st.text_input("Destino Arca", value=campo["campo_destino"], key=f"d_{i}")
        with c3: st.metric("Confianza", f"{p:.2f}")
        with c4: st.markdown(f":{color}[{estado}]")
        mapeos_editados.append({"campo_origen": origen, "campo_destino": destino,
                                 "confianza": p, "flag": p < umbral})

    flags = [m for m in mapeos_editados if m["flag"]]
    if flags:
        st.warning(f"{len(flags)} campo(s) con confianza baja.")

    st.divider()
    ca, cb = st.columns(2)
    with ca:
        if st.button("← Volver a grabar", use_container_width=True):
            st.session_state.etapa = "captura"
            st.rerun()
    with cb:
        if st.button("Confirmar y ejecutar agente →", type="primary", use_container_width=True):
            plan["mapeo_campos"] = mapeos_editados
            st.session_state.plan_confirmado = plan
            st.session_state.etapa = "ejecucion"
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 4 — Ejecución
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "ejecucion":
    st.title("Agente ejecutando")
    plan = st.session_state.plan_confirmado
    st.caption(f"Proceso: *{plan.get('objetivo', '')}*")
    st.caption(f"Portal: **{plan.get('url_portal', url_portal or '—')}**")
    st.divider()

    credenciales = {}
    necesarias = plan.get("credenciales_necesarias", [])
    if necesarias:
        st.subheader("Datos necesarios para ejecutar")
        for item in necesarias:
            es_pass = any(w in item.lower() for w in ["password","contraseña","clave","pass"])
            val = st.text_input(item, type="password" if es_pass else "default", key=f"cred_{item}")
            credenciales[item] = val
        if not st.button("Iniciar ejecución", type="primary", use_container_width=True):
            st.stop()

    with st.spinner("El agente está navegando el portal..."):
        from browser_agent.agent import ejecutar
        try:
            resultados = asyncio.run(ejecutar(plan, credenciales, user_email or ""))
            st.session_state.resultados = resultados
            st.session_state.etapa = "aprobacion"
            st.rerun()
        except Exception as e:
            st.error(f"Error en la ejecución: {e}")
            if st.button("Reintentar"):
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 5 — Aprobación
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "aprobacion":
    st.title("Aprobación de resultados")
    resultados = st.session_state.resultados
    plan       = st.session_state.plan_confirmado

    ok    = sum(1 for r in resultados if r["estado"] == "ok")
    warn  = sum(1 for r in resultados if r["estado"] == "advertencia")
    error = sum(1 for r in resultados if r["estado"] == "error")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total pasos",     len(resultados))
    c2.metric("✅ Exitosos",     ok)
    c3.metric("⚠️ Advertencias", warn)
    c4.metric("❌ Errores",      error)

    st.divider()
    for r in resultados:
        ic = "✅" if r["estado"]=="ok" else "⚠️" if r["estado"]=="advertencia" else "❌"
        st.write(f"{ic} **Paso {r['paso']}** — `{r['accion']}`")

    datos_extraidos = {f"paso_{r['paso']}": r["datos_extraidos"]
                       for r in resultados if r.get("datos_extraidos")}
    if datos_extraidos:
        st.divider()
        st.subheader("Datos extraídos del portal")
        st.json(datos_extraidos)

    st.divider()
    ca, cb = st.columns(2)
    with ca:
        if st.button("← Rechazar — volver a grabar", use_container_width=True):
            st.session_state.etapa = "captura"
            st.rerun()
    with cb:
        if st.button("Aprobar y generar reporte →", type="primary", use_container_width=True):
            st.session_state.etapa = "resultado"
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 6 — Resultados + Dashboards
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "resultado":
    st.title("Reporte ejecutivo")
    st.success("Proceso completado y aprobado.")

    resultados = st.session_state.resultados
    plan       = st.session_state.plan_confirmado
    ok    = sum(1 for r in resultados if r["estado"] == "ok")
    error = sum(1 for r in resultados if r["estado"] != "ok")
    total = len(resultados)

    c1, c2, c3 = st.columns(3)
    c1.metric("Pasos exitosos",  f"{ok}/{total}")
    c2.metric("Origen",  plan.get("plataforma_origen", "—"))
    c3.metric("Destino", plan.get("plataforma_destino", "—"))

    st.divider()

    # ── Dashboard 1: Monte Carlo ───────────────────────────────────────────────
    st.subheader("📊 Dashboard ejecutivo — Impacto económico (Monte Carlo)")
    st.caption("Estimación probabilística del impacto de pasos fallidos sobre el valor de la orden.")
    try:
        from frontend.monte_carlo import estimar_impacto, graficar_distribucion
        historico = [15800, 18420, 22100, 17300, 19800, 16500, 21000, 18900]
        mc = estimar_impacto(
            valor_orden=sum(historico)/len(historico),
            n_missing=error,
            historico_valores=historico,
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Impacto medio",       f"${mc['media']:,.0f} MXN")
        m2.metric("IC 95% — inferior",   f"${mc['ic_low']:,.0f} MXN")
        m3.metric("IC 95% — superior",   f"${mc['ic_high']:,.0f} MXN")
        st.plotly_chart(graficar_distribucion(mc), use_container_width=True)
        st.caption(f"Simulación con {mc['n_sim']:,} iteraciones · {len(historico)} órdenes históricas.")
    except Exception as e:
        st.error(f"Error generando dashboard Monte Carlo: {e}")

    st.divider()

    # ── Dashboard 2: Errores del agente ───────────────────────────────────────
    st.subheader("🔍 Dashboard de errores — Análisis de fallos del agente")
    st.caption("Para ingenieros: detalle de cada paso y resultado al navegar el portal.")
    try:
        import plotly.express as px
        df = pd.DataFrame([{
            "Paso":   r["paso"],
            "Acción": r["accion"],
            "Estado": r["estado"],
            "Datos":  str(r.get("datos_extraidos",""))[:80] if r.get("datos_extraidos") else "—",
        } for r in resultados])

        def color_estado(val):
            return {
                "ok":          "background-color:#1a3a1a;color:#4caf50",
                "advertencia": "background-color:#3a2e00;color:#f5a623",
                "error":       "background-color:#3a1a1a;color:#ff4444",
            }.get(val, "")

        st.dataframe(
            df.style.map(color_estado, subset=["Estado"]),
            use_container_width=True, hide_index=True,
        )

        if len(df) > 0:
            tasa = df.groupby(["Acción","Estado"]).size().reset_index(name="count")
            fig2 = px.bar(
                tasa, x="Acción", y="count", color="Estado",
                color_discrete_map={"ok":"#4caf50","advertencia":"#f5a623","error":"#ff4444"},
                title="Resultado por tipo de acción",
                labels={"count":"Cantidad"},
            )
            fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig2, use_container_width=True)
    except Exception as e:
        st.error(f"Error generando dashboard de errores: {e}")

    st.divider()

    import json
    st.download_button(
        "⬇️ Descargar reporte JSON",
        data=json.dumps({"plan": plan, "resultados": resultados,
                         "resumen": f"{ok}/{total} pasos exitosos"},
                        indent=2, ensure_ascii=False),
        file_name="reporte_arcavision.json",
        mime="application/json",
        use_container_width=True,
    )

    st.divider()
    if st.button("↺ Nueva orden", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
