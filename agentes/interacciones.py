"""Bandeja FIFO para comentarios y mensajes recibidos por los webhooks de Meta."""
from __future__ import annotations

import hmac
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import redes
from comun import CONFIG, DATOS, Latido, cargar_env, leer_json, log
from meta_webhook_protocol import normalizar, verificar_firma

I = CONFIG.get("interacciones", {})
DB = DATOS / "interacciones.sqlite3"
CONTROL = DATOS / "control.json"
ESTADO = DATOS / "interacciones-estado.json"
INTENCION = re.compile(
    r"\b(send\s*me|info(?:rmaci[oó]n)?|precio|cu[aá]nto|cuanto|valor|"
    r"me interesa|interesad[oa]|quiero|m[aá]ndame|mandame|env[ií]ame|"
    r"d[oó]nde|link|env[ií]o|envio|disponible|hola|buenas)\b", re.I)
SENSIBLE = re.compile(
    r"\b(pedido|orden|reembolso|devoluci[oó]n|cancelaci[oó]n|"
    r"reclamo|queja|denuncia|estafa|no lleg[oó]|no ha llegado|demora|"
    r"retraso|pago|transferencia|factura|c[eé]dula|direcci[oó]n|"
    r"documento|identificaci[oó]n|correo|email|telefono|tel[eé]fono|"
    r"datos personales|tarjeta)\b", re.I)
