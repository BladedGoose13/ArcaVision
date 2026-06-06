import asyncio
import base64
import json
import os
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

import mss
import pyaudio
import wave
from PIL import Image
from pynput import mouse, keyboard
from dotenv import load_dotenv

load_dotenv()

class Grabador:
    def __init__(self):
        self.eventos = []
        self.grabando = False
        self.carpeta = Path("sesiones")
        self.carpeta.mkdir(exist_ok=True)
        self.ultimo_screenshot = 0
        self.COOLDOWN = 1.0
        
        # Audio
        self.audio_frames = []
        self.audio = pyaudio.PyAudio()
        self.stream_audio = None

    def capturar_screenshot(self) -> str:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            img.thumbnail((1280, 720))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=70)
            return base64.b64encode(buf.getvalue()).decode()

    def on_click(self, x, y, button, pressed):
        if not self.grabando or not pressed:
            return
        screenshot = self.capturar_screenshot()
        self.eventos.append({
            "tipo": "click",
            "x": x, "y": y,
            "timestamp": datetime.now().isoformat(),
            "screenshot": screenshot
        })
        print(f"  🖱  click ({x:.0f}, {y:.0f}) — {len(self.eventos)} eventos")

    def on_key(self, key):
        if not self.grabando:
            return
        try:
            char = key.char
        except AttributeError:
            char = str(key)
        self.eventos.append({
            "tipo": "tecla",
            "tecla": char,
            "timestamp": datetime.now().isoformat()
        })

    def grabar_audio(self):
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000
        self.stream_audio = self.audio.open(
            format=FORMAT, channels=CHANNELS,
            rate=RATE, input=True,
            frames_per_buffer=CHUNK
        )
        while self.grabando:
            data = self.stream_audio.read(CHUNK, exception_on_overflow=False)
            self.audio_frames.append(data)

    def iniciar(self):
        self.eventos = []
        self.audio_frames = []
        self.grabando = True

        # Iniciar audio en hilo separado
        self.hilo_audio = threading.Thread(target=self.grabar_audio, daemon=True)
        self.hilo_audio.start()

        # Iniciar listeners de mouse y teclado
        self.mouse_listener = mouse.Listener(on_click=self.on_click)
        self.keyboard_listener = keyboard.Listener(on_press=self.on_key)
        self.mouse_listener.start()
        self.keyboard_listener.start()

        print("🔴 GRABANDO — habla y ejecuta el proceso ahora")
        print("   Presiona ENTER cuando termines\n")

    def detener(self) -> dict:
        self.grabando = False
        self.mouse_listener.stop()
        self.keyboard_listener.stop()

        if self.stream_audio:
            self.stream_audio.stop_stream()
            self.stream_audio.close()

        # Guardar audio
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = self.carpeta / f"audio_{ts}.wav"
        with wave.open(str(audio_path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
            wf.setframerate(16000)
            wf.writeframes(b''.join(self.audio_frames))

        # Guardar eventos sin screenshots
        log_path = self.carpeta / f"eventos_{ts}.json"
        ligero = [{k: v for k, v in e.items() if k != "screenshot"} for e in self.eventos]
        with open(log_path, "w") as f:
            json.dump(ligero, f, indent=2, ensure_ascii=False)

        print(f"\n⏹  Detenido: {len(self.eventos)} eventos, audio guardado")
        print(f"   Audio: {audio_path}")

        return {
            "eventos": self.eventos,
            "audio_path": str(audio_path),
            "timestamp": ts
        }


if __name__ == "__main__":
    g = Grabador()
    g.iniciar()
    input()
    resultado = g.detener()
    print(f"\n✅ Sesión guardada con {len(resultado['eventos'])} eventos")