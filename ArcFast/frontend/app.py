"""
frontend/app.py  —  PERSONA 4
--------------------------------
UI principal en Streamlit. Orquesta todos los módulos.
Corre con: streamlit run frontend/app.py
"""

import streamlit as st
import json

st.set_page_config(page_title="ArcFast", layout="wide", page_icon="⚡")


# ─── Sidebar: configuración ───────────────────────────────────────────────────
with st.sidebar:
    st.title("ArcFast")
    st.caption("Agente IA para Arca Continental")
    st.divider()
    user_email = st.text_input("Email del usuario", placeholder="usuario@arca.com")
    url_portal = st.text_input("URL del portal", placeholder="https://portal.walmart.com")
    umbral = st.slider("Umbral de confianza", 0.50, 0.95, 0.70, 0.05,
                       help="Campos bajo este umbral se marcan para revisión humana")
    usar_mock = st.toggle("Usar datos mock (dev)", value=True)


# ─── Estado de la sesión ──────────────────────────────────────────────────────
if "etapa" not in st.session_state:
    st.session_state.etapa = "captura"   # captura → revision → ejecucion → aprobacion → resultado


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 1 — Captura del workflow
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.etapa == "captura":
    st.title("Captura del workflow")
    st.write("Graba tu pantalla mientras explicas el proceso. El agente aprenderá a replicarlo.")

    # TODO Persona 4: integrar el componente de grabación (prototipo existente)
    transcripcion = st.text_area(
        "Transcripción (generada automáticamente por Whisper)",
        height=160,
        placeholder="Aquí aparecerá la transcripción en vivo..."
    )

    if st.button("Analizar workflow", type="primary"):
        if usar_mock:
            from core.workflow_generator import workflow_desde_mock
            st.session_state.workflow = workflow_desde_mock()
        else:
            from core.workflow_generator import generar_workflow
            with st.spinner("Claude analizando la transcripción..."):
                st.session_state.workflow = generar_workflow(transcripcion, url_portal, umbral)

        st.session_state.etapa = "revision"
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 2 — Revisión y corrección del workflow
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "revision":
    st.title("Revisa el workflow detectado")
    workflow = st.session_state.workflow

    st.subheader("Pasos detectados")
    for i, paso in enumerate(workflow.pasos):
        st.write(f"{i+1}. {paso}")

    st.subheader("Mapeo de campos")
    st.caption("Edita los campos incorrectos antes de continuar.")

    mapeos_editados = []
    for mapeo in workflow.mapeos:
        p = mapeo.confianza
        if p >= umbral:
            color, estado = "green", "Actua sola"
        elif p >= umbral - 0.15:
            color, estado = "orange", "Revisar"
        else:
            color, estado = "red", "Requiere corrección"

        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
        with col1:
            origen = st.text_input("Origen", value=mapeo.campo_origen, key=f"o_{mapeo.campo_origen}")
        with col2:
            destino = st.text_input("Destino Arca", value=mapeo.campo_destino, key=f"d_{mapeo.campo_destino}")
        with col3:
            st.metric("Confianza", f"{p:.2f}")
        with col4:
            st.markdown(f":{color}[{estado}]")

        from shared.schemas import FieldMapping
        mapeos_editados.append(FieldMapping(
            campo_origen=origen,
            campo_destino=destino,
            confianza=p,
            flag=p < umbral,
        ))

    flags = [m for m in mapeos_editados if m.flag]
    if flags:
        st.warning(f"{len(flags)} campo(s) con baja confianza — revisa antes de continuar.")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Volver a capturar"):
            st.session_state.etapa = "captura"
            st.rerun()
    with col_b:
        if st.button("Confirmar y ejecutar agente", type="primary"):
            from shared.schemas import WorkflowConfirmado
            st.session_state.workflow_confirmado = WorkflowConfirmado(
                url_portal=url_portal or workflow.url_portal,
                pasos=workflow.pasos,
                mapeos=mapeos_editados,
            )
            st.session_state.etapa = "ejecucion"
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 3 — Ejecución del browser agent
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "ejecucion":
    st.title("Agente ejecutando...")

    with st.spinner("El agente está navegando el portal..."):
        if usar_mock:
            from browser_agent.agent import resultado_mock
            result = resultado_mock()
        else:
            from browser_agent.agent import ejecutar_en_portal
            result = ejecutar_en_portal(st.session_state.workflow_confirmado)

        st.session_state.agent_result = result

    st.success(f"Encontrados {len(result.missing_products)} productos faltantes.")
    if result.challenges:
        st.info("Challenges del agente: " + " · ".join(result.challenges))

    st.session_state.etapa = "aprobacion"
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 4 — Aprobación humana
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "aprobacion":
    st.title("Aprobación de la orden")
    result = st.session_state.agent_result

    st.subheader("Productos faltantes detectados")
    import pandas as pd
    df = pd.DataFrame([p.to_dict() for p in result.missing_products])
    st.dataframe(df, use_container_width=True)

    total = sum(p.precio_unitario * p.cantidad for p in result.missing_products)
    st.metric("Valor total de la orden", f"${total:,.2f} MXN")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Rechazar orden", type="secondary"):
            st.session_state.etapa = "captura"
            st.warning("Orden rechazada. Reiniciando...")
            st.rerun()
    with col_b:
        if st.button("Aprobar y registrar en Arca", type="primary"):
            st.session_state.etapa = "resultado"
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# ETAPA 5 — Resultado: PDF + Dashboard + Email
# ═══════════════════════════════════════════════════════════════════════════════
elif st.session_state.etapa == "resultado":
    st.title("Orden registrada")
    st.success("La orden fue enviada al sistema Arca.")

    # TODO Persona 4: generar PDF con ReportLab y mostrarlo aquí
    # TODO Persona 4: llamar postprocessing.pipeline.run_pipeline()
    # TODO Persona 4: mostrar dashboard Plotly con Monte Carlo

    st.info("Dashboard ejecutivo y reporte PDF aparecerán aquí.")

    if st.button("Nueva orden"):
        for key in ["workflow", "workflow_confirmado", "agent_result", "etapa"]:
            st.session_state.pop(key, None)
        st.rerun()