CORREO = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
NUMERO_PERSONAL = re.compile(r"(?<!\d)(?:\+?57[\s.-]?)?3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
VENTAS = "https://monkey-store.onrender.com"


def _db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dedupe TEXT NOT NULL UNIQUE,
            red TEXT NOT NULL,
            tipo TEXT NOT NULL,
            externo_id TEXT NOT NULL,
            remitente TEXT,
            contexto TEXT,
            texto TEXT NOT NULL,
            evento_ms INTEGER,
            recibido TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            respuesta TEXT,
            detalle TEXT,
            atendido TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_interacciones_fifo ON interacciones(estado, recibido, id)")
    anterior = (datetime.now().astimezone() - timedelta(days=30)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM interacciones WHERE estado IN ('respondida', 'atendida') AND atendido < ?",
                 (anterior,))
    conn.commit()
    return conn


@contextmanager
def _conexion_db():
    conn = _db()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def _fecha() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _identificadores() -> tuple[str, str]:
    """Devuelve los IDs esperados sin confiar en los IDs de la notificación."""
    cargar_env()
    pagina = os.environ.get("META_PAGE_ID", "").strip()
    instagram = os.environ.get("META_IG_ID", "").strip()
    if not instagram:
        instagram = str(((leer_json(redes.HISTORIAL, {}) or {}).get("conexion") or {}).get("instagram_id") or "")
    if not pagina or not instagram:
        raise RuntimeError("Verifica Meta en el panel y configura META_PAGE_ID y META_IG_ID para aceptar webhooks")
    return pagina, instagram


def _cola_remota() -> bool:
    cargar_env()
    return bool(os.environ.get("INTERACCIONES_QUEUE_URL", "").strip())


def _llamar_cola(metodo: str, ruta: str, cuerpo: dict | None = None):
    cargar_env()
    base = os.environ.get("INTERACCIONES_QUEUE_URL", "").strip().rstrip("/")
    token = os.environ.get("INTERACCIONES_QUEUE_TOKEN", "").strip()
    if not base or len(token) < 32:
        raise RuntimeError("Configura INTERACCIONES_QUEUE_URL y un INTERACCIONES_QUEUE_TOKEN de 32+ caracteres localmente")
    data = json.dumps(cuerpo or {}).encode() if cuerpo is not None else None
    req = Request(base + ruta, data=data, method=metodo,
                  headers={"X-Queue-Token": token, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=12) as response:
            if response.status == 204:
                return None
            return json.loads(response.read())
    except HTTPError as e:
        e.close()
        raise RuntimeError(f"Servicio de cola respondió HTTP {e.code}") from e
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        raise RuntimeError(f"No se pudo consultar la cola remota: {type(e).__name__}") from e


def _actualizar_resumen_remoto() -> dict:
    datos = _llamar_cola("GET", "/internal/summary")
    return _estado(remoto=True, webhook="Render conectado", conteos=datos.get("conteos", {}),
                   revision=datos.get("revision", []), actualizado=_fecha(), ultimo_error=None)


def guardar_eventos(eventos: list[dict]) -> int:
    with _conexion_db() as conn:
        antes = conn.total_changes
        for event in eventos:
            mensaje, detalle = _respuesta(event)
            estado = "pendiente" if mensaje else "revision"
            conn.execute("""
                INSERT OR IGNORE INTO interacciones
                    (dedupe, red, tipo, externo_id, remitente, contexto, texto, evento_ms, recibido, estado, detalle)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event["dedupe"], event["red"], event["tipo"], event["externo_id"], event["remitente"],
                  event["contexto"], event["texto"], event["evento_ms"], _fecha(), estado, detalle))
        return conn.total_changes - antes


def _crear_servidor() -> ThreadingHTTPServer | None:
    cargar_env()
    secreto = os.environ.get("META_APP_SECRET", "").strip()
    verify = os.environ.get("META_WEBHOOK_VERIFY_TOKEN", "").strip()
    if not secreto or not verify:
        _estado(webhook="sin configurar", ultimo_error="Faltan META_APP_SECRET o META_WEBHOOK_VERIFY_TOKEN")
        return None

    class Webhook(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def responder(self, status: int, cuerpo: bytes, tipo: str = "text/plain; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            if (urlparse(self.path).path == "/webhook"
                    and query.get("hub.mode") == ["subscribe"]
                    and hmac.compare_digest((query.get("hub.verify_token") or [""])[0], verify)):
                return self.responder(200, (query.get("hub.challenge") or [""])[0].encode())
            self.responder(403, b"forbidden")

        def do_POST(self):
            if urlparse(self.path).path != "/webhook":
                return self.responder(404, b"not found")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.responder(400, b"invalid length")
            if length <= 0 or length > 1_000_000:
                return self.responder(413, b"payload too large")
            body = self.rfile.read(length)
            if not verificar_firma(body, self.headers.get("X-Hub-Signature-256", ""), secreto):
                return self.responder(403, b"invalid signature")
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON")
                pagina, instagram = _identificadores()
                inserted = guardar_eventos(normalizar(payload, pagina, instagram))
            except (AttributeError, TypeError, ValueError, RuntimeError, sqlite3.Error) as e:
                log("responder", f"Webhook rechazado: {e}")
                return self.responder(400, b"invalid event")
            _estado(webhook="activo", ultimo_evento=_fecha(), ultimo_error=None)
            self.responder(200, f"EVENT_RECEIVED {inserted}".encode())

    try:
        return ThreadingHTTPServer(("127.0.0.1", int(I.get("puerto", 8791))), Webhook)
    except OSError as e:
        _estado(webhook="error", ultimo_error=f"No se pudo abrir el puerto {I.get('puerto', 8791)}: {e}")
        return None


def _estado(**campos) -> dict:
    actual = leer_json(ESTADO, {}) or {}
    actual.update(campos)
    from comun import escribir_json
    escribir_json(ESTADO, actual)
    return actual


def _contexto_producto(event: dict) -> dict | None:
    h = leer_json(redes.HISTORIAL, {}) or {}
    for publicacion in reversed(h.get("publicaciones") or []):
        red = publicacion.get(event["red"]) or {}
        if str(red.get("id") or "") == str(event.get("contexto") or ""):
            pid = str(publicacion.get("producto") or "")
            if re.fullmatch(r"[\w-]+", pid):
                return leer_json(DATOS / "productos" / f"{pid}.json")
    return None


def _respuesta(event: dict) -> tuple[str | None, str]:
    if SENSIBLE.search(event["texto"]) or CORREO.search(event["texto"]) or NUMERO_PERSONAL.search(event["texto"]):
        return None, "Caso sensible o de pedido; necesita atención humana"
    if not INTENCION.search(event["texto"]):
        return None, "No coincide con una pregunta frecuente segura"
    producto = _contexto_producto(event)
    if producto:
        anuncio = producto.get("anuncio") or {}
        titulo = (anuncio.get("titulo") or producto.get("nombre") or "").strip()
        precio = (anuncio.get("precio_texto") or "").strip()
        if titulo and precio and not (producto.get("precio") or {}).get("provisional"):
            enlace = f"{VENTAS}/producto/{producto['slug']}" if producto.get("slug") else VENTAS
            telefono = CONFIG["telefono"]["actual"]
            mensaje = (f"¡Hola! {titulo}: {precio}. El envío está incluido y puedes pagar contra entrega. "
                       f"Más información: {enlace} Para confirmar disponibilidad y pedirlo, escríbenos al "
                       f"WhatsApp {telefono[:3]} {telefono[3:6]} {telefono[6:]}.")
            return mensaje, ""
        return None, "No hay precio validado para el producto relacionado"
    if event["tipo"] == "mensaje":
        return ("¡Hola! Gracias por escribir a Monkey Store. Cuéntanos qué producto viste y te compartimos "
                "su precio y detalles. No envíes datos personales ni de pago por este chat.", "")
    return None, "No se pudo relacionar el comentario con un producto publicado"


def _permitido() -> bool:
    control = leer_json(CONTROL, {}) or {}
    return bool(control.get("interacciones_habilitadas", False) and not control.get("pausado", False))


def _limite_alcanzado(conn: sqlite3.Connection) -> bool:
    inicio = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    enviados = conn.execute(
        "SELECT COUNT(*) FROM interacciones WHERE estado='respondida' AND atendido >= ?", (inicio,)).fetchone()[0]
    if enviados >= int(I.get("max_respuestas_dia", 40)):
        return True
    ultima = conn.execute(
        "SELECT MAX(atendido) FROM interacciones WHERE estado='respondida'").fetchone()[0]
    if ultima:
        espera = float(I.get("segundos_entre_respuestas", 30)) - (
            datetime.now().astimezone() - datetime.fromisoformat(ultima)).total_seconds()
        if espera > 0:
            return True
    return False


def _enviar(event: dict, mensaje: str) -> None:
    c = redes.conexion()
    if event["tipo"] == "comentario":
        ruta = f"{event['externo_id']}/replies" if event["red"] == "instagram" else f"{event['externo_id']}/comments"
        redes._llamar("POST", ruta, c["token_pagina"], {"message": mensaje})
    else:
        ruta = f"{c['ig_id']}/messages" if event["red"] == "instagram" else f"{c['pagina_id']}/messages"
        redes._llamar("POST", ruta, c["token_pagina"], {
            "recipient": {"id": event["remitente"]}, "message": {"text": mensaje},
        })


def procesar_uno() -> bool:
    if not _permitido():
        return False
    if _cola_remota():
        event = _llamar_cola("POST", "/internal/claim", {})
        if not event:
            return False
        mensaje, detalle = _respuesta(event)
        if mensaje and event["tipo"] == "mensaje" and event.get("evento_ms"):
            if time.time() * 1000 - event["evento_ms"] > 23 * 60 * 60 * 1000:
                mensaje, detalle = None, "Mensaje fuera de la ventana segura de respuesta"
        if not mensaje:
            _llamar_cola("POST", "/internal/complete", {
                "id": event["id"], "estado": "revision", "detalle": detalle,
            })
            return True
        try:
            _enviar(event, mensaje)
        except (redes.MetaError, OSError, ValueError) as e:
            _llamar_cola("POST", "/internal/complete", {
                "id": event["id"], "estado": "revision",
                "detalle": f"No se reintentó para evitar una respuesta duplicada: {str(e)[:400]}",
            })
            log("responder", f"Interacción {event['id']} enviada a revisión por error de Meta")
            return True
        _llamar_cola("POST", "/internal/complete", {
            "id": event["id"], "estado": "respondida", "respuesta": mensaje,
        })
        log("responder", f"Respuesta enviada a {event['red']} ({event['tipo']}, evento {event['id']})")
        return True
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM interacciones WHERE estado='pendiente' ORDER BY recibido, id LIMIT 1").fetchone()
        if not row:
            return False
        event = dict(row)
        mensaje, detalle = _respuesta(event)
        if not mensaje:
            conn.execute("UPDATE interacciones SET estado='revision', detalle=? WHERE id=?", (detalle, event["id"]))
            conn.commit()
            return True
        if _limite_alcanzado(conn):
            return False
        if event["tipo"] == "mensaje" and event.get("evento_ms"):
            if time.time() * 1000 - event["evento_ms"] > 23 * 60 * 60 * 1000:
                conn.execute("UPDATE interacciones SET estado='revision', detalle=? WHERE id=?",
                             ("Mensaje fuera de la ventana segura de respuesta", event["id"]))
                conn.commit()
                return True
        if event["tipo"] == "mensaje" and event.get("remitente") and mensaje.startswith(
                "¡Hola! Gracias por escribir a Monkey Store."):
            hace_24h = (datetime.now().astimezone() - timedelta(hours=24)).isoformat()
            previos = conn.execute(
                "SELECT COUNT(*) FROM interacciones WHERE remitente=? AND estado='respondida' "
                "AND respuesta LIKE '¡Hola! Gracias por escribir a Monkey Store.%' AND atendido >= ?",
                (event["remitente"], hace_24h)).fetchone()[0]
            if previos:
                conn.execute("UPDATE interacciones SET estado='revision', detalle=? WHERE id=?",
                             ("Ya se envió un mensaje inicial; continuar la conversación manualmente", event["id"]))
                conn.commit()
                return True
        try:
            _enviar(event, mensaje)
        except (redes.MetaError, OSError, ValueError) as e:
            conn.execute("UPDATE interacciones SET estado='revision', detalle=? WHERE id=?",
                         (f"No se reintentó para evitar una respuesta duplicada: {str(e)[:400]}", event["id"]))
            conn.commit()
            log("responder", f"Interacción {event['id']} enviada a revisión por error de Meta")
            return True
        conn.execute(
            "UPDATE interacciones SET estado='respondida', respuesta=?, texto='', contexto=NULL, "
            "atendido=? WHERE id=?",
            (mensaje, _fecha(), event["id"]))
        conn.commit()
        log("responder", f"Respuesta enviada a {event['red']} ({event['tipo']}, evento {event['id']})")
        return True
    finally:
        conn.close()


def resumen(maximo: int = 10) -> dict:
    if _cola_remota():
        datos = leer_json(ESTADO, {}) or {}
        conteos = datos.get("conteos") or {"pendiente": 0, "revision": 0, "respondida": 0, "atendida": 0}
        return {"conteos": conteos, "revision": datos.get("revision", [])[:maximo],
                "webhook": datos, "habilitado": _permitido()}
    with _conexion_db() as conn:
        conteos = {estado: conn.execute("SELECT COUNT(*) FROM interacciones WHERE estado=?", (estado,)).fetchone()[0]
                   for estado in ("pendiente", "revision", "respondida")}
        filas = conn.execute(
            "SELECT id, red, tipo, texto, detalle, recibido FROM interacciones "
            "WHERE estado='revision' ORDER BY recibido, id LIMIT ?", (maximo,)).fetchall()
    return {"conteos": conteos, "revision": [dict(x) for x in filas],
            "webhook": leer_json(ESTADO, {}) or {}, "habilitado": _permitido()}


def marcar_atendida(evento_id: int) -> None:
    if _cola_remota():
        _llamar_cola("POST", "/internal/attend", {"id": evento_id})
        return
    with _conexion_db() as conn:
        cur = conn.execute(
            "UPDATE interacciones SET estado='atendida', texto='', remitente=NULL, contexto=NULL, "
            "respuesta=NULL, atendido=? WHERE id=? AND estado='revision'",
                           (_fecha(), evento_id))
        if cur.rowcount != 1:
            raise ValueError("La interacción no existe o ya fue atendida")


def bucle(parar: threading.Event) -> None:
    lat = Latido("responder", None, "Filtra comentarios y mensajes; responde FAQ segura y escala el resto")
    remoto = _cola_remota()
    servidor = None if remoto else _crear_servidor()
    web = threading.Thread(target=servidor.serve_forever, daemon=True) if servidor else None
    if servidor and web:
        web.start()
        _estado(webhook="activo", puerto=I.get("puerto", 8791), ultimo_error=None)
    elif remoto:
        _estado(remoto=True, webhook="conectando a Render",
                conteos={"pendiente": 0, "revision": 0, "respondida": 0, "atendida": 0}, revision=[])
    ultimo = 0.0
    sincronizado = 0.0
    try:
        while not parar.is_set():
            try:
                trabajo = procesar_uno()
                if remoto and (trabajo or time.monotonic() - sincronizado >= 30):
                    _actualizar_resumen_remoto()
                    sincronizado = time.monotonic()
                lat.set("trabajando" if trabajo else ("esperando" if _permitido() else "pausado"),
                        "Atendiendo interacciones en orden de llegada" if trabajo else
                        ("Esperando nuevas interacciones" if _permitido() else "Respuestas automáticas desactivadas"))
                s = resumen(0) if not remoto else leer_json(ESTADO, {}) or {}
                estado_webhook = (s.get("webhook") if remoto else (s.get("webhook") or {}).get("webhook"))
                lat.set(resumen={**(s.get("conteos") or {}),
                                 "webhook": estado_webhook or "sin configurar"})
            except (OSError, sqlite3.Error, RuntimeError, HTTPError) as e:
                lat.error(str(e))
                log("responder", f"ERROR en bandeja: {e}")
                trabajo = False
            if trabajo:
                ultimo = time.monotonic()
                continue
            if remoto:
                parar.wait(float(I.get("segundos_revision_remota", 10)))
            else:
                parar.wait(1 if time.monotonic() - ultimo >= float(I.get("segundos_entre_respuestas", 30))
                           else min(1, float(I.get("segundos_entre_respuestas", 30)) -
                                    (time.monotonic() - ultimo)))
    finally:
        if servidor:
            servidor.shutdown()
            servidor.server_close()
        lat.set("detenido", "")
