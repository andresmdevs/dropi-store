"""De dónde salen los productos: la API de Integraciones de Dropi y el catálogo de la tienda."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from comun import CONFIG, PRODUCTOS, RAIZ, ahora, cargar_env, escribir_json, leer_json

CDN = "https://d39ru7awumhhs2.cloudfront.net/"


class TokenVencido(Exception):
    pass


def slug(texto: str) -> str:
    t = texto.lower()
    for a, b in zip("áéíóúñü", "aeiounu"):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60]


def ruta_producto(pid: str):
    return PRODUCTOS / f"{pid}.json"


def existe(pid: str) -> bool:
    return ruta_producto(pid).exists()


def nuevo_registro(**campos) -> dict:
    base = {
        "etapa": "nuevo",
        "creado": ahora(),
        "actualizado": ahora(),
        "historial": [],
        "evaluacion": None,
        "fletes": None,
        "precio": None,
        "anuncio": None,
    }
    base.update(campos)
    return base


# ---------------------------------------------------------------------------
# Catálogo propio de la tienda (src/data/products.json): arranque inmediato
# ---------------------------------------------------------------------------

def sembrar_desde_tienda() -> int:
    catalogo = leer_json(RAIZ / "src" / "data" / "products.json", [])
    publicados = set(CONFIG.get("ya_publicados_marketplace", []))
    nuevos = 0
    for p in catalogo:
        pid = str(p["id"])
        if existe(pid):
            continue
        imagenes_locales = [
            str(RAIZ / "public" / "products" / (f"{p['slug']}.webp" if i == 0 else f"{p['slug']}-{i + 1}.webp"))
            for i in range(max(1, len(p.get("sourceImages", []))))
        ]
        reg = nuevo_registro(
            id=pid,
            slug=p["slug"],
            nombre=p["name"],
            fuente="catalogo-tienda",
            categoria=p.get("category"),
            costo=p.get("cost"),
            precio_sugerido=None,
            precio_tienda=p.get("price"),
            stock=None,
            descripcion=p.get("description", ""),
            destacados=p.get("highlights", []),
            imagenes=[CDN + s for s in p.get("sourceImages", [])],
            imagenes_locales=[r for r in imagenes_locales if os.path.exists(r)],
        )
        if p["slug"] in publicados:
            reg["etapa"] = "publicado"
            reg["historial"].append({"cuando": ahora(), "etapa": "publicado", "nota": "Ya estaba en Marketplace"})
        escribir_json(ruta_producto(pid), reg)
        nuevos += 1
    return nuevos


# ---------------------------------------------------------------------------
# API de Integraciones de Dropi
# ---------------------------------------------------------------------------

def _dropi(payload: dict) -> dict:
    cargar_env()
    clave = os.environ.get("DROPI_INTEGRATION_KEY")
    if not clave:
        raise TokenVencido("Falta DROPI_INTEGRATION_KEY en .env.local")
    base = os.environ.get("DROPI_API_URL", "https://api.dropi.co").rstrip("/")
    req = urllib.request.Request(
        f"{base}/integrations/products/index",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "dropi-integration-key": clave},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise TokenVencido(
                "El token de Dropi está vencido (401). Genera uno nuevo en Dropi → Integraciones "
                "y pégalo en dropi-store/.env.local como DROPI_INTEGRATION_KEY"
            ) from e
        raise


def _num(*valores) -> int | None:
    for v in valores:
        try:
            if v not in (None, ""):
                return int(float(v))
        except (TypeError, ValueError):
            continue
    return None


def _stock(o: dict) -> int | None:
    if o.get("stock") is not None:
        return _num(o.get("stock"))
    bodegas = o.get("warehouse_product") or o.get("warehouses") or []
    total = sum(_num(b.get("stock")) or 0 for b in bodegas if isinstance(b, dict))
    return total if bodegas else None


def _limpiar_html(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t or "")).strip()


def traer_catalogo_dropi() -> int:
    """Busca por cada palabra clave y guarda los productos que aún no conocemos."""
    cfg = CONFIG["dropi_busqueda"]
    nuevos = 0
    for palabra in cfg["palabras"]:
        r = _dropi({
            "startData": 0, "pageSize": cfg["por_pagina"], "order_type": "DESC", "order_by": "id",
            "keywords": palabra, "active": True, "no_count": True, "integration": True, "get_stock": True,
        })
        for o in r.get("objects") or []:
            pid = str(o.get("id"))
            if not pid or existe(pid):
                continue
            stock = _stock(o)
            if stock is not None and stock < cfg["stock_minimo"]:
                continue
            galeria = [g.get("urlS3") or g.get("url") for g in (o.get("gallery") or []) if isinstance(g, dict)]
            categorias = [c.get("name") for c in (o.get("categories") or []) if isinstance(c, dict)]
            escribir_json(ruta_producto(pid), nuevo_registro(
                id=pid,
                slug=slug(o.get("name", pid)),
                nombre=o.get("name", ""),
                fuente="dropi-api",
                busqueda=palabra,
                categoria=", ".join(filter(None, categorias)) or None,
                costo=_num(o.get("sale_price"), o.get("price")),
                precio_sugerido=_num(o.get("suggested_price")),
                precio_tienda=None,
                stock=stock,
                descripcion=_limpiar_html(o.get("description", ""))[:1500],
                destacados=[],
                imagenes=[g if g.startswith("http") else CDN + g for g in galeria if g],
                imagenes_locales=[],
            ))
            nuevos += 1
    return nuevos
