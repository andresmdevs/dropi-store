"""Reconecta la sesión de Dropi o de Facebook del navegador de los agentes.

    uv run --with playwright==1.60.0 python agentes/sesion.py dropi
    uv run --with playwright==1.60.0 python agentes/sesion.py facebook

Abre una ventana con el perfil del agente. Inicias sesión como siempre (con tu
clave y tu código, si te lo pide); la ventana se cierra sola apenas detecta la
sesión, o a los 10 minutos.
"""
from __future__ import annotations

import sys
import time

import navegador
from navegador import SITIOS


def reconectar(sitio: str) -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p, navegador.abrir(p, sitio, visible=True, esperar=True) as ctx:
        page = navegador.pagina(ctx)
        page.goto(SITIOS[sitio]["inicio"])
        limite = time.time() + 600
        while time.time() < limite:
            try:
                page = ctx.pages[-1] if ctx.pages else page
                ok = navegador.facebook_conectado(ctx) if sitio == "facebook" else navegador.dropi_conectado(page)
            except Exception:  # noqa: BLE001  (la ventana se cerró)
                break
            if ok:
                page.wait_for_timeout(4000)  # deja que el sitio termine de guardar la sesión
                navegador.marcar_sesion(sitio, True, "Reconectada desde el panel")
                print(f"✅ Sesión de {sitio} conectada")
                return True
            time.sleep(2)
    navegador.marcar_sesion(sitio, False, "No se completó el inicio de sesión")
    print(f"⚠️  No se detectó la sesión de {sitio}")
    return False


if __name__ == "__main__":
    sitio = sys.argv[1] if len(sys.argv) > 1 else ""
    if sitio not in SITIOS:
        raise SystemExit(f"Uso: sesion.py {'|'.join(SITIOS)}")
    sys.exit(0 if reconectar(sitio) else 1)
