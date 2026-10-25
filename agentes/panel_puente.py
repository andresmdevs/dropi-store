"""Publica estado mínimo del Mac y procesa acciones remotas allowlisted."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

AGENTES = Path(__file__).resolve().parent
RAIZ = AGENTES.parent
DATOS = AGENTES / "data"
LATIDOS = Path.home() / ".llm-panel" / "actividad"
ENV_LOCAL = RAIZ / ".env.local"
CONFIG = json.loads((AGENTES / "config.json").read_text())
LABEL = "com.andresmo.dropi-agentes"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
INTERVALO = 10


def _configuracion() -> tuple[str, str]:
    valores = {
        "INTERACCIONES_QUEUE_URL": os.environ.get("INTERACCIONES_QUEUE_URL", ""),
        "INTERACCIONES_QUEUE_TOKEN": os.environ.get("INTERACCIONES_QUEUE_TOKEN", ""),
    }
    try:
        for linea in ENV_LOCAL.read_text().splitlines():
            if "=" not in linea or linea.lstrip().startswith("#"):
                continue
            clave, valor = linea.split("=", 1)
            clave = clave.strip()
            if clave in valores and not valores[clave]:
                valores[clave] = valor.strip().strip("'\"")
    except OSError:
        pass
    url = valores["INTERACCIONES_QUEUE_URL"].rstrip("/")
    token = valores["INTERACCIONES_QUEUE_TOKEN"].strip()
    if not url.startswith("https://") or len(token) < 32:
        raise RuntimeError("Configura la URL y el token de cola remota en .env.local")
    return url, token


def _llamar(url: str, token: str, ruta: str, datos: dict | None = None):
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    req = urllib.request.Request(url + ruta, data=cuerpo, method="POST" if cuerpo is not None else "GET",
                                headers={"X-Queue-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 204:
                return None
            if response.status != 200:
                raise RuntimeError(f"Render respondió HTTP {response.status}")
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 204:
            return None
        raise RuntimeError(f"Render respondió HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("No se pudo consultar el panel remoto") from exc


def _leer_latidos() -> list[dict]:
    agentes = []
    ahora = datetime.now().astimezone()
    for archivo in LATIDOS.glob("*.json"):
        try:
            datos = json.loads(archivo.read_text())
            if datos.get("proyecto") != "dropi-store":
                continue
            actualizado = datetime.fromisoformat(datos["actualizado"])
            edad = max(0, int((ahora - actualizado).total_seconds()))
            estado = datos.get("estado", "desconocido")
            if edad > 900 and estado == "trabajando":
                estado = "sin señal"
            agentes.append({
                "agente": str(datos.get("agente") or archivo.stem)[:80],
                "modelo": str(datos.get("modelo") or "")[:160],
                "estado": estado if estado in (
                    "trabajando", "esperando", "bloqueado", "detenido", "caído", "sin señal", "iniciando"
                ) else "desconocido",
                "tarea": str(datos.get("tarea") or "")[:300],
                "actualizado": actualizado.isoformat(timespec="seconds"),
                "edad_s": edad,
            })
        except (OSError, ValueError, TypeError):
            continue
    return sorted(agentes, key=lambda agente: agente["agente"])


def _servicio() -> str:
    try:
        result = subprocess.run(
            ["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            capture_output=True, timeout=4, check=False)
        if result.returncode == 0:
            return "corriendo"
        if b"Could not find service" in result.stderr or b"service not found" in result.stderr:
            return "detenido"
        return "desconocido"
    except (OSError, subprocess.TimeoutExpired):
        return "desconocido"


def _estado() -> dict:
    url = CONFIG.get("ollama_url", "http://localhost:11434").rstrip("/")
    modelos: list[str] = []
    ollama = False
    try:
        req = urllib.request.Request(url + "/api/ps", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as response:
            datos = json.loads(response.read())
        modelos = sorted({
            str(modelo.get("name", ""))[:160]
            for modelo in datos.get("models", [])
            if isinstance(modelo, dict) and isinstance(modelo.get("name"), str)
        })
        ollama = True
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    return {"servicio": _servicio(), "ollama": ollama, "modelos": modelos, "agentes": _leer_latidos()}


def _ejecutar(accion: str) -> tuple[str, str | None]:
    if accion not in ("iniciar", "detener"):
        return "fallido", "Acción no permitida"
    uid = os.getuid()
    destino = f"gui/{uid}/{LABEL}"
    try:
        if accion == "iniciar":
            if not PLIST.is_file():
                return "fallido", "Instala primero los agentes en este Mac"
            estado = subprocess.run(["/bin/launchctl", "print", destino],
                                    capture_output=True, timeout=4, check=False)
            if estado.returncode == 0:
                return "completado", "Los agentes ya estaban iniciados"
            resultado = subprocess.run(
                ["/bin/launchctl", "bootstrap", f"gui/{uid}", str(PLIST)],
                capture_output=True, text=True, timeout=10, check=False)
        else:
            resultado = subprocess.run(
                ["/bin/launchctl", "bootout", destino],
                capture_output=True, text=True, timeout=10, check=False)
            if resultado.returncode != 0:
                estado = subprocess.run(["/bin/launchctl", "print", destino],
                                        capture_output=True, timeout=4, check=False)
                if estado.returncode != 0:
                    return "completado", "Los agentes ya estaban detenidos"
        if resultado.returncode != 0:
            return "fallido", "launchd no pudo completar la acción"
        return "completado", None
    except (OSError, subprocess.TimeoutExpired):
        return "fallido", "No se pudo completar la acción en este Mac"


def _procesar_comando(url: str, token: str) -> None:
    comando = _llamar(url, token, "/internal/panel/claim")
    if not comando:
        return
    estado, detalle = _ejecutar(comando.get("accion", ""))
    _llamar(url, token, "/internal/panel/complete", {
        "id": comando.get("id"), "estado": estado, "detalle": detalle,
    })


def ejecutar() -> None:
    ultimo_error = 0.0
    proximo_latido = 0.0
    while True:
        try:
            url, token = _configuracion()
            ahora = time.monotonic()
            if ahora >= proximo_latido:
                _llamar(url, token, "/internal/panel/heartbeat", _estado())
                proximo_latido = ahora + 30
            _procesar_comando(url, token)
            ultimo_error = 0.0
        except (OSError, RuntimeError, ValueError) as exc:
            ahora = time.monotonic()
            if not ultimo_error or ahora - ultimo_error >= 300:
                print(f"Panel remoto sin conexión: {exc}", flush=True)
                ultimo_error = ahora
        time.sleep(INTERVALO)


if __name__ == "__main__":
    ejecutar()
