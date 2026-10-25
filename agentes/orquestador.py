"""Orquestador de los agentes de Monkey Store. Lo corre launchd (ver instalar.sh).

Dos agentes en paralelo, cada uno con su modelo local:

  analista  (qwen-tools)  trae catálogo, evalúa productos, cotiza flete y pone precio
  redactor  (gemma-work)  escribe el anuncio de Marketplace y lo deja en la cola

Cada producto es un archivo en agentes/data/productos/<id>.json que avanza por etapas:

  nuevo -> evaluado -> con_precio -> en_cola -> publicado
              \\-> descartado

El paso a «publicado» lo das tú desde el panel, después de publicar en Facebook.
Reglas del negocio: docs/MODELO-DE-NEGOCIO.md
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import fuentes
import interacciones
import precios
import redes
from comun import (AGENTES, CONFIG, DATOS, LATIDOS, PRODUCTOS, RAIZ, Latido, ahora, chat_json,
                   escribir_json, leer_json, log, ollama_vivo)

ESTADO = DATOS / "estado.json"
FLETES_MANUALES = DATOS / "fletes_manuales.json"
# Lo escriben el panel y la app de la barra de menú: {"pausado": bool, "despertar": "<iso>"}
CONTROL = DATOS / "control.json"
SESIONES = DATOS / "sesiones.json"
CANDADO = threading.Lock()
# Con la RAM libre de este Mac no caben los dos modelos a la vez: Ollama descarga uno para
# cargar el otro. El turno hace que cada agente procese su lote entero antes de ceder,
# así hay un cambio de modelo por lote y no uno por petición.
TURNO = threading.Lock()
PARAR = threading.Event()
ETAPAS = ["nuevo", "evaluado", "con_precio", "en_cola", "publicado", "descartado"]


# ---------------------------------------------------------------------------
# Productos en disco
# ---------------------------------------------------------------------------

def productos(etapa: str | None = None) -> list[dict]:
    out = []
    for f in sorted(PRODUCTOS.glob("*.json")):
        p = leer_json(f)
        if p and (etapa is None or p.get("etapa") == etapa):
            out.append(p)
    return out


def guardar(p: dict, etapa: str | None = None, nota: str = "") -> None:
    with CANDADO:
        # Releer por si el panel lo marcó como publicado mientras trabajábamos.
        actual = leer_json(PRODUCTOS / f"{p['id']}.json", {})
        if actual.get("etapa") in ("publicado", "descartado") and etapa not in ("publicado", "descartado"):
            p["etapa"] = actual["etapa"]
            etapa = None
        if etapa and etapa != p.get("etapa"):
            p["etapa"] = etapa
            p.setdefault("historial", []).append({"cuando": ahora(), "etapa": etapa, "nota": nota[:200]})
        p["actualizado"] = ahora()
        escribir_json(PRODUCTOS / f"{p['id']}.json", p)


class turno:
    def __init__(self, lat: Latido):
        self.lat = lat

    def __enter__(self):
        if not TURNO.acquire(blocking=False):
            self.lat.set("esperando", "Esperando turno: el otro agente está usando la memoria")
            TURNO.acquire()
        return self

    def __exit__(self, *exc):
        TURNO.release()


def control() -> dict:
    return leer_json(CONTROL, {}) or {}


def pausado() -> bool:
    return bool(control().get("pausado"))


def esperar(segundos: float) -> None:
    """Duerme, pero despierta antes si piden «trabajar ahora», si pausan o si se apaga."""
    inicio = control()
    fin = time.time() + segundos
    while time.time() < fin and not PARAR.is_set():
        actual = control()
        if actual.get("despertar") != inicio.get("despertar") or actual.get("pausado") != inicio.get("pausado"):
            return
        PARAR.wait(3)


def conteo() -> dict:
    c = {e: 0 for e in ETAPAS}
    for p in productos():
        c[p.get("etapa", "nuevo")] = c.get(p.get("etapa", "nuevo"), 0) + 1
    return c


def pesos(v) -> str:
    return "$" + f"{int(v):,}".replace(",", ".") if v else "—"


# ---------------------------------------------------------------------------
# Analista (qwen-tools)
# ---------------------------------------------------------------------------

SISTEMA_ANALISTA = """Eres el analista de productos de una tienda de dropshipping en Colombia que vende
por Facebook Marketplace con pago contra entrega. Evalúas si vale la pena publicar un producto de Dropi.

