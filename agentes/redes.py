"""Publicación automática en la Página de Facebook y el Instagram de Monkey Store.

Usa solo la API oficial de Meta (Graph API) con el token de un Usuario del
sistema del portafolio comercial: lo publicado sale como la Página y la cuenta
de Instagram del negocio, nunca como tu perfil personal. Nada de navegador,
cookies ni grupos. Guía de configuración: docs/META-REDES.md

    python3 agentes/redes.py verificar             # revisa token, Página e Instagram
    python3 agentes/redes.py ensayo                # elige producto y escribe el texto, sin publicar
    python3 agentes/redes.py publicar --id 2099675 # publica ese producto ya
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from comun import CONFIG, DATOS, PRODUCTOS, ahora, cargar_env, chat_json, escribir_json, leer_json

R = CONFIG["redes"]
GRAPH = f"https://graph.facebook.com/{R['graph_version']}"
HISTORIAL = DATOS / "redes.json"
SITIO = "https://monkey-store.onrender.com"


class MetaError(Exception):
    pass


# ---------------------------------------------------------------------------
# Graph API
# ---------------------------------------------------------------------------

def _llamar(metodo: str, ruta: str, token: str, datos: dict | None = None, timeout: int = 60) -> dict:
    datos = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in (datos or {}).items()}
    datos["access_token"] = token
    url = f"{GRAPH}/{ruta.lstrip('/')}"
    if metodo == "GET":
        req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(datos)}")
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(datos).encode(), method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get("error", {})
        except ValueError:
            err = {}
        raise MetaError(f"Meta {e.code}: {err.get('message', 'error')} (code {err.get('code')}, "
                        f"subcode {err.get('error_subcode')})") from e


def credenciales() -> dict:
    cargar_env()
    token = os.environ.get("META_TOKEN", "").strip()
    pagina = os.environ.get("META_PAGE_ID", "").strip()
    if not token or not pagina:
        raise MetaError("Faltan META_TOKEN y META_PAGE_ID en dropi-store/.env.local (ver docs/META-REDES.md)")
    return {"token": token, "pagina": pagina, "instagram": os.environ.get("META_IG_ID", "").strip()}


def conexion() -> dict:
    """Token de Página derivado del Usuario del sistema + ids de Página e Instagram."""
    c = credenciales()
    p = _llamar("GET", c["pagina"], c["token"],
                {"fields": "name,access_token,instagram_business_account{id,username}"})
    if "access_token" not in p:
        raise MetaError("El token no tiene permiso sobre la Página (asígnala al Usuario del sistema con control total)")
    ig = p.get("instagram_business_account") or {}
    return {"pagina_id": c["pagina"], "pagina_nombre": p.get("name"), "token_pagina": p["access_token"],
            "token": c["token"], "ig_id": c["instagram"] or ig.get("id"), "ig_usuario": ig.get("username")}


def verificar() -> dict:
    try:
        c = conexion()
        yo = _llamar("GET", "me", c["token"], {"fields": "id,name"})
        estado = {"ok": True, "pagina": c["pagina_nombre"], "instagram": c["ig_usuario"],
                  "publica_como": yo.get("name"), "cuando": ahora()}
        if R.get("instagram") and not c["ig_id"]:
            estado["aviso"] = "La Página no tiene una cuenta profesional de Instagram vinculada"
    except MetaError as e:
        estado = {"ok": False, "error": str(e), "cuando": ahora()}
    h = leer_json(HISTORIAL, {}) or {}
    h["conexion"] = estado
    escribir_json(HISTORIAL, h)
    return estado


def publicar_facebook(c: dict, fotos: list[str], texto: str) -> dict:
    ids = []
    for url in fotos:
        r = _llamar("POST", f"{c['pagina_id']}/photos", c["token_pagina"], {"url": url, "published": "false"})
        ids.append(r["id"])
    datos = {"message": texto}
    for i, fid in enumerate(ids):
        datos[f"attached_media[{i}]"] = {"media_fbid": fid}
    r = _llamar("POST", f"{c['pagina_id']}/feed", c["token_pagina"], datos)
    return {"id": r["id"], "url": f"https://www.facebook.com/{r['id']}"}


def _esperar_contenedor(c: dict, contenedor: str) -> None:
    for _ in range(18):  # hasta 3 minutos
        estado = _llamar("GET", contenedor, c["token_pagina"], {"fields": "status_code"}).get("status_code")
        if estado == "FINISHED":
            return
        if estado in ("ERROR", "EXPIRED"):
            raise MetaError(f"Instagram rechazó el contenido ({estado})")
        time.sleep(10)
    raise MetaError("Instagram tardó demasiado en procesar las fotos")


def publicar_instagram(c: dict, fotos: list[str], texto: str) -> dict:
    if not c["ig_id"]:
        raise MetaError("No hay cuenta de Instagram vinculada a la Página")
    tok = c["token_pagina"]
    if len(fotos) == 1:
        contenedor = _llamar("POST", f"{c['ig_id']}/media", tok, {"image_url": fotos[0], "caption": texto})["id"]
    else:
        hijos = [_llamar("POST", f"{c['ig_id']}/media", tok, {"image_url": u, "is_carousel_item": "true"})["id"]
                 for u in fotos[:10]]
        for h in hijos:
            _esperar_contenedor(c, h)
        contenedor = _llamar("POST", f"{c['ig_id']}/media", tok,
                             {"media_type": "CAROUSEL", "children": ",".join(hijos), "caption": texto})["id"]
    _esperar_contenedor(c, contenedor)
    r = _llamar("POST", f"{c['ig_id']}/media_publish", tok, {"creation_id": contenedor})
    enlace = _llamar("GET", r["id"], tok, {"fields": "permalink"}).get("permalink")
    return {"id": r["id"], "url": enlace}


# ---------------------------------------------------------------------------
# Qué publicar
# ---------------------------------------------------------------------------

def _es_jpeg(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.headers.get_content_type() == "image/jpeg"
    except OSError:
        return False


def fotos_publicas(p: dict) -> list[str]:
    """URLs públicas en JPEG (Instagram no acepta otra cosa). Salta la foto con teléfono ajeno."""
    urls = [urllib.parse.quote(u, safe=":/") for u in p.get("imagenes") or []]
    if (p.get("anuncio") or {}).get("foto_con_telefono_ajeno") and len(urls) > 1:
        urls = urls[1:]
    jpeg = [u for u in urls[: R["fotos_maximo"] + 2] if _es_jpeg(u)][: R["fotos_maximo"]]
    if not jpeg and p.get("slug") and p.get("fuente") == "catalogo-tienda":
        og = f"{SITIO}/products/{p['slug']}-og.jpg"
        if _es_jpeg(og):
            jpeg = [og]
    return jpeg


def publicable(p: dict) -> bool:
    pr = p.get("precio") or {}
    alertas = " ".join(pr.get("alertas") or [])
    return (p.get("etapa") in ("en_cola", "publicado") and p.get("anuncio") and pr.get("precio")
            and not pr.get("provisional") and "Poca ganancia" not in alertas
            and (p.get("evaluacion") or {}).get("decision") != "descartar")


def ultima_vez(p: dict) -> datetime | None:
    cuando = (p.get("redes") or {}).get("cuando")
    return datetime.fromisoformat(cuando) if cuando else None


def elegir() -> dict | None:
    limite = datetime.now().astimezone() - timedelta(days=R["dias_sin_repetir"])
    candidatos = []
    for f in PRODUCTOS.glob("*.json"):
        p = leer_json(f)
        if not p or not publicable(p):
            continue
        u = ultima_vez(p)
        if u and u > limite:
            continue
        candidatos.append(p)
    # Primero lo que nunca se ha publicado, luego lo que hace más tiempo; a igualdad, mejor puntaje.
    nunca = datetime(1970, 1, 1).astimezone()
    candidatos.sort(key=lambda p: (ultima_vez(p) is not None, ultima_vez(p) or nunca,
                                   -((p.get("evaluacion") or {}).get("puntaje") or 0)))
    return candidatos[0] if candidatos else None


def ciudad_del_turno() -> str:
    h = leer_json(HISTORIAL, {}) or {}
    ciudades = R["ciudades_foco"]
    return ciudades[len(h.get("publicaciones", [])) % len(ciudades)]


SISTEMA = """Eres el community manager de {marca}, una tienda colombiana que vende por redes con pago
contra entrega y envío incluido a toda Colombia. Escribes en español de Colombia, cercano y claro, sin exagerar.

