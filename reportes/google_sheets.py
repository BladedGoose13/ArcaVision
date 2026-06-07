import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from pathlib import Path

SHEET_ID = "1C3n7x8YgWP59L4lMHFFngvNgsNyBC99rsHr07T3CUos"
CREDENCIALES = "google_credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def conectar():
    creds = Credentials.from_service_account_file(CREDENCIALES, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    return sheet


def inicializar_headers(sheet):
    if sheet.row_count == 0 or sheet.cell(1, 1).value != "Fecha":
        headers = ["Fecha", "Comercio", "Cliente", "CP", "Productos", "Subtotal", "Impuestos", "Total", "Envio"]
        sheet.append_row(headers)


def agregar_a_sheets(datos: dict):
    try:
        sheet = conectar()
        inicializar_headers(sheet)

        fecha = datetime.fromisoformat(datos["fecha"]).strftime("%d/%m/%Y %H:%M")
        comercio = datos.get("objetivo", "Desconocido")[:40]
        productos_texto = ", ".join([
            f"{p['nombre']} (${p['precio']:.2f})"
            for p in datos["productos"]
        ])

        sheet.append_row([
            fecha,
            comercio,
            datos["cliente"],
            datos["zip"],
            productos_texto,
            datos["subtotal"],
            datos["impuestos"],
            datos["total"],
            datos["envio"],
        ])

        print(f"  📊 Google Sheets actualizado")
        return True

    except Exception as e:
        print(f"  ⚠️  Google Sheets no disponible: {e}")
        return False