NO evalúes el margen ni hagas cuentas: el precio y la ganancia se calculan aparte con una fórmula fija.
Evalúa solo:
- demanda en Colombia y si la gente lo compra por impulso en Marketplace;
- que se entienda fácil en una foto;
- riesgo de devolución (tallas, fragilidad, expectativas difíciles de cumplir);
- stock, si viene el dato.

prohibido_marketplace=true SOLO si es suplemento, vitamina, medicamento, producto con promesas médicas,
arma, producto para adultos, animal vivo o una réplica. Una marca conocida en el nombre NO es réplica
por sí sola: solo lo es si los datos dicen "réplica", "tipo", "AAA", "1.1" o algo así.

decision: "publicar" si es buen producto, "revisar" si tienes dudas, "descartar" solo si está
prohibido o es claramente difícil de vender (puntaje menor a 40).
Responde solo con el JSON pedido, en español."""

ESQUEMA_EVALUACION = {
    "type": "object",
    "properties": {
        "puntaje": {"type": "integer", "minimum": 0, "maximum": 100},
        "decision": {"type": "string", "enum": ["publicar", "revisar", "descartar"]},
        "razon": {"type": "string"},
        "publico_objetivo": {"type": "string"},
        "prohibido_marketplace": {"type": "boolean"},
    },
    "required": ["puntaje", "decision", "razon", "publico_objetivo", "prohibido_marketplace"],
}


# Red de seguridad: el modelo pequeño a veces deja pasar productos prohibidos en Marketplace.
PROHIBIDOS = re.compile(
    r"\b(vitamin\w*|suplement\w*|gomitas?|gummies|col[aá]geno|c[aá]psulas?|tabletas?|medicament\w*|"
    r"prote[ií]na|creatina|magnesio|omega\s*3|cbd|cannabis|keto|adelgaz\w*|quema\s*grasa|"
    r"r[eé]plica|aaa|1\.1|arma\w*|pistola\s+de\s+(aire|balines)|navaja|er[oó]tic\w*|sexual\w*|vape|vaper|"
    r"cigarr\w*|perfume\w*|fragancia\w*)\b", re.I)


def evaluar(p: dict) -> dict:
    datos = {
        "nombre": p["nombre"], "categoria": p.get("categoria"), "costo_proveedor": p.get("costo"),
        "precio_sugerido_dropi": p.get("precio_sugerido"), "precio_actual_tienda": p.get("precio_tienda"),
        "stock": p.get("stock"), "descripcion": (p.get("descripcion") or "")[:700],
    }
    r = chat_json(CONFIG["modelos"]["analista"], SISTEMA_ANALISTA,
                  "Evalúa este producto:\n" + json.dumps(datos, ensure_ascii=False), ESQUEMA_EVALUACION)
    encontrado = PROHIBIDOS.search(f"{p.get('nombre', '')} {p.get('categoria') or ''}")
    if encontrado and "pistola de masaje" not in p.get("nombre", "").lower():
        r["prohibido_marketplace"] = True
        r["razon"] = f"Prohibido en Marketplace («{encontrado.group(0)}»). " + r.get("razon", "")
    if r.get("prohibido_marketplace"):
        r["decision"] = "descartar"
    elif r["decision"] == "descartar" and r["puntaje"] >= 40:
        r["decision"] = "revisar"  # sin prohibición, la última palabra es tuya
    return r


def cotizar_lote(ids: list[str]) -> tuple[dict, str | None]:
    """Llama al cotizador (Playwright). Devuelve ({id: {ciudad: flete}}, bloqueo)."""
    manual = leer_json(FLETES_MANUALES, {}) or {}
    resultado = {i: manual[i] for i in ids if manual.get(i)}
    faltan = [i for i in ids if i not in resultado]
    if not faltan:
        return resultado, None
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    proc = subprocess.run(
        [uv, "run", "--quiet", "--with", "playwright==1.60.0", "python", str(AGENTES / "cotizador.py"),
         "cotizar", "--ids", ",".join(faltan)],
        cwd=AGENTES, capture_output=True, text=True, timeout=900,
    )
    salida = (proc.stdout or "").strip().splitlines()
    if proc.returncode != 0:
        motivo = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["error"]
        if "SESION_VENCIDA" in motivo[0]:
            return resultado, "La sesión de Dropi se cayó: usa «Reconectar Dropi» en el panel"
        if "OCUPADO" in motivo[0]:
            return resultado, None  # el navegador de Dropi está en uso; se reintenta en el próximo ciclo
        return resultado, f"Cotizador falló: {motivo[0][:200]}"
    try:
        resultado.update(json.loads(salida[-1]))
    except (IndexError, json.JSONDecodeError):
        return resultado, "El cotizador no devolvió datos legibles"
    return resultado, None


def poner_precio(p: dict, fletes: dict | None) -> None:
    referencia = p.get("precio_tienda") or p.get("precio_sugerido")
    p["fletes"] = fletes or None
    p["precio"] = precios.calcular(int(p.get("costo") or 0), fletes or None, referencia)
    if p.get("anuncio") and p["precio"].get("precio"):
        p["anuncio"]["precio"] = p["precio"]["precio"]
        p["anuncio"]["precio_texto"] = pesos(p["precio"]["precio"])


def ciclo_analista(lat: Latido) -> bool:
    """Un ciclo. Devuelve True si hizo algo (para no dormir si queda trabajo)."""
    estado = leer_json(ESTADO, {}) or {}
    bloqueos: list[str] = []
    trabajo = False

    # 1. Catálogo de Dropi cada N horas
    ultimo = estado.get("catalogo_ultimo")
    vence = datetime.fromisoformat(ultimo) + timedelta(hours=CONFIG["catalogo_cada_horas"]) if ultimo else None
    pedido = control().get("despertar") or ""  # «Trabajar ahora» también refresca el catálogo
    if not vence or datetime.now().astimezone() >= vence or pedido > (ultimo or ""):
        lat.set("trabajando", "Buscando productos nuevos en Dropi")
        errores = []
        try:
            n = fuentes.traer_catalogo_dropi()
            log("analista", f"Catálogo Dropi (API): {n} productos nuevos")
        except Exception as e:  # noqa: BLE001
            errores.append(str(e))
            try:
                lat.set("trabajando", "Buscando productos top con la sesión web de Dropi")
                n = fuentes.traer_catalogo_web()
                log("analista", f"Catálogo Dropi (web): {n} productos nuevos")
                errores = []
            except Exception as e2:  # noqa: BLE001
                errores.append(str(e2))
        if errores:
            estado["catalogo_error"] = "Sin productos nuevos de Dropi. " + " · ".join(errores)
            # Reintenta en 30 min (no en cada ciclo), por si reconectas o pegas un token nuevo.
            reintento = datetime.now().astimezone() - timedelta(hours=CONFIG["catalogo_cada_horas"], minutes=-30)
            estado["catalogo_ultimo"] = reintento.isoformat(timespec="seconds")
        else:
            estado.pop("catalogo_error", None)
            estado["catalogo_ultimo"] = ahora()
        escribir_json(ESTADO, estado)
    if estado.get("catalogo_error"):
        bloqueos.append(estado["catalogo_error"])

    # 2. Evaluar productos nuevos
    nuevos = productos("nuevo")[: CONFIG["lote_por_ciclo"]]
    if nuevos:
        with turno(lat):
            for p in nuevos:
                if PARAR.is_set() or pausado():
                    break
                lat.set("trabajando", f"Evaluando: {p['nombre']}")
                try:
                    ev = evaluar(p)
                    p["evaluacion"] = {**ev, "modelo": CONFIG["modelos"]["analista"], "cuando": ahora()}
                    destino = "descartado" if ev["decision"] == "descartar" else "evaluado"
                    guardar(p, destino, f"{ev['decision']} ({ev['puntaje']}): {ev['razon']}")
                    log("analista", f"{p['nombre']}: {ev['decision']} ({ev['puntaje']})")
                    lat.hecho()
                    trabajo = True
                except Exception as e:  # noqa: BLE001
                    lat.error(f"Evaluando {p['nombre']}: {e}")
                    log("analista", f"ERROR evaluando {p['id']}: {e}")

    # 3. Cotizar y poner precio (evaluados, y re-cotizar los que quedaron con precio provisional)
    pendientes = productos("evaluado")[: CONFIG["lote_por_ciclo"]]
    provisionales = [p for e in ("con_precio", "en_cola") for p in productos(e)
                     if (p.get("precio") or {}).get("provisional")]
    lote = pendientes + provisionales[: CONFIG["lote_por_ciclo"]]
    if lote and not PARAR.is_set():
        lat.set("trabajando", f"Cotizando flete de {len(lote)} productos en {', '.join(CONFIG['precios']['ciudades'])}")
        fletes, bloqueo = cotizar_lote([p["id"] for p in lote])
        if bloqueo:
            bloqueos.append(bloqueo)
        for p in lote:
            f = fletes.get(p["id"]) or None
            if p["etapa"] != "evaluado" and not f:
                continue  # sigue provisional; no hay nada nuevo que guardar
            poner_precio(p, f)
            nota = (f"{pesos(p['precio'].get('precio'))} "
                    f"{'provisional' if p['precio'].get('provisional') else 'con flete promedio ' + pesos(p['precio'].get('flete_promedio'))}")
            guardar(p, "con_precio" if p["etapa"] == "evaluado" else None, nota)
            trabajo = True

    bloqueos += verificar_telefonos()
    if (leer_json(SESIONES, {}) or {}).get("dropi", {}).get("ok") is False:
        bloqueos.append("La sesión de Dropi del navegador se cayó: usa «Reconectar Dropi» en el panel")

    lat.bloqueos(bloqueos)
    lat.set(resumen=conteo())
    return trabajo


def verificar_telefonos() -> list[str]:
    """Busca los números prohibidos en el código de la tienda y en los anuncios.

    En los anuncios los corrige solo; en el código avisa (los cambios de código los revisas tú).
    """
    tel = CONFIG.get("telefono") or {}
    prohibidos = [re.sub(r"\D", "", n) for n in tel.get("prohibidos", [])]
    if not prohibidos:
        return []
    patron = re.compile("|".join(r"\D?".join(n) for n in prohibidos))
    avisos = []
    archivos = [f for carpeta in ("src", "docs", "public") for f in (RAIZ / carpeta).rglob("*")
                if f.is_file() and f.suffix in (".js", ".ts", ".astro", ".json", ".md", ".html", ".xml", ".txt")]
    en_codigo = [str(f.relative_to(RAIZ)) for f in archivos if patron.search(f.read_text(errors="ignore"))]
    if en_codigo:
        avisos.append(f"El número viejo sigue en: {', '.join(en_codigo[:5])}")
    for p in productos("en_cola"):
        a = p.get("anuncio") or {}
        texto = f"{a.get('titulo', '')}\n{a.get('descripcion', '')}"
        if patron.search(texto):
            a["titulo"] = patron.sub(tel["actual"], a.get("titulo", ""))
            a["descripcion"] = patron.sub(tel["actual"], a.get("descripcion", ""))
            guardar(p, None, "Teléfono viejo corregido")
            log("analista", f"Teléfono viejo corregido en el anuncio de {p['nombre']}")
    return avisos


# ---------------------------------------------------------------------------
# Redactor (gemma-work)
# ---------------------------------------------------------------------------

SISTEMA_REDACTOR = """Eres el redactor de anuncios de Facebook Marketplace de una tienda colombiana
que vende con pago contra entrega y envío incluido. Escribes en español de Colombia, cercano y claro.