Reglas:
- No inventes características que no estén en los datos. Nada de promesas médicas.
- Empieza con un gancho corto que diga para qué sirve el producto.
- Luego 3 o 4 viñetas con «•» y el precio en una línea propia.
- Menciona que hay envíos a la ciudad indicada y a toda Colombia.
- Cierra con: pago contra entrega, envío incluido y «Pídelo por WhatsApp al 311 791 8947».
- facebook: puede llevar el enlace del producto si viene en los datos.
- instagram: sin enlaces; termina con los hashtags (máximo 15, en minúscula, sin repetir).
Responde solo con el JSON pedido."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "facebook": {"type": "string"},
        "instagram": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}, "maxItems": 15},
    },
    "required": ["facebook", "instagram", "hashtags"],
}


def escribir(p: dict, ciudad: str) -> dict:
    a = p["anuncio"]
    datos = {
        "producto": p["nombre"], "titulo_anuncio": a.get("titulo"), "descripcion": a.get("descripcion"),
        "precio": a.get("precio_texto"), "ciudad_foco": ciudad.title(),
        "enlace": f"{SITIO}/producto/{p['slug']}" if p.get("fuente") == "catalogo-tienda" else None,
        "hashtags_base": R["hashtags_base"],
    }
    t = chat_json(CONFIG["modelos"]["publicista"], SISTEMA.format(marca=R.get("marca", "Monkey Store")),
                  "Escribe la publicación para la Página de Facebook y para Instagram:\n"
                  + json.dumps(datos, ensure_ascii=False), ESQUEMA)
    etiquetas = []
    for h in R["hashtags_base"] + t.get("hashtags", []):
        h = "#" + h.lstrip("#").replace(" ", "").lower()
        if h not in etiquetas:
            etiquetas.append(h)
    precio = a.get("precio_texto") or ""
    fb = fijar_datos(t["facebook"], precio, con_enlace=True)
    ig = fijar_datos(t["instagram"], precio, con_enlace=False)
    cuerpo_ig = "\n".join(l for l in ig.splitlines() if not l.strip().startswith("#")).rstrip()
    ig = cuerpo_ig + "\n\n" + " ".join(etiquetas[:15])
    return {"facebook": fb, "instagram": ig[:2200], "ciudad": ciudad}


