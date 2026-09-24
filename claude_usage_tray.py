"""
Claude Usage Tray - Monitor de uso de Claude para la bandeja del sistema de Windows.

Muestra en el icono el % consumido de la sesión actual (ventana de 5 h) y, en el
menú, el detalle de la sesión y del límite semanal, con lo restante y la hora de
reinicio.

AVISO: usa el endpoint interno que alimenta la página Ajustes > Uso de claude.ai.
No es una API pública ni documentada: puede cambiar o dejar de funcionar sin aviso.

Requisitos:  pip install pystray pillow curl_cffi
Ejecutar:    pythonw claude_usage_tray.py   (sin ventana de consola)
"""

import json
import os
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import pystray
from curl_cffi import requests
from PIL import Image, ImageDraw, ImageFont

APP_NAME = "ClaudeUsageTray"
CONFIG_PATH = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME / "config.json"
BASE_URL = "https://claude.ai/api"
USAGE_PAGE = "https://claude.ai/settings/usage"
REFRESH_SECONDS = 60
ALERT_THRESHOLDS = (80, 95)  # % de la sesión en los que se muestra una notificación

# Claves conocidas de la respuesta y su etiqueta en pantalla
LIMITS = [
    ("five_hour", "Sesión actual (5 h)"),
    ("seven_day", "Semanal (todos los modelos)"),
    ("seven_day_opus", "Semanal (Opus)"),
    ("seven_day_sonnet", "Semanal (Sonnet)"),
]


# ---------------------------------------------------------------- configuración
def load_config() -> dict:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps({"session_key": "", "org_id": ""}, indent=2), encoding="utf-8"
        )
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    # La variable de entorno tiene prioridad sobre el archivo
    cfg["session_key"] = os.environ.get("CLAUDE_SESSION_KEY") or cfg.get("session_key", "")
    return cfg


def save_org_id(org_id: str) -> None:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["org_id"] = org_id
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- cliente
class ClaudeClient:
    def __init__(self, session_key: str, org_id: str = ""):
        # impersonate="chrome" evita que Cloudflare bloquee la petición
        self.session = requests.Session(impersonate="chrome")
        self.session.cookies.set("sessionKey", session_key, domain="claude.ai")
        self.org_id = org_id

    def _get(self, path: str):
        r = self.session.get(BASE_URL + path, timeout=20, headers={"Accept": "application/json"})
        if r.status_code in (401, 403):
            raise PermissionError("sessionKey no válida o caducada")
        r.raise_for_status()
        return r.json()

    def _resolve_org(self) -> str:
        orgs = self._get("/organizations")
        # Preferimos la organización con capacidad de chat (la de claude.ai)
        chosen = next((o for o in orgs if "chat" in (o.get("capabilities") or [])), orgs[0])
        save_org_id(chosen["uuid"])
        return chosen["uuid"]

    def usage(self) -> dict:
        if not self.org_id:
            self.org_id = self._resolve_org()
        return self._get(f"/organizations/{self.org_id}/usage")


# ---------------------------------------------------------------- utilidades
def time_until(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        target = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    secs = int((target - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "ya"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} d {h} h"
    return f"{h} h {m} min" if h else f"{m} min"


def color_for(pct: float) -> tuple:
    if pct < 50:
        return (46, 160, 67)    # verde
    if pct < 80:
        return (219, 154, 4)    # ámbar
    return (207, 34, 46)        # rojo


def make_icon(pct: float | None) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bg = (110, 110, 110) if pct is None else color_for(pct)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=14, fill=bg)
    text = "?" if pct is None else str(min(int(round(pct)), 100))
    font_size = 34 if len(text) < 3 else 26
    try:
        font = ImageFont.truetype("segoeuib.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), text, font=font)
    x = (size - (box[2] - box[0])) / 2 - box[0]
    y = (size - (box[3] - box[1])) / 2 - box[1]
    draw.text((x, y), text, fill="white", font=font)
    return img


# ---------------------------------------------------------------- aplicación
class TrayApp:
    def __init__(self):
        self.cfg = load_config()
        self.client = ClaudeClient(self.cfg["session_key"], self.cfg.get("org_id", ""))
        self.lines: list[str] = ["Cargando…"]
        self.last_update = "—"
        self.alerted: set[int] = set()
        self.stop_event = threading.Event()
        self.icon = pystray.Icon(
            APP_NAME, make_icon(None), "Claude: cargando…", menu=pystray.Menu(self._menu_items)
        )

    def _menu_items(self):
        for line in self.lines:
            yield pystray.MenuItem(line, None, enabled=False)
        yield pystray.MenuItem(f"Actualizado: {self.last_update}", None, enabled=False)
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Actualizar ahora", lambda: self.refresh(), default=True)
        yield pystray.MenuItem("Abrir página de uso", lambda: webbrowser.open(USAGE_PAGE))
        yield pystray.MenuItem("Editar configuración", lambda: os.startfile(CONFIG_PATH))
        yield pystray.MenuItem("Salir", self.quit)

    def refresh(self):
        if not self.client.session.cookies.get("sessionKey"):
            self._show_error(f"Falta sessionKey en {CONFIG_PATH}")
            return
        try:
            data = self.client.usage()
        except PermissionError as e:
            self._show_error(str(e))
            return
        except Exception as e:  # red, Cloudflare, cambio de formato…
            self._show_error(f"Error: {type(e).__name__}")
            return

        lines, session_pct = [], None
        for key, label in LIMITS:
            block = data.get(key)
            if not block or block.get("utilization") is None:
                continue
            used = float(block["utilization"])
            left = max(0.0, 100.0 - used)
            lines.append(
                f"{label}: {used:.0f}% usado · {left:.0f}% restante · "
                f"reinicia en {time_until(block.get('resets_at'))}"
            )
            if key == "five_hour":
                session_pct = used

        self.lines = lines or ["Sin datos de uso disponibles"]
        self.last_update = datetime.now().strftime("%H:%M:%S")
        self.icon.icon = make_icon(session_pct)
        if session_pct is not None:
            # El tooltip de Windows admite ~127 caracteres
            self.icon.title = f"Claude · sesión {session_pct:.0f}% usado, {100 - session_pct:.0f}% restante"
            self._maybe_alert(session_pct)
        else:
            self.icon.title = "Claude · uso"
        self.icon.update_menu()

    def _maybe_alert(self, pct: float):
        if pct < min(ALERT_THRESHOLDS):
            self.alerted.clear()  # nueva sesión: rearmar avisos
            return
        for t in ALERT_THRESHOLDS:
            if pct >= t and t not in self.alerted:
                self.alerted.add(t)
                try:
                    self.icon.notify(f"Has usado el {pct:.0f}% de la sesión actual.", "Claude")
                except Exception:
                    pass

    def _show_error(self, msg: str):
        self.lines = [msg]
        self.last_update = datetime.now().strftime("%H:%M:%S")
        self.icon.icon = make_icon(None)
        self.icon.title = f"Claude · {msg}"[:127]
        self.icon.update_menu()

    def _loop(self):
        while not self.stop_event.is_set():
            self.refresh()
            self.stop_event.wait(REFRESH_SECONDS)

    def _setup(self, icon):
        icon.visible = True
        threading.Thread(target=self._loop, daemon=True).start()

    def quit(self):
        self.stop_event.set()
        self.icon.stop()

    def run(self):
        self.icon.run(setup=self._setup)


if __name__ == "__main__":
    TrayApp().run()
