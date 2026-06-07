import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from grabador.grabador import Grabador
from cerebro.procesar import procesar_sesion
from agente.ejecutar import ejecutar


def pedir_credenciales(plan: dict) -> dict:
    credenciales = {}
    necesarias = plan.get("credenciales_necesarias", [])
    if not necesarias:
        return credenciales
    print("\n🔑 El bot necesita estos datos para ejecutar:")
    for item in necesarias:
        valor = input(f"  {item}: ").strip()
        credenciales[item] = valor
    return credenciales


async def main():
    print("\n" + "═"*55)
    print("  🏪  Hack4Her — Always on Shelf")
    print("  Arca Continental × Hack4Her 2026")
    print("═"*55)
    print()
    print("  Opciones:")
    print("  1. Grabar proceso nuevo")
    print("  2. Ejecutar proceso grabado")
    print()

    opcion = input("  Elige (1 o 2): ").strip()

    if opcion == "1":
        print("\n  Habla en voz alta explicando lo que haces.")
        print("  Ejecuta el proceso en tu browser normalmente.")
        print()
        input("  Presiona ENTER para iniciar la grabación...")

        g = Grabador()
        g.iniciar()
        input()
        sesion = g.detener()

        plan = procesar_sesion(sesion["eventos"], sesion["audio_path"])

        print("\n¿Quieres ejecutar el proceso ahora? (s/n): ", end="")
        if input().strip().lower() != "s":
            print("  Plan guardado. Corre de nuevo y elige opción 2.")
            return

    elif opcion == "2":
        plan_path = Path("sesiones/plan.json")
        if not plan_path.exists():
            print("  ❌ No hay plan guardado. Graba primero (opción 1).")
            return
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        print(f"\n  📋 Plan: {plan.get('objetivo')}")
        print(f"     Plataforma: {plan.get('plataforma')}")
        print(f"     Pasos: {len(plan.get('pasos', []))}")
    else:
        print("  Opción inválida.")
        return

    credenciales = pedir_credenciales(plan)
    email = input("\n  📧 Email para el reporte: ").strip()

    resultados = await ejecutar(plan, credenciales, email)

    ok = sum(1 for r in resultados if r["estado"] == "ok")
    print(f"\n  ✅ Completado: {ok}/{len(resultados)} pasos exitosos")


if __name__ == "__main__":
    asyncio.run(main())