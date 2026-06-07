"""
scripts/test_correo.py
----------------------
Prueba de entrega de correo + cifrado, de punta a punta, SIN correr el agente.

Qué hace:
  1. Genera el Excel financiero (queda cifrado en reposo: compras_arcavision.xlsx.enc)
  2. Envía el ticket por email a DESTINO usando tus credenciales del .env
  3. Imprime si el envío fue exitoso y si los datos quedaron cifrados

Uso (desde la raíz del repo, con tu .env configurado):
    python -m scripts.test_correo
    python -m scripts.test_correo otro_correo@gmail.com
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from postprocessing.reporte import generar_excel_compras, enviar_ticket, extraer_datos_pedido
from postprocessing.crypto import cifrado_disponible, esta_cifrado

DESTINO = sys.argv[1] if len(sys.argv) > 1 else "user.h4her@gmail.com"


def main():
    print("=" * 60)
    print("  ArcaVision — Prueba de correo + cifrado")
    print("=" * 60)

    # ── Diagnóstico de configuración ──────────────────────────────────────────
    remitente = os.getenv("EMAIL_REMITENTE", "").strip()
    password  = os.getenv("EMAIL_PASSWORD", "").strip()
    print(f"\n1) Configuración:")
    print(f"   EMAIL_REMITENTE : {remitente or '❌ NO definido'}")
    print(f"   EMAIL_PASSWORD  : {'✅ definido ('+str(len(password))+' chars)' if password else '❌ NO definido'}")
    print(f"   Cifrado activo  : {'✅ sí' if cifrado_disponible() else '❌ no (falta ARCAVISION_ENC_KEY)'}")
    print(f"   Destinatario    : {DESTINO}")

    if not remitente or not password:
        print("\n❌ Falta EMAIL_REMITENTE o EMAIL_PASSWORD en tu .env. No se puede enviar.")
        return
    if password and " " in password:
        print("   ⚠️  Tu EMAIL_PASSWORD tiene espacios. El App Password de Gmail va sin espacios.")

    # ── Datos de pedido de ejemplo ────────────────────────────────────────────
    datos_reporte = {
        "objetivo": "Prueba de captura de orden",
        "origen": "Portal cliente", "destino": "ARCA SAP",
        "productos": [
            {"nombre": "Coca-Cola 2L", "precio_unitario": 28.50, "cantidad": 48, "sku": "CC-2L"},
            {"nombre": "Sprite 600ml", "precio_unitario": 14.00, "cantidad": 24, "sku": "SP-600"},
        ],
        "resultados": [{"paso": 1, "accion": "click", "intencion": "login", "estado": "ok"}],
        "fecha": "2026-06-07T12:00:00", "motor": "browser_use", "iteraciones": 1,
    }

    # ── 2) Excel financiero (se cifra en reposo) ──────────────────────────────
    print(f"\n2) Generando Excel financiero…")
    excel_path = generar_excel_compras(datos_reporte)
    print(f"   Archivo en disco: {excel_path}")
    print(f"   ¿Cifrado en reposo? {'✅ sí (.enc)' if str(excel_path).endswith('.enc') else '⚠️ no'}")

    # ── 3) Envío del ticket ───────────────────────────────────────────────────
    print(f"\n3) Enviando ticket a {DESTINO}…")
    datos_pedido = extraer_datos_pedido("", datos_reporte)
    datos_pedido["productos"] = datos_reporte["productos"]
    datos_pedido["total"] = sum(p["precio_unitario"] * p["cantidad"] for p in datos_reporte["productos"])
    enviar_ticket(datos_pedido, datos_reporte, DESTINO, excel_path)

    enviado = datos_pedido.get("ticket_enviado")
    print("\n" + "=" * 60)
    if enviado:
        print(f"  ✅ CORREO ENVIADO a {DESTINO}")
        print(f"     Revisa la bandeja (y spam). Adjunto: Excel de compras.")
    else:
        print(f"  ❌ NO se envió. Revisa los mensajes de error arriba")
        print(f"     (causa común: App Password incorrecto o 2FA no activado).")
    print("=" * 60)


if __name__ == "__main__":
    main()
