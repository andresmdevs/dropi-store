#!/usr/bin/env python3
"""
Pipeline de imágenes de producto para Monkey Store.

Toma las fotos originales del proveedor (CDN de Dropi), les quita el fondo,
las centra en un lienzo cuadrado con fondo de marca y sombra suave, y exporta
WebP optimizados a public/products/.

Resultado: catálogo visualmente uniforme (look de tienda propia, no de catálogo
de proveedor) y servido desde nuestro dominio en vez del CDN de Dropi.

Uso:
    .venv-img/bin/python scripts/build-images.py            # solo los que faltan
    .venv-img/bin/python scripts/build-images.py --force    # regenerar todo
    .venv-img/bin/python scripts/build-images.py --only slug1,slug2
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data" / "products.json"
OUT_DIR = ROOT / "public" / "products"
CACHE_DIR = ROOT / ".cache" / "originals"
CDN = "https://d39ru7awumhhs2.cloudfront.net/"

# Lienzo cuadrado: consistencia visual en la grilla (evita saltos de layout).
SIZE_LG, SIZE_SM = 900, 450
MARGIN = 0.09          # aire alrededor del producto (proporción del lienzo)
SHADOW_BLUR = 22
SHADOW_ALPHA = 90

# Fondo de marca: degradado sutil, mismo lenguaje visual que el sitio.
BG_TOP = (23, 33, 51)
BG_BOTTOM = (12, 18, 30)


def log(msg: str) -> None:
    print(msg, flush=True)


def download(path: str) -> bytes:
    """Descarga (con caché en disco) la imagen original del CDN del proveedor."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / urllib.parse.quote(path, safe="")
    if cached.exists():
        return cached.read_bytes()

    url = CDN + urllib.parse.quote(path)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    cached.write_bytes(data)
    return data


def gradient_bg(size: int) -> Image.Image:
    """Fondo degradado vertical del tamaño pedido."""
    grad = Image.new("RGB", (1, size))
    px = grad.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        px[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
    return grad.resize((size, size), Image.BILINEAR)


def trim_transparent(img: Image.Image) -> Image.Image:
    """Recorta el margen transparente para que el producto ocupe todo el lienzo."""
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def compose(cutout: Image.Image, size: int) -> Image.Image:
    """Centra el recorte en el lienzo de marca y le añade una sombra suave."""
    canvas = gradient_bg(size).convert("RGBA")

    inner = int(size * (1 - 2 * MARGIN))
    subject = cutout.copy()
    subject.thumbnail((inner, inner), Image.LANCZOS)

    x = (size - subject.width) // 2
    y = (size - subject.height) // 2

    # Sombra: silueta desenfocada y desplazada hacia abajo -> sensación de volumen.
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    silhouette = Image.new("RGBA", subject.size, (0, 0, 0, SHADOW_ALPHA))
    shadow.paste(silhouette, (x, y + int(size * 0.018)), subject)
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))

    canvas.alpha_composite(shadow)
    canvas.alpha_composite(subject, (x, y))
    return canvas.convert("RGB")


def render_one(source: str, out_stem: str, remove_bg, force: bool) -> bool:
    """Procesa una imagen de origen -> {stem}.webp (grande) y {stem}-sm.webp."""
    lg_path = OUT_DIR / f"{out_stem}.webp"
    sm_path = OUT_DIR / f"{out_stem}-sm.webp"
    if lg_path.exists() and sm_path.exists() and not force:
        log(f"  ✓  {out_stem} (ya existe)")
        return True

    raw = download(source)
    original = Image.open(io.BytesIO(raw))
    original.seek(0)  # GIF/animados: primer fotograma
    original = original.convert("RGBA")

    cutout = trim_transparent(remove_bg(original).convert("RGBA"))
    if cutout.width < 40 or cutout.height < 40:
        # El recorte dejó casi nada: mejor conservar la imagen original.
        log(f"  ⚠  {out_stem}: recorte vacío, uso la imagen original")
        cutout = original

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    compose(cutout, SIZE_LG).save(lg_path, "WEBP", quality=86, method=6)
    compose(cutout, SIZE_SM).save(sm_path, "WEBP", quality=82, method=6)

    kb = (lg_path.stat().st_size + sm_path.stat().st_size) / 1024
    log(f"  ✅ {out_stem}  ({kb:.0f} KB)")
    return True


def process(product: dict, remove_bg, force: bool) -> bool:
    """Procesa toda la galería del producto.

    La primera imagen es la principal ({slug}.webp) y las siguientes se numeran
    ({slug}-2.webp, {slug}-3.webp...) para alimentar la galería del detalle.
    """
    slug = product["slug"]
    sources = product.get("sourceImages") or []
    if not sources:
        log(f"  ⏭  {slug}: sin imagen de origen")
        return False

    done = 0
    for index, source in enumerate(sources):
        stem = slug if index == 0 else f"{slug}-{index + 1}"
        try:
            if render_one(source, stem, remove_bg, force):
                done += 1
        except Exception as exc:  # noqa: BLE001 - seguimos con las demás
            log(f"  ❌ {stem}: {exc}")

    return done > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerar aunque ya exista")
    parser.add_argument("--only", default="", help="lista de slugs separados por coma")
    args = parser.parse_args()

    products = json.loads(DATA.read_text(encoding="utf-8"))
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        products = [p for p in products if p["slug"] in wanted]

    log(f"Procesando {len(products)} productos -> {OUT_DIR.relative_to(ROOT)}/\n")

    # La primera ejecución descarga el modelo de recorte (~176 MB).
    from rembg import new_session, remove

    session = new_session("u2net")
    remove_bg = lambda im: remove(im, session=session)  # noqa: E731

    ok = sum(process(p, remove_bg, args.force) for p in products)
    log(f"\nListo: {ok}/{len(products)} imágenes disponibles.")
    return 0 if ok == len(products) else 1


if __name__ == "__main__":
    sys.exit(main())