Reglas:
- Título de máximo 80 caracteres: nombre real del producto y su beneficio principal. Sin emojis ni mayúsculas sostenidas.
- Descripción de 4 a 8 líneas: qué es, para qué sirve, qué incluye, 3 o 4 viñetas con «•».
- No inventes características que no estén en los datos. Nada de promesas médicas.
- No pongas teléfonos, enlaces ni precios dentro de la descripción.
- Categoría según el uso: fitness/ejercicio -> Deportes y actividades al aire libre; audio, cámaras,
  relojes, luces, proyectores -> Electrónica y computadoras; cargadores y accesorios de celular -> Celulares;
  cosas de la casa -> Artículos para el hogar.
- foto_con_telefono_ajeno = true si la foto muestra un número de teléfono, un WhatsApp, un logo o una
  marca de agua de otro vendedor.
- Termina siempre con estas dos líneas exactas:
  ✅ Pago contra entrega en toda Colombia
  🚚 Envío incluido
Responde solo con el JSON pedido."""

CATEGORIAS_FB = CONFIG["marketplace"]["categorias"]

ESQUEMA_ANUNCIO = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "descripcion": {"type": "string"},
        "categoria": {"type": "string", "enum": CATEGORIAS_FB},
        "etiquetas": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "foto_con_telefono_ajeno": {"type": "boolean"},
    },
    "required": ["titulo", "descripcion", "categoria", "etiquetas", "foto_con_telefono_ajeno"],
}

ESQUEMA_FOTO = {
    "type": "object",
    "properties": {"foto_con_telefono_ajeno": {"type": "boolean"}, "que_se_ve": {"type": "string"}},
    "required": ["foto_con_telefono_ajeno", "que_se_ve"],
}

# Nombres viejos -> categorías reales del formulario de Marketplace
CATEGORIAS_VIEJAS = {
    "Electrónica": "Electrónica y computadoras", "Celulares y accesorios": "Celulares",
    "Artículos deportivos": "Deportes y actividades al aire libre", "Hogar": "Artículos para el hogar",
    "Accesorios para vehículos": "Repuestos para autos", "Mascotas": "Artículos para mascotas",
    "Ropa y accesorios": "Joyas y accesorios",
}


def primera_imagen(p: dict) -> list[bytes]:
    for url in p.get("imagenes") or []:
        try:
            seguro = urllib.parse.quote(url, safe=":/")
            with urllib.request.urlopen(seguro, timeout=20) as r:
                if r.headers.get_content_type() in ("image/jpeg", "image/png"):
                    return [r.read()]
        except OSError:
            continue
    return []


def limpiar_anuncio(a: dict) -> dict:
    tmax = CONFIG["marketplace"]["titulo_max"]
    titulo = re.sub(r"\s+", " ", a["titulo"]).strip().strip('"')
    if len(titulo) > tmax:
        titulo = titulo[:tmax].rsplit(" ", 1)[0]
    desc = a["descripcion"].strip()
    desc = re.sub(r"(https?://\S+|www\.\S+)", "", desc)
    desc = re.sub(r"\+?\d[\d\s-]{8,}\d", "", desc)  # teléfonos
    for frase, icono in zip(CONFIG["marketplace"]["frases_fijas"], ("✅", "🚚")):
        if frase.lower() not in desc.lower():
            desc += f"\n{icono} {frase}"
    return {**a, "titulo": titulo, "descripcion": desc}


def revisar_cola(lat: Latido) -> bool:
    """Pone al día los anuncios viejos de la cola: categoría real y foto sin teléfonos ajenos."""
    trabajo = False
    for p in productos("en_cola"):
        if PARAR.is_set() or pausado():
            break
        a = p.get("anuncio") or {}
        if a.get("categoria") in CATEGORIAS_VIEJAS:
            a["categoria"] = CATEGORIAS_VIEJAS[a["categoria"]]
            guardar(p, None, "Categoría ajustada a Marketplace")
        if a.get("foto_revisada"):
            continue
        lat.set("trabajando", f"Revisando la foto de: {p['nombre']}")
        imagen = primera_imagen(p)
        if imagen:
            try:
                r = chat_json(CONFIG["modelos"]["redactor"],
                              "Revisas fotos de productos para Marketplace. Responde solo el JSON.",
                              "¿La foto muestra un número de teléfono, WhatsApp, logo o marca de agua de otro "
                              "vendedor? Describe en una frase qué se ve.", ESQUEMA_FOTO, imagenes=imagen)
                a["foto_con_telefono_ajeno"] = bool(r["foto_con_telefono_ajeno"])
            except Exception as e:  # noqa: BLE001
                lat.error(f"Revisando foto de {p['nombre']}: {e}")
                continue
        a["foto_revisada"] = True
        guardar(p, None, "Foto revisada")
        if a.get("foto_con_telefono_ajeno"):
            log("redactor", f"La foto principal de {p['nombre']} trae teléfono o marca ajena: se usará la siguiente")
        trabajo = True
    return trabajo


def ciclo_redactor(lat: Latido) -> bool:
    trabajo = False
    lote = [p for p in productos("con_precio")
            if (p.get("evaluacion") or {}).get("decision") != "descartar" and (p.get("precio") or {}).get("precio")]
    lote = lote[: CONFIG["lote_por_ciclo"]]
    if not lote:
        with turno(lat):
            trabajo = revisar_cola(lat)
        lat.set(resumen={"en_cola": len(productos("en_cola"))})
        return trabajo
    with turno(lat):
        trabajo = redactar_lote(lat, lote)
    lat.set(resumen={"en_cola": len(productos("en_cola"))})
    return trabajo


def redactar_lote(lat: Latido, lote: list[dict]) -> bool:
    trabajo = False
    for p in lote:
        if PARAR.is_set() or pausado():
            break
        lat.set("trabajando", f"Redactando anuncio: {p['nombre']}")
        try:
            datos = {
                "nombre": p["nombre"], "categoria": p.get("categoria"),
                "descripcion_proveedor": (p.get("descripcion") or "")[:900],
                "destacados": p.get("destacados") or [],
                "publico_objetivo": (p.get("evaluacion") or {}).get("publico_objetivo"),
            }
            a = chat_json(CONFIG["modelos"]["redactor"], SISTEMA_REDACTOR,
                          "Escribe el anuncio para este producto (la foto es del proveedor):\n"
                          + json.dumps(datos, ensure_ascii=False),
                          ESQUEMA_ANUNCIO, imagenes=primera_imagen(p))
            a = limpiar_anuncio(a)
            p["anuncio"] = {
                **a,
                "precio": p["precio"]["precio"],
                "precio_texto": pesos(p["precio"]["precio"]),
                "estado": "Nuevo",
                "fotos": p.get("imagenes_locales") or [],
                "fotos_url": p.get("imagenes") or [],
                "modelo": CONFIG["modelos"]["redactor"],
                "creado": ahora(),
                "foto_revisada": True,
            }
            guardar(p, "en_cola", a["titulo"])
            log("redactor", f"Anuncio listo: {a['titulo']} {pesos(p['precio']['precio'])}")
            lat.hecho()
            trabajo = True
        except Exception as e:  # noqa: BLE001
            lat.error(f"Redactando {p['nombre']}: {e}")
            log("redactor", f"ERROR redactando {p['id']}: {e}")
    return trabajo


# ---------------------------------------------------------------------------
# Publicista (gemma-work): Página de Facebook e Instagram de Monkey Store
# ---------------------------------------------------------------------------

def ciclo_publicista(lat: Latido) -> bool:
    """En cada turno del día (config redes.horas) publica un producto con la API oficial de Meta."""
    resumen = {"próximo turno": redes.proximo_turno() or "—",
               "publicados": len((leer_json(redes.HISTORIAL, {}) or {}).get("publicaciones", []))}
    if control().get("redes_pausado"):
        lat.set("pausado", "Publicación en redes pausada desde el panel", resumen=resumen)
        lat.bloqueos([])
        return False
    try:
        redes.credenciales()
    except redes.MetaError as e:
        lat.bloqueos([str(e)])
        lat.set("bloqueado", "Esperando la conexión con Meta (Página e Instagram de Monkey Store)", resumen=resumen)
        return False
    conexion = (leer_json(redes.HISTORIAL, {}) or {}).get("conexion") or {}
    revisada = conexion.get("cuando")
    if not revisada or datetime.fromisoformat(revisada) < datetime.now().astimezone() - timedelta(hours=1):
        conexion = redes.verificar()
    if not conexion.get("ok"):
        lat.bloqueos([f"Meta: {conexion.get('error')}"])
        lat.set("bloqueado", "La conexión con Meta falló", resumen=resumen)
        return False
    lat.bloqueos([conexion["aviso"]] if conexion.get("aviso") else [])

    turno_hora = redes.turno_pendiente()
    if turno_hora is None:
        lat.set("esperando", f"Próxima publicación {resumen['próximo turno']} en "
                             f"{conexion.get('pagina')} / @{conexion.get('instagram') or '—'}", resumen=resumen)
        return False
    p = redes.elegir()
    if not p:
        redes.marcar_turno(turno_hora, "Sin productos con precio cotizado")
        lat.bloqueos(["No hay productos listos para redes: necesitan precio con flete cotizado (no provisional)"])
        return False
    with turno(lat):
        lat.set("trabajando", f"Publicando en Página e Instagram: {p['nombre']}", resumen=resumen)
        try:
            r = redes.publicar(p)
            redes.marcar_turno(turno_hora, f"Publicado: {p['nombre']}")
            log("publicista", f"Publicado {p['nombre']}: FB {(r.get('facebook') or {}).get('url')} "
                              f"IG {(r.get('instagram') or {}).get('url')}")
            lat.hecho()
        except Exception as e:  # noqa: BLE001
            redes.marcar_turno(turno_hora, f"Error: {e}")
            lat.error(f"Publicando {p['nombre']}: {e}")
            log("publicista", f"ERROR publicando {p['id']}: {e}")
    return True


# ---------------------------------------------------------------------------
# Bucle
# ---------------------------------------------------------------------------

def bucle(nombre: str, rol: str, ciclo) -> None:
    modelo = CONFIG["modelos"][nombre]
    lat = Latido(nombre, modelo, rol)
    while not PARAR.is_set():
        if pausado():
            if lat.datos["estado"] != "pausado":
                log(nombre, "Pausado desde el panel")
            lat.set("pausado", "Pausado. Dale «Seguir» en el panel o en la barra de menú.")
            esperar(3600)
            continue
        try:
            if not ollama_vivo():
                lat.set("bloqueado", "Ollama no responde en " + CONFIG["ollama_url"])
                lat.bloqueos(["Ollama apagado: abre la app de Ollama"])
                esperar(60)
                continue
            hizo = ciclo(lat)
        except Exception as e:  # noqa: BLE001
            lat.error(f"{e}\n{traceback.format_exc()[-400:]}")
            log(nombre, f"ERROR en ciclo: {e}")
            hizo = False
        if hizo:
            continue
        # El redactor depende de lo que deje el analista: revisa cada minuto.
        espera = 60 if nombre in ("redactor", "publicista") else CONFIG["ciclo_segundos"]
        siguiente = datetime.now() + timedelta(seconds=espera)
        if nombre != "publicista":  # el publicista ya dejó su propio estado
            estado = "bloqueado" if lat.datos["bloqueos"] and nombre == "analista" and not productos("nuevo") else "esperando"
            lat.set(estado, f"Sin trabajo pendiente. Próxima revisión {siguiente:%H:%M}", siguiente=siguiente.isoformat())
        esperar(espera)
    lat.set("detenido", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--una-vez", action="store_true", help="un ciclo de cada agente y salir")
    a = ap.parse_args()

    n = fuentes.sembrar_desde_tienda()
    if n:
        log("orquestador", f"Sembrados {n} productos desde src/data/products.json")

    if a.una_vez:
        ciclo_analista(Latido("analista", CONFIG["modelos"]["analista"], "Evalúa, cotiza y pone precio"))
        ciclo_redactor(Latido("redactor", CONFIG["modelos"]["redactor"], "Redacta anuncios de Marketplace"))
        for nombre in ("analista", "redactor"):
            lat = Latido.__new__(Latido)
            lat.ruta = LATIDOS / f"{CONFIG['proyecto']}__{nombre}.json"
            lat.datos = leer_json(lat.ruta, {})
            lat.set("detenido", "Prueba de un ciclo terminada")
        return

    hilos = [
        threading.Thread(target=bucle, args=("analista", "Evalúa, cotiza y pone precio", ciclo_analista), daemon=True),
        threading.Thread(target=bucle, args=("redactor", "Redacta anuncios de Marketplace", ciclo_redactor), daemon=True),
        threading.Thread(target=bucle, args=("publicista", "Publica en la Página y el Instagram de Monkey Store",
                                             ciclo_publicista), daemon=True),
        threading.Thread(target=interacciones.bucle, args=(PARAR,), daemon=True),
    ]
    for h in hilos:
        h.start()
    try:
        while any(h.is_alive() for h in hilos):
            time.sleep(5)
    except KeyboardInterrupt:
        PARAR.set()
        for h in hilos:
            h.join(timeout=30)


if __name__ == "__main__":
    main()
