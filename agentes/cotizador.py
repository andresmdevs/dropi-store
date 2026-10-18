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

   De paso aprende la búsqueda del catálogo que tengas abierta (filtros como
   «Con órdenes»), para traer productos top aunque el token de Integraciones venza.

2. Cotizar (lo llama el orquestador solo):
       uv run --with playwright==1.60.0 python agentes/cotizador.py cotizar --ids 123,456
   Imprime en stdout un JSON {id: {CIUDAD: flete}}.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import unicodedata

import navegador
from comun import CONFIG, DATOS, PRODUCTOS, ahora, escribir_json, leer_json

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
# Calibración
# ---------------------------------------------------------------------------

PRECIOS = ("sale_price", "suggested_price", "price", "precio")
PAGINA = ("startData", "start", "offset", "page", "pagina")


def lista_de_productos(js):
    """Ruta (generalizada) de la lista más larga de dicts con nombre y precio."""
    mejor = None
    for ruta, _ in caminar(js):
        if len(ruta) < 2 or not isinstance(ruta[-2], int):
            continue
        lista_ruta = ruta[:-2]
        try:
            lista = obtener(js, lista_ruta)
        except (KeyError, IndexError, TypeError):
            continue
        if not isinstance(lista, list) or len(lista) < 5:
            continue
        muestra = [x for x in lista[:5] if isinstance(x, dict)]
        if len(muestra) == 5 and all("name" in x and any(k in x for k in PRECIOS) for x in muestra):
            if not mejor or len(lista) > mejor[1]:
                mejor = (list(lista_ruta), len(lista))
    return mejor


def detectar_catalogo(capturas):
    for c in reversed(capturas):
        if PROHIBIDO.search(c["url"]) or c["metodo"] not in ("GET", "POST"):
            continue
        encontrado = lista_de_productos(a_json(c["respuesta"]))
        if encontrado:
            cuerpo = a_json(c["cuerpo"]) if c["cuerpo"] else None
            pagina = next((k for k in PAGINA if isinstance(cuerpo, dict) and k in cuerpo), None)
            return {"url": c["url"], "metodo": c["metodo"], "cuerpo": cuerpo, "headers_auth": sorted(c["headers"]),
                    "ruta_lista": encontrado[0], "por_pagina": encontrado[1], "campo_pagina": pagina}
    return None


def calibrar() -> None:
    from playwright.sync_api import sync_playwright

    capturas = []
    with sync_playwright() as p, navegador.abrir(p, "dropi", visible=True, esperar=True) as ctx:

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
        page = navegador.pagina(ctx)
        page.goto(INICIO)
        print("\n" + "=" * 70)
        print("1. Inicia sesión en Dropi si te lo pide.")
        print("2. En el catálogo, pon los filtros con los que buscas productos top")
        print("   (por ejemplo «Con órdenes») y aplica. Los agentes repetirán esa búsqueda.")
        print("3. Arma una ORDEN FICTICIA de cualquier producto hasta que veas el valor")
        print("   del flete de las transportadoras.  ⚠️  NO LA CONFIRMES.")
        print("4. Vuelve aquí y responde.")
        print("=" * 70)
        input("\nPresiona Enter cuando estés viendo el valor del flete... ")
        ciudad = input("¿Qué ciudad de destino elegiste? (ej. CALI): ").strip()
        flete = input("¿Qué valor de flete viste? (solo números, ej. 14500): ").strip().replace(".", "")
        producto = input("¿ID del producto en Dropi? (Enter si no lo sabes): ").strip()
        precio = input("¿Precio de venta que pusiste? (Enter para omitir): ").strip().replace(".", "")
        navegador.marcar_sesion("dropi", navegador.dropi_conectado(page), "Calibración")

    escribir_json(CAPTURA, capturas)
    CAPTURA.chmod(0o600)
    resultado = analizar(capturas, ciudad, flete, producto, precio)
    resultado["catalogo"] = detectar_catalogo(capturas)
    escribir_json(CALIBRACION, resultado)
    CALIBRACION.chmod(0o600)
    print(json.dumps({k: v for k, v in resultado.items() if k not in ("ciudades", "cuerpo", "catalogo")},
                     ensure_ascii=False, indent=2))
    print("\n✅ Cotización calibrada." if resultado.get("ok") else "\n⚠️  " + resultado["problema"])
    print("✅ Búsqueda del catálogo aprendida." if resultado["catalogo"]
          else "⚠️  No vi la búsqueda del catálogo: abre el catálogo con tus filtros durante la calibración.")


