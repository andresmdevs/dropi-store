"""Piezas compartidas por los agentes: rutas, config, estado en disco y cliente de Ollama.

Solo usa la biblioteca estándar, así launchd lo corre con el python3 del sistema.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

AGENTES = Path(__file__).resolve().parent
RAIZ = AGENTES.parent
DATOS = AGENTES / "data"
PRODUCTOS = DATOS / "productos"
LOGS = DATOS / "logs"
# El panel de LLMs lee los latidos de aquí, sin importar de qué proyecto vengan.
LATIDOS = Path.home() / ".llm-panel" / "actividad"

for d in (DATOS, PRODUCTOS, LOGS, LATIDOS):
    d.mkdir(parents=True, exist_ok=True)

CONFIG = json.loads((AGENTES / "config.json").read_text())


def ahora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def cargar_env() -> None:
    """Carga .env.local y .env del proyecto sin pisar lo que ya esté en el entorno."""
    for nombre in (".env.local", ".env"):
        ruta = RAIZ / nombre
        if not ruta.exists():
            continue
        for linea in ruta.read_text().splitlines():
            if "=" not in linea or linea.lstrip().startswith("#"):
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip().strip("'\""))


def leer_json(ruta: Path, defecto=None):
    try:
        return json.loads(ruta.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def escribir_json(ruta: Path, datos) -> None:
    """Escritura atómica: el panel nunca lee un archivo a medio escribir."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)


def log(agente: str, mensaje: str) -> None:
    linea = f"{ahora()} [{agente}] {mensaje}"
    print(linea, flush=True)
    with (LOGS / f"{datetime.now():%Y-%m-%d}.log").open("a") as f:
        f.write(linea + "\n")


class Latido:
    """Estado de un agente, publicado para el panel en ~/.llm-panel/actividad/."""

    def __init__(self, agente: str, modelo: str | None, rol: str):
        self.ruta = LATIDOS / f"{CONFIG['proyecto']}__{agente}.json"
        self.datos = {
            "proyecto": CONFIG["proyecto"],
            "carpeta": str(RAIZ),
            "agente": agente,
            "rol": rol,
            "modelo": modelo,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "estado": "iniciando",
            "tarea": "",
            "desde": ahora(),
            "actualizado": ahora(),
            "hechos_hoy": 0,
            "ultimo_error": None,
            "bloqueos": [],
            "resumen": {},
        }
        self._guardar()

    def _guardar(self) -> None:
        self.datos["actualizado"] = ahora()
        escribir_json(self.ruta, self.datos)

    def set(self, estado: str | None = None, tarea: str | None = None, **extra) -> None:
        if estado and estado != self.datos["estado"]:
            self.datos["desde"] = ahora()
            self.datos["estado"] = estado
        if tarea is not None:
            self.datos["tarea"] = tarea
        self.datos.update(extra)
        self._guardar()

    def bloqueos(self, lista: list[str]) -> None:
        self.datos["bloqueos"] = lista
        self._guardar()

    def hecho(self) -> None:
        self.datos["hechos_hoy"] += 1
        self._guardar()

    def error(self, mensaje: str) -> None:
        self.datos["ultimo_error"] = {"cuando": ahora(), "mensaje": mensaje[:500]}
        self._guardar()


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def _post(url: str, cuerpo: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(cuerpo).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ollama_vivo() -> bool:
    try:
        with urllib.request.urlopen(CONFIG["ollama_url"] + "/api/version", timeout=3):
            return True
    except OSError:
        return False


def chat_json(modelo: str, sistema: str, usuario: str, esquema: dict,
              imagenes: list[bytes] | None = None, timeout: int = 600) -> dict:
    """Pide al modelo una respuesta que cumpla `esquema` (salida estructurada de Ollama)."""
    mensaje = {"role": "user", "content": usuario}
    if imagenes:
        mensaje["images"] = [base64.b64encode(b).decode() for b in imagenes]
    cuerpo = {
        "model": modelo,
        "stream": False,
        "think": False,
        "keep_alive": CONFIG["keep_alive"],
        "format": esquema,
        "options": {"num_ctx": CONFIG["num_ctx"], "temperature": 0.5},
        "messages": [{"role": "system", "content": sistema}, mensaje],
    }
    url = CONFIG["ollama_url"] + "/api/chat"
    try:
        r = _post(url, cuerpo, timeout)
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")
        # Los modelos sin modo de razonamiento rechazan el campo "think".
        if e.code == 400 and "think" in detalle:
            cuerpo.pop("think")
            r = _post(url, cuerpo, timeout)
        else:
            raise RuntimeError(f"Ollama {e.code}: {detalle[:300]}") from e
    texto = r["message"]["content"].strip()
    if texto.startswith("```"):
        texto = texto.strip("`").removeprefix("json").strip()
    return json.loads(texto)


def hoy() -> str:
    return time.strftime("%Y-%m-%d")
