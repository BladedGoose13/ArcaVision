"""
frontend/dashboard_proveedor.py
--------------------------------
Dashboard Streamlit para el equipo de Arca Continental (proveedor).
Permite seleccionar una empresa cliente y ver:
  - Historial de órdenes (valor + missing products)
  - Simulación Monte Carlo del impacto económico
  - Predicción de las próximas 6 órdenes
  - KPIs clave: valor promedio, tasa de missing, pérdida anual estimada

Ejecutar:
    streamlit run frontend/dashboard_proveedor.py
"""

import streamlit as st
from pathlib import Path
import sys

# Asegurar que el root del proyecto esté en el path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from frontend.monte_carlo import (
    init_demo_db,
    get_empresas,
    get_historial,
    estimar_impacto,
    predecir_proxima_orden,
    graficar_distribucion,
    graficar_prediccion,
    graficar_historial,
)

DB_PATH = ROOT / "data" / "arcfast.db"

# ---------------------------------------------------------------------------
# Configuración de la página
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="ArcFast — Analytics",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS personalizado
# ---------------------------------------------------------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Syne:wght@400;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Syne', sans-serif;
    background-color: #0A0E1A;
    color: #E2E8F0;
}

.block-container { padding-top: 2rem; padding-bottom: 2rem; }