def aprender_busqueda() -> None:
    """Abre Dropi; pones filtros en el catálogo, aplicas y cierras la ventana. Guarda esa búsqueda."""
    from playwright.sync_api import sync_playwright

    capturas = []
    with sync_playwright() as p, navegador.abrir(p, "dropi", visible=True, esperar=True) as ctx:

        def al_responder(r):
            req = r.request
            if req.resource_type in ("xhr", "fetch") and "products/v4/index" in req.url:
                try:
                    texto = r.text()
                except Exception:  # noqa: BLE001
                    return
                capturas.append({"metodo": req.method, "url": req.url, "estado": r.status,
                                 "headers": {k: v for k, v in req.headers.items() if AUTH.search(k)},
                                 "cuerpo": req.post_data, "respuesta": texto[:400_000]})

        ctx.on("response", al_responder)
        page = navegador.pagina(ctx)
        page.goto(INICIO)
        print("Pon los filtros en el catálogo («Con órdenes», categoría, orden), dale «Aplicar filtros» "
              "y cierra la ventana cuando veas los productos.")
        while ctx.pages:
            try:
                ctx.pages[-1].wait_for_timeout(1000)
            except Exception:  # noqa: BLE001
                break
    # La última búsqueda de la primera página es la que quedó con tus filtros.
    primeras = [c for c in capturas if (a_json(c["cuerpo"]) or {}).get("startData", 0) in (0, None)]
    catalogo = detectar_catalogo(primeras or capturas)
    if not catalogo:
        print("⚠️  No vi ninguna búsqueda del catálogo.")
        return
    cal = leer_json(CALIBRACION, {}) or {}
    cal["catalogo"] = catalogo
    escribir_json(CALIBRACION, cal)
    CALIBRACION.chmod(0o600)
    filtros = {k: v for k, v in (catalogo["cuerpo"] or {}).items() if k not in ("pageSize", "startData")}
    print("✅ Búsqueda aprendida:", json.dumps(filtros, ensure_ascii=False))
    subprocess.run(["/usr/bin/osascript", "-e",
                    'display notification "Búsqueda de Dropi aprendida ✅" with title "Monkey Agentes"'],
                   capture_output=True)


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


# ---------------------------------------------------------------------------
# Repetir peticiones con la sesión del navegador
# ---------------------------------------------------------------------------

class Sesion:
    """Abre Dropi con el perfil del agente y toma las cabeceras de autenticación vigentes.

    Las peticiones salen desde la propia página, con las mismas cabeceras que usa la web.
    """

    def __init__(self, p, nombres_auth):
        self._cm = navegador.abrir(p, "dropi", visible=False)
        self.nombres = set(nombres_auth)
        self.auth = {}

    def __enter__(self):
        self.ctx = self._cm.__enter__()

        def al_pedir(req):
            if "api.dropi" in req.url:
                for k, v in req.headers.items():
                    if k in self.nombres:
                        self.auth[k] = v

        self.ctx.on("request", al_pedir)
        self.page = navegador.pagina(self.ctx)
        self.page.goto(INICIO)
        self.page.wait_for_timeout(8000)
        if not navegador.dropi_conectado(self.page) or not self.auth.get("x-authorization"):
            navegador.marcar_sesion("dropi", False, "Sesión vencida: hay que reconectar")
            self._cm.__exit__(None, None, None)
            raise SystemExit("SESION_VENCIDA")
        navegador.marcar_sesion("dropi", True)
        return self

    def pedir(self, url, metodo, cuerpo):
        """Hace la petición desde la página de Dropi, igual que su web (el firewall bloquea otras vías)."""
        cabeceras = dict(self.auth)
        if cuerpo is not None:
            cabeceras["content-type"] = "application/json"
        return self.page.evaluate(
            """async ([url, metodo, headers, cuerpo]) => {
                const r = await fetch(url, {method: metodo, headers, body: cuerpo ?? undefined});
                return {estado: r.status, texto: await r.text()};
            }""",
            [url, metodo, cabeceras, json.dumps(cuerpo) if cuerpo is not None else None],
        )

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)


API = "https://api.dropi.co/api"
AUTH_DROPI = ["x-authorization", "x-captcha-token"]


def _objetos(r):
    if r["estado"] >= 400:
        raise RuntimeError(f"Dropi respondió {r['estado']}: {r['texto'][:150]}")
    j = a_json(r["texto"]) or {}
    return j.get("objects") if isinstance(j, dict) else j


def _numero(v, defecto=1):
    try:
        n = float(v)
        return int(n) if n.is_integer() else n
    except (TypeError, ValueError):
        return defecto


