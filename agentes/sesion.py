"""Reconecta la sesión de Dropi del navegador de los agentes.

    uv run --with playwright==1.60.0 python agentes/sesion.py

Abre una ventana con el perfil del agente en Dropi. Si la sesión sigue viva la
deja abierta unos segundos para que lo veas y avisa; si no, esperas a iniciar
sesión (hasta 10 minutos). Al final avisa con una notificación de macOS.

Los agentes necesitan su propio perfil: Chrome no deja que un programa maneje
el perfil con el que tú navegas.
"""
from __future__ import annotations

import subprocess
import sys
import time

import navegador
from navegador import SITIOS


def avisar(texto: str) -> None:
    subprocess.run(["/usr/bin/osascript", "-e", f'display notification "{texto}" with title "Monkey Agentes"'],
                   capture_output=True)


def reconectar() -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p, navegador.abrir(p, "dropi", visible=True, esperar=True) as ctx:
        autenticado = {"ok": False}

        def al_responder(r):
            if "api.dropi.co/api" in r.url and r.status == 200 and r.request.headers.get("x-authorization"):
                autenticado["ok"] = True

        ctx.on("response", al_responder)
        page = navegador.pagina(ctx)
        page.goto(SITIOS["dropi"]["inicio"])
        page.wait_for_timeout(6000)  # deja cargar el panel antes de decidir
        ya_estaba = autenticado["ok"] and navegador.dropi_conectado(page)
        limite = time.time() + 600
        while time.time() < limite:
            try:
                page = ctx.pages[-1]
            except IndexError:
                break  # cerraste la ventana
            if autenticado["ok"] and navegador.dropi_conectado(page):
                navegador.marcar_sesion("dropi", True, "Reconectada desde el panel")
                avisar("La sesión de Dropi ya estaba activa ✅" if ya_estaba else "Sesión de Dropi conectada ✅")
                page.wait_for_timeout(5000)
                print("✅ Sesión de Dropi conectada")
                return True
            time.sleep(2)
    navegador.marcar_sesion("dropi", False, "No se completó el inicio de sesión")
    avisar("No se detectó la sesión de Dropi")
    print("⚠️  No se detectó la sesión de Dropi")
    return False


if __name__ == "__main__":
    sys.exit(0 if reconectar() else 1)
