"""
frontend/monte_carlo.py  —  PERSONA 4
----------------------------------------
Estimación de impacto económico de missing products
usando simulación Monte Carlo sobre datos históricos.

Diferenciador IFI — física estadística aplicada a negocio.
"""

import numpy as np


def estimar_impacto(
    valor_orden: float,
    n_missing: int,
    historico_valores: list[float],
    n_simulaciones: int = 10_000,
    semilla: int = 42,
) -> dict:
    """
    Corre N simulaciones Monte Carlo para estimar el impacto económico
    de los missing products en el contexto histórico de la empresa.

    Args:
        valor_orden:       Valor en MXN de la orden actual
        n_missing:         Número de productos faltantes detectados
        historico_valores: Lista de valores de órdenes históricas (MXN)
        n_simulaciones:    Número de iteraciones Monte Carlo

    Returns:
        dict con media, IC 95% inferior y superior, y percentiles
    """
    rng = np.random.default_rng(semilla)

    media_hist   = np.mean(historico_valores)
    std_hist     = np.std(historico_valores)
    ratio_missing = n_missing / max(len(historico_valores), 1)

    # Simulamos el impacto como fracción del valor de la orden
    # con ruido calibrado al histórico de la empresa
    impactos = rng.normal(
        loc=valor_orden * ratio_missing,
        scale=std_hist * ratio_missing,
        size=n_simulaciones,
    )
    impactos = np.abs(impactos)   # El impacto siempre es positivo

    ic_low  = np.percentile(impactos, 2.5)
    ic_high = np.percentile(impactos, 97.5)

    return {
        "media":    float(np.mean(impactos)),
        "ic_low":   float(ic_low),
        "ic_high":  float(ic_high),
        "p25":      float(np.percentile(impactos, 25)),
        "p75":      float(np.percentile(impactos, 75)),
        "n_sim":    n_simulaciones,
        "samples":  impactos.tolist()[:500],   # muestra para el histograma
    }


def graficar_distribucion(resultado: dict):
    """
    Devuelve una figura Plotly lista para st.plotly_chart().
    Muestra la distribución Monte Carlo con el IC 95% sombreado.
    """
    import plotly.graph_objects as go
    import plotly.figure_factory as ff

    samples = resultado["samples"]
    media   = resultado["media"]
    ic_low  = resultado["ic_low"]
    ic_high = resultado["ic_high"]

    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=samples,
        nbinsx=40,
        name="Simulaciones",
        marker_color="#7F77DD",
        opacity=0.7,
    ))

    fig.add_vline(x=media,   line_dash="solid", line_color="#534AB7",
                  annotation_text=f"Media ${media:,.0f}", annotation_position="top right")
    fig.add_vline(x=ic_low,  line_dash="dash",  line_color="#E24B4A",
                  annotation_text=f"IC 2.5%", annotation_position="top left")
    fig.add_vline(x=ic_high, line_dash="dash",  line_color="#E24B4A",
                  annotation_text=f"IC 97.5%")

    fig.add_vrect(x0=ic_low, x1=ic_high,
                  fillcolor="#534AB7", opacity=0.08, line_width=0)

    fig.update_layout(
        title="Distribución Monte Carlo — Impacto económico de missing products",
        xaxis_title="Impacto estimado (MXN)",
        yaxis_title="Frecuencia",
        showlegend=False,
        height=360,
        margin=dict(t=50, b=40, l=40, r=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig
