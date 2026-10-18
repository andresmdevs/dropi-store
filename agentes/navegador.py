"""Navegador con sesión propia para cada sitio (Dropi y Facebook).

Cada sitio tiene su perfil persistente en agentes/data/navegador-<sitio>, así la
sesión sobrevive entre corridas. Un candado por perfil evita que dos procesos
(cotizador, publicador, reconexión) abran el mismo perfil a la vez.
"""
from __future__ import annotations

import contextlib
import fcntl
import subprocess
import sys

from comun import DATOS, ahora, escribir_json, leer_json

SITIOS = {
    "dropi": {"inicio": "https://app.dropi.co/dashboard/search", "login": "https://app.dropi.co/auth/login"},
    "facebook": {"inicio": "https://www.facebook.com/marketplace/you/selling", "login": "https://www.facebook.com/login"},
}
SESIONES = DATOS / "sesiones.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/148.0.0.0 Safari/537.36")
SEC_CH_UA = '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="24"'


def perfil(sitio: str):
    return DATOS / f"navegador-{sitio}"


def marcar_sesion(sitio: str, ok: bool, detalle: str = "") -> None:
    datos = leer_json(SESIONES, {}) or {}
    datos[sitio] = {"ok": ok, "cuando": ahora(), "detalle": detalle[:200]}
    escribir_json(SESIONES, datos)


def estado_sesion(sitio: str) -> dict:
    return (leer_json(SESIONES, {}) or {}).get(sitio) or {"ok": None, "cuando": None, "detalle": "Nunca conectada"}


class Ocupado(Exception):
    pass


@contextlib.contextmanager
def abrir(p, sitio: str, visible: bool, esperar: bool = False):
    """Abre el perfil del sitio. Lanza Ocupado si otro proceso lo tiene abierto."""
    carpeta = perfil(sitio)
    carpeta.mkdir(parents=True, exist_ok=True)
    candado = open(DATOS / f"navegador-{sitio}.lock", "w")
    try:
        fcntl.flock(candado, fcntl.LOCK_EX | (0 if esperar else fcntl.LOCK_NB))
    except BlockingIOError as e:
        raise Ocupado(f"El navegador de {sitio} está en uso por otro proceso") from e
    opciones = dict(
        headless=not visible,
        viewport={"width": 1280, "height": 860},
        locale="es-CO",
        # Sin esto Chromium invisible se presenta como «HeadlessChrome» y el firewall de
        # Dropi responde 403 a todo.
        user_agent=UA,
        extra_http_headers={"sec-ch-ua": SEC_CH_UA},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    try:
        try:
            ctx = p.chromium.launch_persistent_context(str(carpeta), **opciones)
        except Exception as e:  # noqa: BLE001
            if "Executable doesn't exist" not in str(e):
                raise
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            ctx = p.chromium.launch_persistent_context(str(carpeta), **opciones)
        try:
            yield ctx
        finally:
            ctx.close()
    finally:
        fcntl.flock(candado, fcntl.LOCK_UN)
        candado.close()


def pagina(ctx):
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def dropi_conectado(page) -> bool:
    url = page.url
    return "app.dropi.co" in url and "login" not in url and "auth" not in url


def facebook_conectado(ctx) -> bool:
    return any(c["name"] == "c_user" for c in ctx.cookies("https://www.facebook.com"))
