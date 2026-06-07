import streamlit as st
import pandas as pd
import sqlite3
from pathlib import Path
from datetime import datetime

st.set_page_config(page_title="Arca Continental", page_icon="🏪", layout="wide")

st.markdown('<div style="background:#C00000;padding:20px;border-radius:8px;margin-bottom:20px"><h1 style="color:white;margin:0">🏪 Arca Continental — Centro de Pedidos</h1><p style="color:#ffcccc;margin:0">Always on Shelf · Hack4Her 2026</p></div>', unsafe_allow_html=True)

DB_PATH = "reportes/historial.db"

if not Path(DB_PATH).exists():
    st.warning("No hay pedidos aún.")
    st.stop()

conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query("SELECT * FROM pedidos ORDER BY id DESC", conn)
conn.close()

if df.empty:
    st.warning("No hay pedidos registrados aún.")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("📦 Pedidos", len(df))
col2.metric("💰 Total vendido", f"${df['total'].sum():,.2f}")
col3.metric("🏪 Comercios", df['comercio'].nunique())
col4.metric("👥 Clientes", df['cliente'].nunique())

st.divider()
st.subheader("📋 Historial de pedidos")
st.dataframe(df[["fecha","comercio","cliente","zip","productos","subtotal","impuestos","total","envio"]], use_container_width=True, hide_index=True)
st.caption(f"Última actualización: {datetime.now().strftime('%H:%M:%S')}")
if st.button("🔄 Actualizar"):
    st.rerun()
