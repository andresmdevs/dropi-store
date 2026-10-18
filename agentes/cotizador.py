"""Cotiza el flete de un producto en las ciudades de referencia, sin crear órdenes.

Hace lo mismo que la «orden ficticia» manual, pero repite SOLO la consulta de
cotización que dispara el formulario de Dropi. Nunca confirma ni crea órdenes.

Se usa en dos pasos:

1. Calibrar (una vez, o cuando Dropi cambie su web):
       uv run --with playwright==1.60.0 python agentes/cotizador.py calibrar
   Abre un Chromium con un perfil propio (agentes/data/navegador). Inicias sesión
   en Dropi, armas una orden ficticia hasta ver el valor del flete (SIN
   confirmar) y respondes tres preguntas en la terminal. El script aprende qué
   petición hace la cotización y dónde viene el valor.

2. Cotizar (lo llama el orquestador solo):
       uv run --with playwright==1.60.0 python agentes/cotizador.py cotizar --ids 123,456
   Imprime en stdout un JSON {id: {CIUDAD: flete}}.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import unicodedata

from comun import CONFIG, DATOS, PRODUCTOS, ahora, escribir_json, leer_json

PERFIL = DATOS / "navegador"
CALIBRACION = DATOS / "calibracion.json"
CAPTURA = DATOS / "captura-calibracion.json"
INICIO = "https://app.dropi.co/dashboard/search"

# Cualquier URL que parezca crear o confirmar una orden queda vetada.
PROHIBIDO = re.compile(r"(orders?/?$|orders?/(create|store|save|confirm)|/create|/store|confirm)", re.I)
PERMITIDO = re.compile(r"(cotiza|quote|cotizar|tarifa|flete|shipping|freight|transportadora|trajectory)", re.I)
AUTH = re.compile(r"(authorization|token|x-auth|dropi)", re.I)


def normal(t) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", t.upper())


def caminar(obj, ruta=()):
    """Recorre un JSON y entrega (ruta, valor) de cada hoja."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from caminar(v, ruta + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from caminar(v, ruta + (i,))
    else:
        yield ruta, obj


def poner(obj, ruta, valor):
    for k in ruta[:-1]:
        obj = obj[k]
    obj[ruta[-1]] = valor


def obtener(obj, ruta):
    for k in ruta:
        obj = obj[k]
    return obj


def mismo_tipo(original, valor):
    """Respeta el tipo que mandó Dropi en la calibración (número o texto)."""
    try:
        if isinstance(original, int):
            return int(float(valor))
        if isinstance(original, float):
            return float(valor)
    except (TypeError, ValueError):
        pass
    return str(valor)


def general(ruta):
    return tuple("*" if isinstance(k, int) else k for k in ruta)


