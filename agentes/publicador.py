"""Asistente de publicación en Facebook Marketplace.

    uv run --with playwright==1.60.0 python agentes/publicador.py --id 2099675

Abre Facebook con el perfil del agente, llena el formulario de Marketplace
(fotos, título, precio, categoría, estado y descripción) y te deja la ventana:
tú revisas y haces clic en «Siguiente» y «Publicar». Cuando Facebook confirma
la publicación, el producto pasa a «publicado» solo.

Códigos de salida: 0 publicado, 3 cerrado sin publicar, 4 sesión vencida,
5 navegador ocupado, 2 el formulario cambió (deja captura en data/capturas/).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import navegador
from comun import CONFIG, DATOS, PRODUCTOS, ahora, escribir_json, leer_json

CREAR = "https://www.facebook.com/marketplace/create/item"
FOTOS = DATOS / "fotos-fb"
CAPTURAS = DATOS / "capturas"

# Facebook muestra el formulario en el idioma de la cuenta.
TEXTOS = {
    "titulo": ["Título", "Title"],
    "precio": ["Precio", "Price"],
    "categoria": ["Categoría", "Category"],
    "estado": ["Estado", "Condition"],
    "descripcion": ["Descripción", "Description"],
    "nuevo": ["Nuevo", "New"],
}


class FormularioCambio(Exception):
    pass


def preparar_fotos(p: dict) -> list[str]:
    """Fotos en JPG (Facebook no siempre acepta WebP). Salta la principal si trae teléfono ajeno."""
    destino = FOTOS / p["id"]
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    fuentes = list((p.get("anuncio") or {}).get("fotos") or p.get("imagenes_locales") or [])
    if not fuentes:
        for i, url in enumerate(p.get("imagenes") or []):
            archivo = destino / f"origen-{i}.img"
            try:
                with urllib.request.urlopen(urllib.parse.quote(url, safe=":/"), timeout=30) as r:
                    archivo.write_bytes(r.read())
                fuentes.append(str(archivo))
            except OSError:
                continue
    if (p.get("anuncio") or {}).get("foto_con_telefono_ajeno") and len(fuentes) > 1:
        fuentes = fuentes[1:]
    salida = []
    for i, origen in enumerate(fuentes[: CONFIG["publicacion"]["fotos_maximo"]]):
        jpg = destino / f"{i + 1:02d}.jpg"
        r = subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", origen, "--out", str(jpg)],
                           capture_output=True)
        if r.returncode == 0 and jpg.exists():
            salida.append(str(jpg))
    if not salida:
        raise FormularioCambio("No hay fotos utilizables para este producto")
    return salida


def localizar(page, clave: str):
    for texto in TEXTOS[clave]:
        for loc in (page.get_by_label(texto, exact=True),
                    page.locator(f'label:has(span:text-is("{texto}")) input, label:has(span:text-is("{texto}")) textarea')):
            if loc.count():
                return loc.first
    raise FormularioCambio(f"No encontré el campo «{TEXTOS[clave][0]}»")


def opcion(page, textos: list[str]) -> bool:
    for texto in textos:
        loc = page.locator(f'[role="option"]:has-text("{texto}"), [role="listbox"] span:text-is("{texto}"), '
                           f'[role="dialog"] span:text-is("{texto}"), [role="menu"] span:text-is("{texto}")')
        if loc.count():
            loc.first.click()
            return True
    return False


def llenar(page, p: dict, fotos: list[str]) -> list[str]:
    """Llena lo que pueda. Devuelve la lista de campos que tienes que completar a mano."""
    a = p["anuncio"]
    pendientes = []
    page.goto(CREAR)
    page.wait_for_timeout(5000)
    entrada = page.locator('input[type="file"][accept*="image"]')
    if not entrada.count():
        entrada = page.locator('input[type="file"]')
    if entrada.count():
        entrada.first.set_input_files(fotos)
        page.wait_for_timeout(2500)
    else:
        pendientes.append(f"fotos (están en {FOTOS / p['id']})")

    for clave, valor in (("titulo", a["titulo"]), ("precio", str(a["precio"]))):
        try:
            localizar(page, clave).fill(valor)
        except FormularioCambio:
            pendientes.append(TEXTOS[clave][0].lower())

    try:
        localizar(page, "categoria").click()
        page.wait_for_timeout(1200)
        if not opcion(page, [a.get("categoria") or "Varios", "Varios", "Miscellaneous"]):
            pendientes.append(f"categoría ({a.get('categoria')})")
            page.keyboard.press("Escape")
        page.wait_for_timeout(800)
    except FormularioCambio:
        pendientes.append("categoría")

    try:
        localizar(page, "estado").click()
        page.wait_for_timeout(800)
        if not opcion(page, TEXTOS["nuevo"]):
            page.keyboard.press("Escape")
            pendientes.append("estado (Nuevo)")
    except FormularioCambio:
        pass  # algunas categorías no piden estado

    try:
        localizar(page, "descripcion").fill(a["descripcion"])
    except FormularioCambio:
        pendientes.append("descripción")
    return pendientes


def marcar_publicado(pid: str, url: str) -> None:
    ruta = PRODUCTOS / f"{pid}.json"
    p = leer_json(ruta, {})
    p["etapa"] = "publicado"
    p["publicacion"] = {"cuando": ahora(), "modo": "asistido", "url": url}
    p.setdefault("historial", []).append({"cuando": ahora(), "etapa": "publicado", "nota": "Publicado con el asistente"})
    p["actualizado"] = ahora()
    escribir_json(ruta, p)


def asistir(pid: str) -> int:
    from playwright.sync_api import sync_playwright

    p = leer_json(PRODUCTOS / f"{pid}.json")
    if not p or not p.get("anuncio"):
        print(f"El producto {pid} no tiene anuncio listo")
        return 2
    fotos = preparar_fotos(p)

    with sync_playwright() as pw, navegador.abrir(pw, "facebook", visible=True) as ctx:
        page = navegador.pagina(ctx)
        page.goto("https://www.facebook.com/")
        page.wait_for_timeout(3000)
        if not navegador.facebook_conectado(ctx) or "login" in page.url:
            navegador.marcar_sesion("facebook", False, "Sesión vencida: hay que reconectar")
            print("SESION_VENCIDA")
            return 4
        navegador.marcar_sesion("facebook", True)
        try:
            pendientes = llenar(page, p, fotos)
        except Exception as e:  # noqa: BLE001
            pendientes = [f"todo el formulario ({e})"]
        if pendientes:
            CAPTURAS.mkdir(parents=True, exist_ok=True)
            try:
                page.screenshot(path=str(CAPTURAS / f"{pid}-{int(time.time())}.png"), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            print("Completa a mano: " + ", ".join(pendientes))
        print("Revisa y haz clic en «Siguiente» y «Publicar» en la ventana.")

        limite = time.time() + 1800
        while time.time() < limite and ctx.pages:
            try:
                url = ctx.pages[-1].url
            except Exception:  # noqa: BLE001
                break
            if "/marketplace/" in url and "/create" not in url:
                marcar_publicado(pid, url)
                print("PUBLICADO")
                return 0
            time.sleep(2)
    print("Cerrado sin publicar")
    return 3


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    a = ap.parse_args()
    try:
        sys.exit(asistir(a.id))
    except navegador.Ocupado as e:
        print(f"OCUPADO: {e}")
        sys.exit(5)
    except FormularioCambio as e:
        print(f"FORMULARIO: {e}")
        sys.exit(2)