def cotizar(ids: list[str]) -> dict:
    """Cotiza el flete como el formulario «Crear orden» de Dropi, sin crear nada.

    Por cada ciudad: ciudades del departamento (trajectory/bycity), bodega de origen
    del producto (getOriginCityForCalculateShipping) y cotización por transportadora
    (cotizaEnvioTransportadoraV2). Devuelve {id: {CIUDAD: flete más barato}} y deja
    el detalle por transportadora en data/cotizaciones/<id>.json.
    """
    from playwright.sync_api import sync_playwright

    ciudades = CONFIG["precios"]["ciudades_dropi"]
    detalle_dir = DATOS / "cotizaciones"
    detalle_dir.mkdir(exist_ok=True)
    salida = {}
    with sync_playwright() as p, Sesion(p, AUTH_DROPI) as s:
        por_depto = {}
        for pid in ids:
            prod = leer_json(PRODUCTOS / f"{pid}.json", {})
            try:
                ficha = _objetos(s.pedir(f"{API}/products/productlist/v1/show/?id={pid}", "GET", None))
            except RuntimeError as e:
                salida[pid] = {}
                print(f"{pid}: sin ficha ({e})", file=sys.stderr)
                continue
            precio = (prod.get("precio_tienda") or prod.get("precio_sugerido")
                      or _numero(ficha.get("suggested_price"), 0) or (prod.get("costo") or 0) * 2)
            variacion = None
            if ficha.get("type") != "SIMPLE" and ficha.get("variations"):
                variacion = ficha["variations"][0].get("id")
            fletes, detalle = {}, {}
            for nombre, info in ciudades.items():
                try:
                    depto = info["departamento_id"]
                    if depto not in por_depto:
                        r = _objetos(s.pedir(f"{API}/trajectory/bycity", "POST",
                                             {"department_id": depto, "rate_type": "CON RECAUDO"}))
                        por_depto[depto] = r.get("cities", []) if isinstance(r, dict) else (r or [])
                    destino = next((c for c in por_depto[depto] if c.get("id") == info["id"]), None)
                    if not destino:
                        continue
                    origen = _objetos(s.pedir(f"{API}/orders/getOriginCityForCalculateShipping", "POST", {
                        "id": int(pid), "destination": f"{nombre.lower()}, {info['departamento'].lower()}",
                        "type": ficha.get("type", "SIMPLE"), "is_edit_order": False}))
                    bodega = origen["warehouse"]
                    cuerpo = {
                        "peso": _numero(ficha.get("weight")), "largo": _numero(ficha.get("length")),
                        "ancho": _numero(ficha.get("width")), "alto": _numero(ficha.get("height")),
                        "ciudad_remitente": bodega["city"], "ciudad_destino": destino,
                        "EnvioConCobro": True,
                        "products": [{**ficha, "quantity": 1, "price": precio, "variation_id": variacion}],
                        "ValorDeclarado": precio, "warehouse": bodega,
                        "zip_code": None, "colonia": None, "dir": "Calle 1 # 1-1",
                        "destination_name": "Cotizacion Prueba", "destination_phone": "3000000000",
                        "insurance": False,
                    }
                    resp = _objetos(s.pedir(f"{API}/orders/cotizaEnvioTransportadoraV2", "POST", cuerpo)) or []
                    por_transportadora = {x.get("transportadora"): (x.get("objects") or {}).get("precioEnvio")
                                          for x in resp if isinstance(x, dict)}
                    validos = [v for v in por_transportadora.values() if isinstance(v, (int, float)) and v > 0]
                    detalle[nombre] = {"origen": bodega["city"].get("name"), "transportadoras": por_transportadora}
                    if validos:
                        fletes[nombre] = int(round(min(validos)))
                except Exception as e:  # noqa: BLE001
                    detalle[nombre] = {"error": str(e)[:200]}
            escribir_json(detalle_dir / f"{pid}.json", {"cuando": ahora(), "precio_declarado": precio,
                                                       "fletes": fletes, "detalle": detalle})
            salida[pid] = fletes
    return salida


def catalogo(paginas: int) -> list[dict]:
    """Repite la búsqueda del catálogo aprendida en la calibración, página por página."""
    from playwright.sync_api import sync_playwright

    cat = (leer_json(CALIBRACION) or {}).get("catalogo")
    if not cat:
        raise SystemExit("SIN_CATALOGO")
    productos = []
    with sync_playwright() as p, Sesion(p, cat["headers_auth"]) as s:
        for n in range(paginas):
            cuerpo = copy.deepcopy(cat["cuerpo"])
            campo = cat.get("campo_pagina")
            if campo and isinstance(cuerpo, dict):
                base = cuerpo[campo] if isinstance(cuerpo[campo], int) else 0
                cuerpo[campo] = base + n * (cat["por_pagina"] if campo in ("startData", "start", "offset") else 1)
            elif n:
                break  # sin paginación conocida: solo la primera página
            r = s.pedir(cat["url"], cat["metodo"], cuerpo)
            if r["estado"] >= 400:
                break
            try:
                lista = obtener(a_json(r["texto"]), cat["ruta_lista"])
            except (KeyError, IndexError, TypeError):
                break
            if not lista:
                break
            productos.extend(x for x in lista if isinstance(x, dict))
    return productos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["calibrar", "cotizar", "catalogo", "aprender-busqueda"])
    ap.add_argument("--ids", default="")
    ap.add_argument("--paginas", type=int, default=3)
    a = ap.parse_args()
    try:
        if a.modo == "calibrar":
            calibrar()
        elif a.modo == "aprender-busqueda":
            aprender_busqueda()
        elif a.modo == "cotizar":
            print(json.dumps(cotizar([i for i in a.ids.split(",") if i])))
        else:
            print(json.dumps(catalogo(a.paginas), ensure_ascii=False))
    except navegador.Ocupado as e:
        raise SystemExit(f"OCUPADO: {e}") from None
