import asyncio
import json
import os
from datetime import datetime
from pathlib import 
from dotenv import load_dotenv

load_dotenv()


async def ejecutar(plan: dict, credenciales: dict, email_reporte: str):
    from browser_use import Agent
    from langchain_anthropic import ChatAnthropic

    todas = {**credenciales, **plan.get("credenciales_obtenidas", {})}
    objetivo = plan.get("objetivo", "Ejecutar el proceso aprendido")
    origen = plan.get("plataforma_origen", "")
    destino = plan.get("plataforma_destino", "")
    creds_texto = "\n".join([f"- {k}: {v}" for k, v in todas.items() if v])
    mapeo = plan.get("mapeo_campos", [])
    mapeo_texto = "\n".join([
        f"- '{m['campo_origen']}' en {origen} corresponde a '{m['campo_destino']}' en {destino}"
        for m in mapeo
    ]) if mapeo else "Aprende el mapeo observando la página"

    task = f"""
Eres un agente que automatiza procesos entre dos sistemas web.

OBJETIVO: {objetivo}

SISTEMAS:
- Origen: {origen}
- Destino: {destino}

CREDENCIALES DISPONIBLES:
{creds_texto if creds_texto else "Ninguna — infiere del contexto"}

MAPEO DE CAMPOS APRENDIDO:
{mapeo_texto}

INSTRUCCIONES:
1. Ejecuta el proceso completo de principio a fin
2. Si un elemento no está visible, haz scroll para encontrarlo
3. Si algo falla, intenta una alternativa antes de rendirte
4. Al terminar, extrae los datos más importantes del resultado
5. NO pares hasta completar el objetivo o agotar opciones razonables
"""

    print(f"\n🤖 Browser Use ejecutando: {objetivo}")
    print(f"   Sistemas: {origen} → {destino}\n")

    llm = ChatAnthropic(
        model="claude-opus-4-5",
        api_key=os.getenv("ANTHROPIC_API_KEY")
    )

    agent = Agent(task=task, llm=llm)

    try:
        result = await agent.run(max_steps=50)
        resultado_texto = str(result)
        print(f"\n✅ Browser Use completó el proceso")
    except Exception as e:
        resultado_texto = f"Error: {e}"
        print(f"\n❌ Error: {e}")

    reporte = {
        "objetivo": objetivo,
        "plataforma_origen": origen,
        "plataforma_destino": destino,
        "credenciales_usadas": list(todas.keys()),
        "resultado": resultado_texto,
        "fecha": datetime.now().isoformat()
    }

    Path("sesiones").mkdir(exist_ok=True)
    with open("sesiones/reporte.json", "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)

    print(f"  📄 Reporte: sesiones/reporte.json")

    try:
        import sys
        sys.path.insert(0, '.')
        from reportes.generar_reporte import generar_todo
        generar_todo(email_reporte)
    except Exception as e:
        print(f"  ⚠️  Error generando reporte: {e}")

    return [{"estado": "ok", "resultado": resultado_texto}]