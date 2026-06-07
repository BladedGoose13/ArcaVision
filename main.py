"""
main.py — CLI de ArcFast
--------------------------
Corre con: python main.py
Modo web:  uvicorn backend.api:app --reload --port 8000
"""

import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from grabador.grabador import Grabador
from cerebro.procesar import procesar_sesion
from browser_agent.agent import ejecutar


def pedir_credenciales(plan: dict) -> dict:
    credenciales = {}
    necesarias = plan.get("credenciales_necesarias", [])
    if not necesarias:
        return credenciales
    print("\n🔑 El agente necesita estos datos para ejecutar:")
    for item in necesarias:
        es_pass = any(w in item.lower() for w in ["password","contraseña","clave","pass"])
        if es_pass:
            import getpass
            valor = getpass.getpass(f"  {item}: ")
        else:
            valor = input(f"  {item}: ").strip()
        credenciales[item] = valor
    return credenciales


async def main():
    print("\n" + "═"*55)
    print("  ⚡  ArcFast — Arca Continental")
    print("  Automatización de órdenes de compra")
    print("═"*55)
    print()
    print("  Opciones:")
    print("  1. Grabar proceso nuevo")
    print("  2. Ejecutar proceso guardado")
    print("  3. Ver historial (SQLite)")
    print()

    opcion = input("  Elige (1/2/3): ").strip()

    if opcion == "1":
        print("\n  Habla en voz alta explicando lo que haces.")
        print("  Ejecuta el proceso en tu browser normalmente.")
        print()
        input("  Presiona ENTER para iniciar la grabación...")

        g = Grabador()
        g.iniciar()
        input()  # esperar ENTER para detener
        sesion = g.detener()

        plan = procesar_sesion(sesion["eventos"], sesion["audio_path"])

        print("\n¿Quieres ejecutar el proceso ahora? (s/n): ", end="")
        if input().strip().lower() != "s":
            print("  Plan guardado en sesiones/plan.json — corre de nuevo y elige opción 2.")
            return

    elif opcion == "2":
        plan_path = Path("sesiones/plan.json")
        if not plan_path.exists():
            print("  ❌ No hay plan guardado. Graba primero (opción 1).")
            return
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        print(f"\n  📋 Plan cargado: {plan.get('objetivo')}")
        print(f"     Origen → Destino: {plan.get('plataforma_origen')} → {plan.get('plataforma_destino')}")
        print(f"     Pasos: {len(plan.get('pasos', []))}")

    elif opcion == "3":
        try:
            from database.db import obtener_historial, obtener_estadisticas
            stats = obtener_estadisticas()
            print(f"\n  📊 Estadísticas generales:")
            print(f"     Sesiones totales : {stats['total_sesiones']}")
            print(f"     Tasa de éxito    : {stats['tasa_exito_pct']}%")
            print(f"     Planes activos   : {stats['planes_activos']}")
            print(f"\n  📋 Últimas 10 sesiones:")
            for s in obtener_historial(10):
                print(f"     {s['fecha'][:16]}  {s.get('plataforma_origen','?')} → {s.get('plataforma_destino','?')}  {s['n_exitosos']}/{s['n_pasos']} ok")
        except Exception as e:
            print(f"  ❌ Error leyendo SQLite: {e}")
        return

    else:
        print("  Opción inválida.")
        return

    credenciales = pedir_credenciales(plan)
    email = input("\n  📧 Email para el reporte (Enter para omitir): ").strip()

    resultados = await ejecutar(plan, credenciales, email)

    ok = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\n  ✅ Completado: {ok}/{len(resultados)} pasos exitosos")

    # Guardar historial Excel
    try:
        from postprocessing.reporte import agregar_al_historial_excel
        from datetime import datetime
        agregar_al_historial_excel({
            "objetivo": plan.get("objetivo",""),
            "origen":   plan.get("plataforma_origen",""),
            "destino":  plan.get("plataforma_destino",""),
            "resultados": resultados,
            "fecha":    datetime.now().isoformat(),
        })
        print("  📊 Historial Excel actualizado: reportes/historial_arca.xlsx")
    except Exception as e:
        print(f"  ⚠️  Historial Excel: {e}")


if __name__ == "__main__":
    asyncio.run(main())
