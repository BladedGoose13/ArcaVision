"""
postprocessing/reporte.py
--------------------------
Generación de Excel y ticket HTML con los resultados del agente.
Se conecta directamente a la SQLite de ArcFast para leer historial.
"""

import json
import re
import os
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment


# ─── Excel ────────────────────────────────────────────────────────────────────

def generar_excel(datos: dict, output_path: str = "reportes/reporte_arcfast.xlsx") -> str:
    Path("reportes").mkdir(exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporte ArcFast"

    rojo       = PatternFill("solid", fgColor="C8102E")
    gris       = PatternFill("solid", fgColor="F2F2F2")
    gris_claro = PatternFill("solid", fgColor="FAFAFA")
    ok_fill    = PatternFill("solid", fgColor="E6F4EC")
    err_fill   = PatternFill("solid", fgColor="FDECEA")
    warn_fill  = PatternFill("solid", fgColor="FEF3E2")
    font_blanco = Font(bold=True, color="FFFFFF", size=13)
    font_bold   = Font(bold=True)
    centro      = Alignment(horizontal="center", vertical="center")

    # Título
    ws.row_dimensions[1].height = 32
    ws.merge_cells("A1:F1")
    ws["A1"] = "ARCFAST — ARCA CONTINENTAL — REPORTE DE EJECUCIÓN"
    ws["A1"].font  = font_blanco
    ws["A1"].fill  = rojo
    ws["A1"].alignment = centro

    # Metadata
    fecha = datetime.fromisoformat(datos.get("fecha", datetime.now().isoformat())).strftime("%d/%m/%Y %H:%M:%S")
    ws.merge_cells("A2:F2")
    ws["A2"] = (f"Proceso: {datos.get('objetivo','')}  |  "
                f"Origen: {datos.get('origen','')}  →  Destino: {datos.get('destino','')}  |  Fecha: {fecha}")
    ws["A2"].fill = gris
    ws["A2"].alignment = centro
    ws.append([])

    # Headers resultados
    headers = ["Paso", "Acción", "Estado", "Datos extraídos"]
    ws.append(headers)
    for col in range(1, 5):
        c = ws.cell(row=4, column=col)
        c.font = font_bold
        c.fill = gris
        c.alignment = centro

    # Filas de resultados
    resultados = datos.get("resultados", [])
    for i, r in enumerate(resultados, 5):
        estado = r.get("estado", "error")
        fill = ok_fill if estado == "ok" else err_fill if estado == "error" else warn_fill
        datos_ext = str(r.get("datos_extraidos", ""))[:200] if r.get("datos_extraidos") else "—"
        fila = [r.get("paso", ""), r.get("accion", ""), estado.upper(), datos_ext]
        ws.append(fila)
        for col in range(1, 5):
            ws.cell(row=i, column=col).fill = fill

    ws.append([])

    # Resumen
    ok    = sum(1 for r in resultados if r.get("estado") == "ok")
    total = len(resultados)
    fila_res = ws.max_row + 1
    ws.cell(row=fila_res, column=1, value="RESUMEN").font = font_bold
    ws.cell(row=fila_res, column=2, value=f"{ok}/{total} pasos exitosos").font = font_bold

    # ── Segunda hoja: historial desde SQLite ──────────────────────────────────
    try:
        from database.db import obtener_historial
        historial = obtener_historial(limit=30)
        if historial:
            ws2 = wb.create_sheet("Historial")
            ws2.merge_cells("A1:G1")
            ws2["A1"] = "HISTORIAL DE SESIONES — ARCFAST"
            ws2["A1"].font  = font_blanco
            ws2["A1"].fill  = rojo
            ws2["A1"].alignment = centro

            h2 = ["Fecha", "Usuario", "Empresa", "Origen", "Destino", "Pasos", "Exitosos", "Errores", "Duración"]
            ws2.append(h2)
            for col in range(1, len(h2)+1):
                c = ws2.cell(row=2, column=col)
                c.font = font_bold
                c.fill = gris

            for s in historial:
                ws2.append([
                    s.get("fecha", "")[:16],
                    s.get("email_usuario", ""),
                    s.get("empresa", ""),
                    s.get("plataforma_origen", ""),
                    s.get("plataforma_destino", ""),
                    s.get("n_pasos", 0),
                    s.get("n_exitosos", 0),
                    s.get("n_errores", 0),
                    f"{s.get('duracion_seg', 0):.1f}s" if s.get("duracion_seg") else "—",
                ])
            for col_dim in ["A","B","C","D","E","F","G","H","I"]:
                ws2.column_dimensions[col_dim].width = 22
    except Exception as e:
        print(f"  ⚠️  Historial SQLite no disponible: {e}")

    # Anchos hoja principal
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 60

    wb.save(output_path)
    return output_path


# ─── Ticket HTML ──────────────────────────────────────────────────────────────

def generar_ticket_html(datos: dict) -> str:
    """Genera un ticket HTML de confirmación del proceso ejecutado."""
    fecha    = datetime.fromisoformat(datos.get("fecha", datetime.now().isoformat())).strftime("%d/%m/%Y %H:%M")
    objetivo = datos.get("objetivo", "Proceso automatizado")
    origen   = datos.get("origen", "")
    destino  = datos.get("destino", "")

    resultados = datos.get("resultados", [])
    ok    = sum(1 for r in resultados if r.get("estado") == "ok")
    total = len(resultados)

    # Filas de pasos
    filas_pasos = ""
    for r in resultados:
        estado = r.get("estado", "error")
        color  = "#E6F4EC" if estado == "ok" else "#FDECEA" if estado == "error" else "#FEF3E2"
        icono  = "✅" if estado == "ok" else "❌" if estado == "error" else "⚠️"
        datos_ext = str(r.get("datos_extraidos", ""))[:100] if r.get("datos_extraidos") else ""
        filas_pasos += f"""
        <tr style="background:{color}">
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{r.get('paso','')}</td>
          <td style="padding:8px;border-bottom:1px solid #eee">{r.get('accion','')}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{icono} {estado.upper()}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;font-size:12px;color:#666">{datos_ext}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ArcFast — Reporte</title></head>
<body style="margin:0;background:#f5f5f5;font-family:'Segoe UI',Arial,sans-serif">
<div style="max-width:640px;margin:30px auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.1)">
  <div style="background:#C8102E;padding:28px;text-align:center">
    <h1 style="color:white;margin:0;font-size:22px;letter-spacing:1px">⚡ ArcFast</h1>
    <p style="color:#ffcccc;margin:6px 0 0;font-size:14px">Arca Continental · Reporte de ejecución</p>
  </div>
  <div style="padding:28px">
    <table style="width:100%;margin-bottom:20px">
      <tr><td style="color:#888;font-size:12px;text-transform:uppercase;letter-spacing:.5px">Proceso</td></tr>
      <tr><td style="font-size:16px;font-weight:600;color:#1a1a1a">{objetivo}</td></tr>
    </table>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:24px">
      <div style="background:#f9f9f9;border-radius:6px;padding:14px;text-align:center">
        <div style="font-size:11px;color:#888;text-transform:uppercase;margin-bottom:4px">Fecha</div>
        <div style="font-size:13px;font-weight:600">{fecha}</div>
      </div>
      <div style="background:#f9f9f9;border-radius:6px;padding:14px;text-align:center">
        <div style="font-size:11px;color:#888;text-transform:uppercase;margin-bottom:4px">Resultado</div>
        <div style="font-size:20px;font-weight:700;color:{'#1A7A45' if ok==total else '#C8102E'}">{ok}/{total}</div>
      </div>
      <div style="background:#f9f9f9;border-radius:6px;padding:14px;text-align:center">
        <div style="font-size:11px;color:#888;text-transform:uppercase;margin-bottom:4px">Flujo</div>
        <div style="font-size:12px;font-weight:600">{origen} → {destino}</div>
      </div>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f2f2f2">
          <th style="padding:8px;text-align:center;font-size:12px">#</th>
          <th style="padding:8px;text-align:left;font-size:12px">Acción</th>
          <th style="padding:8px;text-align:center;font-size:12px">Estado</th>
          <th style="padding:8px;text-align:left;font-size:12px">Datos</th>
        </tr>
      </thead>
      <tbody>{filas_pasos}</tbody>
    </table>
  </div>
  <div style="background:#f2f2f2;padding:14px;text-align:center;font-size:11px;color:#999">
    ArcFast · Arca Continental · Hack4Her 2026
  </div>
</div>
</body></html>"""


def guardar_ticket(html: str, output_path: str = "reportes/ticket.html") -> str:
    Path("reportes").mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


# ─── Historial en Excel acumulativo ──────────────────────────────────────────

HISTORIAL_PATH = "reportes/historial_arca.xlsx"

def agregar_al_historial_excel(datos: dict):
    """Agrega una fila al Excel de historial acumulativo."""
    Path("reportes").mkdir(exist_ok=True)

    rojo = PatternFill("solid", fgColor="C8102E")
    font_blanco = Font(bold=True, color="FFFFFF", size=11)
    centro = Alignment(horizontal="center")

    if Path(HISTORIAL_PATH).exists():
        wb = openpyxl.load_workbook(HISTORIAL_PATH)
        ws = wb.active
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Historial Pedidos"
        headers = ["Fecha", "Objetivo", "Origen", "Destino", "Pasos", "Exitosos", "Errores", "Motor"]
        ws.append(headers)
        for col in range(1, len(headers)+1):
            c = ws.cell(row=1, column=col)
            c.font = font_blanco
            c.fill = rojo
            c.alignment = centro
        for ltr in ["A","B","C","D"]:
            ws.column_dimensions[ltr].width = 24

    resultados = datos.get("resultados", [])
    ok  = sum(1 for r in resultados if r.get("estado") == "ok")
    err = sum(1 for r in resultados if r.get("estado") == "error")

    fecha = datetime.fromisoformat(datos.get("fecha", datetime.now().isoformat())).strftime("%d/%m/%Y %H:%M")
    ws.append([
        fecha,
        datos.get("objetivo", ""),
        datos.get("origen", ""),
        datos.get("destino", ""),
        len(resultados),
        ok,
        err,
        datos.get("motor", "playwright"),
    ])
    wb.save(HISTORIAL_PATH)
    return HISTORIAL_PATH