/* KPI cards */
.kpi-card {
    background: linear-gradient(135deg, #0D1117 0%, #111827 100%);
    border: 1px solid #1E2733;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    text-align: center;
}
.kpi-label {
    font-size: 0.72rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #64748B;
    font-family: 'IBM Plex Mono', monospace;
    margin-bottom: 0.3rem;
}
.kpi-value {
    font-size: 1.9rem;
    font-weight: 800;
    color: #00D4AA;
    font-family: 'Syne', sans-serif;
    line-height: 1.1;
}
.kpi-sub {
    font-size: 0.75rem;
    color: #475569;
    margin-top: 0.2rem;
    font-family: 'IBM Plex Mono', monospace;
}

/* Empresa card en sidebar */
.empresa-header {
    font-size: 1.1rem;
    font-weight: 700;
    color: #00D4AA;
    margin-bottom: 0.1rem;
}
.empresa-rfc {
    font-size: 0.7rem;
    color: #64748B;
    font-family: 'IBM Plex Mono', monospace;
    letter-spacing: 0.08em;
}

/* Section headers */
h2, h3 { font-family: 'Syne', sans-serif !important; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #0D1117;
    border-right: 1px solid #1E2733;
}

/* Solana hash badge */
.hash-badge {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: #94A3B8;
    background: #111827;
    border: 1px solid #1E2733;
    border-radius: 6px;
    padding: 0.3rem 0.6rem;
    word-break: break-all;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Inicializar DB demo si no existe
# ---------------------------------------------------------------------------

if not DB_PATH.exists():
    with st.spinner("Inicializando base de datos demo..."):
        init_demo_db(DB_PATH)

# ---------------------------------------------------------------------------
# Sidebar — selector de empresa
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## ⚡ ArcFast Analytics")
    st.markdown("Portal del proveedor — Arca Continental")
    st.divider()

    empresas = get_empresas(DB_PATH)
    if not empresas:
        st.warning("No hay empresas registradas en la base de datos.")
        st.stop()

    nombres = {e["nombre"]: e for e in empresas}
    empresa_sel = st.selectbox(
        "Empresa cliente",
        options=list(nombres.keys()),
        format_func=lambda x: x,
    )
    empresa = nombres[empresa_sel]

    st.markdown(f"""
    <div class="empresa-header">{empresa['nombre']}</div>
    <div class="empresa-rfc">RFC: {empresa.get('rfc') or '—'}</div>
    """, unsafe_allow_html=True)

    st.divider()

    n_sim = st.select_slider(
        "Simulaciones Monte Carlo",
        options=[5_000, 10_000, 20_000, 50_000],
        value=20_000,
    )
    horizonte = st.slider("Horizonte de predicción (órdenes)", 3, 12, 6)

    st.divider()
    st.caption("Base de datos: `data/arcfast.db`")
    if st.button("🔄 Regenerar DB demo"):
        DB_PATH.unlink(missing_ok=True)
        init_demo_db(DB_PATH)
        st.rerun()


# ---------------------------------------------------------------------------
# Cargar historial de la empresa seleccionada
# ---------------------------------------------------------------------------

historial = get_historial(empresa["id"], DB_PATH)

if not historial:
    st.warning(f"No hay órdenes registradas para {empresa['nombre']}.")
    st.stop()

valores  = [h["valor_orden"] for h in historial]
missings = [h["missing"]     for h in historial]

# ---------------------------------------------------------------------------
# Header principal
# ---------------------------------------------------------------------------

st.markdown(f"## {empresa['nombre']}")
st.caption(f"Contacto: {empresa.get('contacto') or '—'}  ·  {len(historial)} órdenes registradas")

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

valor_promedio  = sum(valores) / len(valores)
tasa_missing    = sum(missings) / max(sum(h["total_productos"] for h in historial), 1) * 100
ultima_orden    = historial[-1]
ultima_fecha    = ultima_orden["fecha"]

# Monte Carlo rápido para KPI de pérdida anual
mc_kpi = estimar_impacto(
    valor_orden=ultima_orden["valor_orden"],
    n_missing=ultima_orden["missing"],
    historico_valores=valores,
    historico_missing=missings,
    n_simulaciones=n_sim,
)

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Valor promedio orden</div>
        <div class="kpi-value">${valor_promedio:,.0f}</div>
        <div class="kpi-sub">MXN</div>
    </div>""", unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Tasa missing products</div>
        <div class="kpi-value">{tasa_missing:.1f}%</div>
        <div class="kpi-sub">promedio histórico</div>
    </div>""", unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Pérdida anual estimada</div>
        <div class="kpi-value">${mc_kpi['perdida_anual_est']:,.0f}</div>
        <div class="kpi-sub">Monte Carlo IC 95%</div>
    </div>""", unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">Última orden</div>
        <div class="kpi-value">{ultima_fecha}</div>
        <div class="kpi-sub">${ultima_orden['valor_orden']:,.0f} · {ultima_orden['missing']} missing</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["📦 Historial", "🎲 Monte Carlo", "🔮 Predicción"])

# ── Tab 1: Historial ────────────────────────────────────────────────────────
with tab1:
    st.plotly_chart(
        graficar_historial(historial, empresa["nombre"]),
        use_container_width=True,
    )

    st.subheader("Detalle de órdenes")
    import pandas as pd
    df = pd.DataFrame(historial)
    df = df.rename(columns={
        "fecha":            "Fecha",
        "total_productos":  "Total productos",
        "missing":          "Missing",
        "valor_orden":      "Valor (MXN)",
        "solana_hash":      "Solana Hash",
    })
    df["Valor (MXN)"] = df["Valor (MXN)"].map("${:,.2f}".format)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Solana Hash": st.column_config.TextColumn(width="medium"),
        }
    )

    # Último hash on-chain
    if ultima_orden.get("solana_hash"):
        st.markdown("**Último audit trail Solana:**")
        st.markdown(
            f'<div class="hash-badge">{ultima_orden["solana_hash"]}</div>',
            unsafe_allow_html=True,
        )

# ── Tab 2: Monte Carlo ──────────────────────────────────────────────────────
with tab2:
    col_mc1, col_mc2 = st.columns([2, 1])

    with col_mc1:
        mc = estimar_impacto(
            valor_orden=ultima_orden["valor_orden"],
            n_missing=ultima_orden["missing"],
            historico_valores=valores,
            historico_missing=missings,
            n_simulaciones=n_sim,
        )
        st.plotly_chart(
            graficar_distribucion(mc, empresa["nombre"]),
            use_container_width=True,
        )

    with col_mc2:
        st.markdown("### Estadísticas")
        stats = {
            "Media":      mc["media"],
            "IC 2.5%":    mc["ic_low"],
            "IC 97.5%":   mc["ic_high"],
            "P10":        mc["p10"],
            "P25":        mc["p25"],
            "P75":        mc["p75"],
            "P90":        mc["p90"],
        }
        for label, val in stats.items():
            c1, c2 = st.columns([1, 1])
            c1.caption(label)
            c2.markdown(f"**${val:,.0f}**")

        st.divider()
        st.metric(
            "Pérdida anual proyectada",
            f"${mc['perdida_anual_est']:,.0f}",
            help="Media × 24 órdenes/año",
        )
        st.caption(f"Basado en {n_sim:,} simulaciones")

# ── Tab 3: Predicción ───────────────────────────────────────────────────────
with tab3:
    pred = predecir_proxima_orden(historial, n_simulaciones=n_sim, horizonte_ordenes=horizonte)

    st.plotly_chart(
        graficar_prediccion(pred, empresa["nombre"]),
        use_container_width=True,
    )

    st.subheader("Tabla de predicción")
    df_pred = pd.DataFrame({
        "Fecha":             pred["fechas"],
        "Valor predicho":    [f"${v:,.0f}" for v in pred["valor_media"]],
        "IC 5%":             [f"${v:,.0f}" for v in pred["valor_ic_low"]],
        "IC 95%":            [f"${v:,.0f}" for v in pred["valor_ic_high"]],
        "Missing estimado":  [f"{v:.1f}" for v in pred["missing_media"]],
    })
    st.dataframe(df_pred, use_container_width=True, hide_index=True)

    st.info(
        "La predicción usa **Bootstrap + Monte Carlo** sobre el historial real de la empresa. "
        "El intervalo de confianza al 90% refleja la variabilidad histórica de sus órdenes.",
        icon="ℹ️",
    )
