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
import hashlib
import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data" / "products.json"
OUT_DIR = ROOT / "public" / "products"
CACHE_DIR = ROOT / ".cache" / "originals"
# La tarjeta OG lleva el nombre y el precio horneados en el JPEG: sin esto, cambiar
# un precio dejaría la vista previa de WhatsApp mostrando el precio viejo para siempre.
OG_LOCK = OUT_DIR / "_og.lock.json"
CDN = "https://d39ru7awumhhs2.cloudfront.net/"

# Lienzo cuadrado: consistencia visual en la grilla (evita saltos de layout).
SIZE_LG, SIZE_SM = 900, 450
MARGIN = 0.09          # aire alrededor del producto (proporción del lienzo)
SHADOW_BLUR = 22
SHADOW_ALPHA = 90

# Fondo de marca: degradado sutil, mismo lenguaje visual que el sitio.
BG_TOP = (23, 33, 51)
BG_BOTTOM = (12, 18, 30)

# Tarjeta para compartir en WhatsApp/Facebook. 1200x630 es la proporción 1.91:1
# que piden los lectores de Open Graph; recortan al centro si no se respeta.
# Se exporta en JPEG a propósito: la vista previa de WhatsApp no es fiable con WebP.
OG_W, OG_H = 1200, 630
BRAND = (56, 189, 248)     # --brand del sitio
TEXT = (246, 249, 255)     # --txt
MUTED = (146, 167, 190)    # --muted

# Se prueban en orden; si ninguna existe se cae a la tipografía de PIL (fea pero no rompe).
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


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


def og_fingerprint(product: dict) -> str:
    """Huella de lo que se dibuja dentro de la tarjeta: nombre y precio."""
    raw = f"{product['name']}|{product['price']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def read_lock() -> dict:
    if OG_LOCK.exists():
        try:
            return json.loads(OG_LOCK.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def load_font(size: int):
    """Primera tipografía disponible del sistema, o la de PIL si no hay ninguna."""
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    """Parte el texto en líneas que quepan en max_w, con elipsis si se pasa."""
    def shrink(word: str) -> str:
        """Recorta una palabra que por sí sola no cabe (si no, se sale del lienzo)."""
        if draw.textlength(word, font=font) <= max_w:
            return word
        while word and draw.textlength(word + "…", font=font) > max_w:
            word = word[:-1]
        return word + "…"

    words, lines, current = text.split(), [], ""
    for word in words:
        probe = f"{current} {word}".strip()
        if not current:
            current = shrink(word)
        elif draw.textlength(probe, font=font) <= max_w:
            current = probe
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) == max_lines and len(" ".join(lines).split()) < len(words):
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def cop(value: int) -> str:
    """28000 -> '$ 28.000' (separador de miles colombiano)."""
    return "$ " + f"{value:,}".replace(",", ".")


def render_og(cutout: Image.Image, product: dict, out_path: Path) -> None:
    """Tarjeta 1200x630 para la vista previa del enlace: producto + nombre + precio."""
    canvas = Image.new("RGB", (OG_W, OG_H))
    # Mismo degradado de marca, estirado al formato apaisado.
    canvas.paste(gradient_bg(OG_H).resize((OG_W, OG_H), Image.BILINEAR), (0, 0))
    canvas = canvas.convert("RGBA")

    # Producto a la izquierda, dentro de un cuadrado con aire.
    pane = int(OG_H * 0.82)
    subject = cutout.copy()
    subject.thumbnail((pane, pane), Image.LANCZOS)
    px = (OG_H - subject.width) // 2 + 20
    py = (OG_H - subject.height) // 2

    shadow = Image.new("RGBA", (OG_W, OG_H), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", subject.size, (0, 0, 0, SHADOW_ALPHA)), (px, py + 12), subject)
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR)))
    canvas.alpha_composite(subject, (px, py))

    draw = ImageDraw.Draw(canvas)
    x = OG_H + 40
    max_w = OG_W - x - 60

    f_eyebrow, f_title, f_price, f_pill = load_font(24), load_font(52), load_font(64), load_font(26)

    draw.text((x, 132), "MONKEY STORE", font=f_eyebrow, fill=BRAND)

    y = 182
    for line in wrap(draw, product["name"], f_title, max_w, 3):
        draw.text((x, y), line, font=f_title, fill=TEXT)
        y += 62

    y += 18
    draw.text((x, y), cop(product["price"]), font=f_price, fill=TEXT)

    # Píldora "Pago contra entrega": es el diferenciador real frente a Temu.
    label = "Pago contra entrega"
    pw = draw.textlength(label, font=f_pill)
    py2 = y + 96
    draw.rounded_rectangle((x, py2, x + pw + 44, py2 + 52), radius=26, fill=(30, 58, 82))
    draw.text((x + 22, py2 + 12), label, font=f_pill, fill=BRAND)

    canvas.convert("RGB").save(out_path, "JPEG", quality=82, optimize=True)


