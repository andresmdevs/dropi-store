"""Prepara un anuncio para publicarlo desde tu propio Chrome, con tu sesión de Facebook.

    python3 agentes/publicador.py --id 2099675

- Convierte las fotos a JPG en agentes/data/fotos-fb/<id>/ y abre esa carpeta en
  Finder, lista para arrastrarlas al formulario.
- Copia la descripción al portapapeles (título y precio se copian desde el panel).
- Abre el formulario de Marketplace en una pestaña nueva de tu Chrome.

No toca Facebook: el formulario lo llenas y lo publicas tú. Después marca el
anuncio como publicado en el panel.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

from comun import CONFIG, DATOS, PRODUCTOS, leer_json

CREAR = "https://www.facebook.com/marketplace/create/item"
FOTOS = DATOS / "fotos-fb"


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
        r = subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", origen, "--out", str(jpg)], capture_output=True)
        if r.returncode == 0 and jpg.exists():
            salida.append(str(jpg))
    for f in destino.glob("origen-*"):
        f.unlink()
    return salida


def preparar(pid: str) -> int:
    p = leer_json(PRODUCTOS / f"{pid}.json")
    if not p or not p.get("anuncio"):
        print(f"El producto {pid} no tiene anuncio listo")
        return 2
    fotos = preparar_fotos(p)
    subprocess.run(["/usr/bin/pbcopy"], input=p["anuncio"]["descripcion"].encode(), check=False)
    if fotos:
        subprocess.run(["/usr/bin/open", str(FOTOS / pid)], check=False)
    subprocess.run(["/usr/bin/open", "-a", "Google Chrome", CREAR], check=False)
    print(f"Listo: {len(fotos)} fotos en Finder, descripción copiada y Marketplace abierto en Chrome")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    sys.exit(preparar(ap.parse_args().id))
