import base64
import json
import os
import platform
import threading
import time
import wave
from datetime import datetime
from io import BytesIO
from pathlib import Path

import mss
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# Importar pynput con manejo de errores para Windows/Mac/Linux
try:
    from pynput import mouse, keyboard
    PYNPUT_OK = True
except Exception:
    PYNPUT_OK = False
    print("⚠️  pynput no disponible — grabación de clicks desactivada")

# Importar pyaudio con manejo de errores
try:
    import pyaudio
    PYAUDIO_OK = True
except Exception:
    PYAUDIO_OK = False
    print("⚠️  pyaudio no disponible — grabación de audio desactivada")


class Grabador:
    def __init__(self):
        self.eventos = []
        self.grabando = False
        self.carpeta = Path("sesiones")
        self.carpeta.mkdir(exist_ok=True)
        self.audio_frames = []
        self.stream_audio = None
        self._sistema = platform.system()  # Windows, Darwin, Linux

        if PYAUDIO_OK:
            self.audio = pyaudio.PyAudio()
        else:
            self.audio = None

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
        if not PYAUDIO_OK:
            return
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000
        try:
            self.stream_audio = self.audio.open(
                format=FORMAT, channels=CHANNELS,
                rate=RATE, input=True,
                frames_per_buffer=CHUNK
            )
            while self.grabando:
                data = self.stream_audio.read(CHUNK, exception_on_overflow=False)
                self.audio_frames.append(data)
        except Exception as e:
            print(f"  ⚠️  Error de audio: {e}")

    def iniciar(self):
        self.eventos = []
        self.audio_frames = []
        self.grabando = True

        if PYAUDIO_OK:
            self.hilo_audio = threading.Thread(target=self.grabar_audio, daemon=True)
            self.hilo_audio.start()

        if PYNPUT_OK:
            self.mouse_listener = mouse.Listener(on_click=self.on_click)
            self.keyboard_listener = keyboard.Listener(on_press=self.on_key)
            self.mouse_listener.start()
            self.keyboard_listener.start()

        print("🔴 GRABANDO — habla y ejecuta el proceso ahora")
        print("   Presiona ENTER cuando termines\n")

    def detener(self) -> dict:
        self.grabando = False

        if PYNPUT_OK:
            try:
                self.mouse_listener.stop()
                self.keyboard_listener.stop()
            except Exception:
                pass

        if self.stream_audio:
            try:
                self.stream_audio.stop_stream()
                self.stream_audio.close()
            except Exception:
                pass
            finally:
                self.stream_audio = None

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_path = self.carpeta / f"audio_{ts}.wav"

        if PYAUDIO_OK and self.audio_frames:
            with wave.open(str(audio_path), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(16000)
                wf.writeframes(b''.join(self.audio_frames))
        else:
            # Crear archivo WAV vacío si no hay audio
            with wave.open(str(audio_path), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b'')

        log_path = self.carpeta / f"eventos_{ts}.json"
        ligero = [{k: v for k, v in e.items() if k != "screenshot"} for e in self.eventos]
        with open(log_path, "w", encoding="utf-8") as f:
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