def render_og_home(out_path: Path) -> None:
    """Tarjeta de la home: sin producto, solo la propuesta de valor."""
    canvas = Image.new("RGB", (OG_W, OG_H))
    canvas.paste(gradient_bg(OG_H).resize((OG_W, OG_H), Image.BILINEAR), (0, 0))
    draw = ImageDraw.Draw(canvas)

    f_eyebrow, f_title, f_sub, f_pill = load_font(26), load_font(66), load_font(32), load_font(28)
    x, max_w = 90, OG_W - 180

    draw.text((x, 150), "MONKEY STORE", font=f_eyebrow, fill=BRAND)

    y = 208
    for line in wrap(draw, "Tecnología y fitness para Colombia", f_title, max_w, 2):
        draw.text((x, y), line, font=f_title, fill=TEXT)
        y += 78

    draw.text((x, y + 14), "Envíos a todo el país · Despachamos desde Medellín", font=f_sub, fill=MUTED)

    label = "Pagas cuando lo recibes"
    pw = draw.textlength(label, font=f_pill)
    py = y + 86
    draw.rounded_rectangle((x, py, x + pw + 48, py + 58), radius=29, fill=(30, 58, 82))
    draw.text((x + 24, py + 13), label, font=f_pill, fill=BRAND)

    canvas.save(out_path, "JPEG", quality=84, optimize=True)


def render_one(source: str, out_stem: str, remove_bg, force: bool, og_for: dict | None = None,
               lock: dict | None = None) -> bool:
    """Procesa una imagen de origen -> {stem}.webp (grande) y {stem}-sm.webp.

    Si `og_for` trae el producto, genera además {stem}-og.jpg (tarjeta para compartir).
    """
    lock = lock if lock is not None else {}
    lg_path = OUT_DIR / f"{out_stem}.webp"
    sm_path = OUT_DIR / f"{out_stem}-sm.webp"
    og_path = OUT_DIR / f"{out_stem}-og.jpg"

    # La OG se rehace si falta O si cambió el nombre/precio que lleva dibujados.
    needs_og = og_for is not None and (not og_path.exists() or lock.get(out_stem) != og_fingerprint(og_for))
    if lg_path.exists() and sm_path.exists() and not needs_og and not force:
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
    if force or not lg_path.exists():
        compose(cutout, SIZE_LG).save(lg_path, "WEBP", quality=86, method=6)
    if force or not sm_path.exists():
        compose(cutout, SIZE_SM).save(sm_path, "WEBP", quality=82, method=6)

    kb = (lg_path.stat().st_size + sm_path.stat().st_size) / 1024
    if og_for is not None and (force or needs_og):
        render_og(cutout, og_for, og_path)
        lock[out_stem] = og_fingerprint(og_for)
        kb += og_path.stat().st_size / 1024
        log(f"  ✅ {out_stem}  (+og, {kb:.0f} KB)")
    else:
        log(f"  ✅ {out_stem}  ({kb:.0f} KB)")
    return True


def process(product: dict, remove_bg, force: bool, lock: dict) -> bool:
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
            # La tarjeta para compartir se hace solo con la imagen principal.
            if render_one(source, stem, remove_bg, force,
                          og_for=product if index == 0 else None, lock=lock):
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

    lock = read_lock()
    ok = sum(process(p, remove_bg, args.force, lock) for p in products)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OG_LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    home_og = ROOT / "public" / "og-default.jpg"
    if args.force or not home_og.exists():
        render_og_home(home_og)
        log(f"\n  ✅ og-default.jpg  ({home_og.stat().st_size / 1024:.0f} KB)")

    log(f"\nListo: {ok}/{len(products)} imágenes disponibles.")
    return 0 if ok == len(products) else 1


if __name__ == "__main__":
    sys.exit(main())