TELEFONO = re.compile(r"(whats\s*app|wa\.me|\+?57\s?3\d{2}|\b3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b)", re.I)
PRECIO = re.compile(r"\$\s?\d{1,3}(?:[.,]\d{3})+")


def fijar_datos(texto: str, precio: str, con_enlace: bool) -> str:
    """El teléfono y el precio los pone el programa, no el modelo (se equivoca con los números)."""
    numero = CONFIG["telefono"]["actual"]
    legible = f"{numero[:3]} {numero[3:6]} {numero[6:]}"
    lineas = [l for l in texto.strip().splitlines() if not TELEFONO.search(l)]
    texto = PRECIO.sub(precio, "\n".join(lineas)) if precio else "\n".join(lineas)
    if precio and precio not in texto:
        texto += f"\n\n💰 {precio}"
    cta = f"📲 Pídelo por WhatsApp al {legible}"
    if con_enlace:
        cta += f"\nhttps://wa.me/57{numero}"
    hashtags = [l for l in texto.splitlines() if l.strip().startswith("#")]
    cuerpo = "\n".join(l for l in texto.splitlines() if not l.strip().startswith("#")).rstrip()
    return (cuerpo + "\n\n" + cta + ("\n\n" + "\n".join(hashtags) if hashtags else "")).strip()