def mismo_numero(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.5
    except (TypeError, ValueError):
        return False


def a_json(texto):
    try:
        return json.loads(texto)
    except (TypeError, json.JSONDecodeError):
        return None


def plano(d: dict) -> dict:
    """Aplana un nivel: {"department": {"id": 5}} -> {"department.id": 5}."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update({f"{k}.{k2}": v2 for k2, v2 in v.items() if not isinstance(v2, (dict, list))})
        elif not isinstance(v, list):
            out[k] = v
    return out


def listas_de_ciudades(js):
    """Busca listas de dicts donde aparecen varias de las ciudades de referencia."""
    objetivo = {normal(c) for c in CONFIG["precios"]["ciudades"]}
    encontradas = []

    def visitar(o):
        if isinstance(o, list) and o and all(isinstance(x, dict) for x in o[:5]):
            nombres = {normal(v) for x in o for v in plano(x).values() if isinstance(v, str)}
            if len(objetivo & nombres) >= 2:
                encontradas.append([plano(x) for x in o])
        if isinstance(o, dict):
            for v in o.values():
                visitar(v)
        elif isinstance(o, list):
            for v in o:
                visitar(v)

    visitar(js)
    return encontradas


def buscar_ciudad(ciudades, nombre):
    n = normal(nombre)
    for c in ciudades:
        if any(isinstance(v, str) and normal(v) == n for v in c.values()):
            return c
    return None


# ---------------------------------------------------------------------------
# Navegador
# ---------------------------------------------------------------------------

def abrir(p, visible: bool):
    PERFIL.mkdir(parents=True, exist_ok=True)
    try:
        return p.chromium.launch_persistent_context(str(PERFIL), headless=not visible,
                                                    viewport={"width": 1400, "height": 900})
    except Exception as e:  # noqa: BLE001
        if "Executable doesn't exist" in str(e):
            import subprocess
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            return p.chromium.launch_persistent_context(str(PERFIL), headless=not visible)
        raise


def calibrar() -> None:
    from playwright.sync_api import sync_playwright

    capturas = []
    with sync_playwright() as p:
        ctx = abrir(p, visible=True)

        def al_responder(r):
            req = r.request
            if req.resource_type not in ("xhr", "fetch") or "dropi" not in req.url:
                return
            try:
                texto = r.text()
            except Exception:  # noqa: BLE001
                texto = None
            capturas.append({
                "metodo": req.method, "url": req.url, "estado": r.status,
                "headers": {k: v for k, v in req.headers.items() if AUTH.search(k) or k == "content-type"},
                "cuerpo": req.post_data, "respuesta": (texto or "")[:400_000],
            })

        ctx.on("response", al_responder)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(INICIO)
        print("\n" + "=" * 70)
        print("1. Inicia sesión en Dropi si te lo pide.")
        print("2. Arma una ORDEN FICTICIA de cualquier producto hasta que veas el valor")
        print("   del flete de las transportadoras.  ⚠️  NO LA CONFIRMES.")
        print("3. Vuelve aquí y responde.")
        print("=" * 70)
        input("\nPresiona Enter cuando estés viendo el valor del flete... ")
        ciudad = input("¿Qué ciudad de destino elegiste? (ej. CALI): ").strip()
        flete = input("¿Qué valor de flete viste? (solo números, ej. 14500): ").strip().replace(".", "")
        producto = input("¿ID del producto en Dropi? (Enter si no lo sabes): ").strip()
        precio = input("¿Precio de venta que pusiste? (Enter para omitir): ").strip().replace(".", "")
        ctx.close()

    escribir_json(CAPTURA, capturas)
    CAPTURA.chmod(0o600)
    resultado = analizar(capturas, ciudad, flete, producto, precio)
    escribir_json(CALIBRACION, resultado)
    CALIBRACION.chmod(0o600)
    print(json.dumps({k: v for k, v in resultado.items() if k not in ("ciudades", "cuerpo")},
                     ensure_ascii=False, indent=2))
    print("\n✅ Calibración guardada." if resultado.get("ok") else "\n⚠️  " + resultado["problema"])


def analizar(capturas, ciudad, flete, producto, precio) -> dict:
    ciudades = []
    for c in capturas:
        for lista in listas_de_ciudades(a_json(c["respuesta"])):
            if len(lista) > len(ciudades):
                ciudades = lista

    base = {"creado": ahora(), "ok": False, "ciudad_calibracion": ciudad, "flete_visto": flete}
    if not ciudades:
        return {**base, "problema": "No vi la lista de ciudades de Dropi. Repite y elige el destino desde el selector."}
    registro_ciudad = buscar_ciudad(ciudades, ciudad)
    if not registro_ciudad:
        return {**base, "problema": f"No encontré {ciudad} en la lista de ciudades capturada."}

    candidatas = []
    for c in capturas:
        if PROHIBIDO.search(c["url"]) and not PERMITIDO.search(c["url"]):
            continue
        cuerpo = a_json(c["cuerpo"])
        resp = a_json(c["respuesta"])
        if cuerpo is None or resp is None:
            continue
        rutas_flete = [r for r, v in caminar(resp) if mismo_numero(v, flete)]
        rutas_ciudad = {}
        for r, v in caminar(cuerpo):
            for atributo, valor in registro_ciudad.items():
                if v not in (None, "") and str(v) == str(valor):
                    rutas_ciudad[json.dumps(r)] = atributo
        if rutas_flete and rutas_ciudad:
            candidatas.append((c, rutas_flete, rutas_ciudad, cuerpo))

    if not candidatas:
        return {**base, "ciudades": ciudades,
                "problema": "No encontré una petición que lleve la ciudad y devuelva ese flete. "
                            "Revisa el valor que escribiste y repite."}

    c, rutas_flete, rutas_ciudad, cuerpo = candidatas[-1]
    rutas_producto = [r for r, v in caminar(cuerpo) if producto and str(v) == producto]
    rutas_precio = [r for r, v in caminar(cuerpo) if precio and mismo_numero(v, precio)]
    return {
        **base,
        "ok": True,
        "url": c["url"],
        "metodo": c["metodo"],
        "headers_auth": sorted(c["headers"]),
        "cuerpo": cuerpo,
        "rutas_ciudad": rutas_ciudad,
        "rutas_producto": [json.dumps(r) for r in rutas_producto],
        "rutas_precio": [json.dumps(r) for r in rutas_precio],
        "ruta_flete": list(general(rutas_flete[0])),
        "ciudades": ciudades,
    }


def extraer_fletes(resp, ruta_general):
    valores = []
    for r, v in caminar(resp):
        if general(r) == tuple(ruta_general) and isinstance(v, (int, float)) and v > 0:
            valores.append(int(v))
        elif general(r) == tuple(ruta_general) and isinstance(v, str) and v.replace(".", "").isdigit():
            valores.append(int(float(v)))
    return valores


def cotizar(ids: list[str]) -> dict:
    from playwright.sync_api import sync_playwright

    cal = leer_json(CALIBRACION)
    if not cal or not cal.get("ok"):
        raise SystemExit("SIN_CALIBRAR")
    if PROHIBIDO.search(cal["url"]) and not PERMITIDO.search(cal["url"]):
        raise SystemExit("La URL calibrada parece crear órdenes; se rechaza por seguridad.")

    salida = {}
    with sync_playwright() as p:
        ctx = abrir(p, visible=False)
        auth = {}

        def al_pedir(req):
            if "api.dropi" in req.url:
                for k, v in req.headers.items():
                    if k in cal["headers_auth"]:
                        auth[k] = v

        ctx.on("request", al_pedir)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(INICIO)
        page.wait_for_timeout(8000)
        if "login" in page.url or not auth:
            ctx.close()
            raise SystemExit("SESION_VENCIDA")

        for pid in ids:
            prod = leer_json(PRODUCTOS / f"{pid}.json", {})
            precio = prod.get("precio_tienda") or prod.get("precio_sugerido") or (prod.get("costo") or 0) * 2
            fletes = {}
            for nombre in CONFIG["precios"]["ciudades"]:
                destino = buscar_ciudad(cal["ciudades"], nombre)
                if not destino:
                    continue
                cuerpo = copy.deepcopy(cal["cuerpo"])
                for ruta, atributo in cal["rutas_ciudad"].items():
                    if atributo in destino:
                        poner(cuerpo, json.loads(ruta), destino[atributo])
                for ruta in map(json.loads, cal["rutas_producto"]):
                    poner(cuerpo, ruta, mismo_tipo(obtener(cal["cuerpo"], ruta), pid))
                for ruta in map(json.loads, cal["rutas_precio"]):
                    poner(cuerpo, ruta, mismo_tipo(obtener(cal["cuerpo"], ruta), precio))
                r = page.evaluate(
                    """async ([url, metodo, headers, cuerpo]) => {
                        const r = await fetch(url, {method: metodo, headers: {...headers, 'content-type': 'application/json'},
                                                     body: metodo === 'GET' ? undefined : cuerpo});
                        return {estado: r.status, texto: await r.text()};
                    }""",
                    [cal["url"], cal["metodo"], auth, json.dumps(cuerpo)],
                )
                valores = extraer_fletes(a_json(r["texto"]), cal["ruta_flete"]) if r["estado"] < 400 else []
                if valores:
                    fletes[nombre] = min(valores)
            salida[pid] = fletes
        ctx.close()
    return salida


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["calibrar", "cotizar"])
    ap.add_argument("--ids", default="")
    a = ap.parse_args()
    if a.modo == "calibrar":
        calibrar()
    else:
        print(json.dumps(cotizar([i for i in a.ids.split(",") if i])))