def publicar(p: dict, ensayo: bool = False) -> dict:
    fotos = fotos_publicas(p)
    if not fotos:
        raise MetaError(f"{p['nombre']}: no tiene fotos JPEG públicas")
    textos = escribir(p, ciudad_del_turno())
    resultado = {"producto": p["id"], "nombre": p["nombre"], "cuando": ahora(), "fotos": fotos,
                 "textos": textos, "ensayo": ensayo}
    if not ensayo:
        c = conexion()
        if R.get("facebook"):
            resultado["facebook"] = publicar_facebook(c, fotos, textos["facebook"])
        if R.get("instagram") and c["ig_id"]:
            resultado["instagram"] = publicar_instagram(c, fotos, textos["instagram"])
        p = leer_json(PRODUCTOS / f"{p['id']}.json", p)
        p["redes"] = {"cuando": resultado["cuando"], "facebook": resultado.get("facebook"),
                      "instagram": resultado.get("instagram")}
        escribir_json(PRODUCTOS / f"{p['id']}.json", p)
    h = leer_json(HISTORIAL, {}) or {}
    clave = "ensayos" if ensayo else "publicaciones"
    h[clave] = (h.get(clave, []) + [resultado])[-200:]
    escribir_json(HISTORIAL, h)
    return resultado


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------

def _hechos_hoy() -> set[int]:
    h = leer_json(HISTORIAL, {}) or {}
    hoy = datetime.now().strftime("%Y-%m-%d")
    return {x.get("turno") for x in h.get("turnos", []) if x.get("fecha") == hoy}


def turno_pendiente() -> int | None:
    """El turno más reciente del día que ya llegó y no se ha cumplido (None si no toca)."""
    hora = datetime.now().hour
    pendientes = [t for t in R["horas"] if t <= hora and t not in _hechos_hoy()]
    return max(pendientes) if pendientes else None


def marcar_turno(turno: int, nota: str) -> None:
    """Marca el turno y salta los anteriores del día: nunca se publican turnos atrasados en ráfaga."""
    h = leer_json(HISTORIAL, {}) or {}
    hoy = datetime.now().strftime("%Y-%m-%d")
    hechos = _hechos_hoy()
    nuevos = [{"fecha": hoy, "turno": t, "nota": f"Saltado (se cubrió en el turno de las {turno}:00)",
               "cuando": ahora()} for t in R["horas"] if t < turno and t not in hechos]
    nuevos.append({"fecha": hoy, "turno": turno, "nota": nota, "cuando": ahora()})
    h["turnos"] = (h.get("turnos", []) + nuevos)[-100:]
    escribir_json(HISTORIAL, h)


def proximo_turno() -> str:
    if turno_pendiente() is not None:
        return "ahora"
    hora = datetime.now().hour
    siguientes = [t for t in sorted(R["horas"]) if t > hora]
    return f"hoy {siguientes[0]:02d}:00" if siguientes else f"mañana {min(R['horas']):02d}:00"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["verificar", "ensayo", "publicar"])
    ap.add_argument("--id")
    a = ap.parse_args()
    if a.modo == "verificar":
        print(json.dumps(verificar(), ensure_ascii=False, indent=2))
    else:
        prod = leer_json(PRODUCTOS / f"{a.id}.json") if a.id else elegir()
        if not prod:
            raise SystemExit("No hay productos listos para redes (necesitan precio cotizado, no provisional)")
        r = publicar(prod, ensayo=a.modo == "ensayo")
        print(json.dumps(r, ensure_ascii=False, indent=2))
