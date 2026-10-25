"""Webhook HTTPS público de Meta y cola compartida en Render PostgreSQL."""
from __future__ import annotations

import hmac
import json
import os
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import panel_auth
from meta_webhook_protocol import normalizar, verificar_firma

CONFIG = json.loads((Path(__file__).with_name("config.json")).read_text())
PANEL_HTML = Path(__file__).with_name("panel_remoto.html")
PANEL_MANIFEST = Path(__file__).with_name("panel.webmanifest")
PANEL_ICON = Path(__file__).with_name("panel-icon.svg")


def _db():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("Falta DATABASE_URL")
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(url, connect_timeout=5, row_factory=dict_row)


def preparar_db() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS interacciones (
                id BIGSERIAL PRIMARY KEY,
                dedupe TEXT NOT NULL UNIQUE,
                red TEXT NOT NULL,
                tipo TEXT NOT NULL,
                externo_id TEXT NOT NULL,
                remitente TEXT,
                contexto TEXT,
                texto TEXT NOT NULL,
                evento_ms BIGINT,
                recibido TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                estado TEXT NOT NULL DEFAULT 'pendiente',
                respuesta TEXT,
                detalle TEXT,
                atendido TIMESTAMPTZ,
                reservado_hasta TIMESTAMPTZ
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS interacciones_fifo ON interacciones(estado, recibido, id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS panel_estado (
                id SMALLINT PRIMARY KEY CHECK (id = 1),
                payload JSONB NOT NULL,
                actualizado TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS panel_comandos (
                id BIGSERIAL PRIMARY KEY,
                accion TEXT NOT NULL CHECK (accion IN ('iniciar', 'detener')),
                estado TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'procesando', 'completado', 'fallido')),
                creado TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reservado_hasta TIMESTAMPTZ,
                terminado TIMESTAMPTZ,
                detalle TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS panel_comandos_fifo ON panel_comandos(estado, id)")


def _guardar(eventos: list[dict]) -> int:
    with _db() as conn:
        _limpiar(conn)
        insertados = 0
        for event in eventos:
            cur = conn.execute(
                "INSERT INTO interacciones "
                "(dedupe, red, tipo, externo_id, remitente, contexto, texto, evento_ms) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT(dedupe) DO NOTHING",
                (event["dedupe"], event["red"], event["tipo"], event["externo_id"], event["remitente"],
                 event["contexto"], event["texto"], event["evento_ms"]))
            insertados += cur.rowcount
        return insertados


def _resumen() -> dict:
    estados = ("pendiente", "revision", "respondida", "atendida")
    with _db() as conn:
        _limpiar(conn)
        conteos = {estado: conn.execute(
            "SELECT COUNT(*) AS cantidad FROM interacciones WHERE estado=%s", (estado,)).fetchone()["cantidad"]
                   for estado in estados}
        revision = conn.execute(
            "SELECT id, red, tipo, texto, detalle, recibido FROM interacciones "
            "WHERE estado='revision' ORDER BY recibido, id LIMIT 10").fetchall()
    return {"conteos": conteos, "revision": [
        {**event, "recibido": event["recibido"].isoformat()} for event in revision
    ]}


def _limpiar(conn) -> None:
    conn.execute(
        "DELETE FROM interacciones WHERE estado IN ('respondida', 'atendida') "
        "AND atendido < NOW() - INTERVAL '30 days'")


def _reclamar() -> dict | None:
    config = CONFIG.get("interacciones", {})
    maximo = int(config.get("max_respuestas_dia", 40))
    pausa = int(config.get("segundos_entre_respuestas", 30))
    with _db() as conn:
        _limpiar(conn)
        conn.execute(
            "UPDATE interacciones SET estado='revision', detalle=%s, atendido=NOW(), reservado_hasta=NULL "
            "WHERE estado='procesando' AND reservado_hasta < NOW()",
            ("El agente local dejó vencer la reserva; revisar antes de responder",))
        limite = conn.execute(
            "SELECT COUNT(*) AS cantidad, MAX(atendido) AS ultima FROM interacciones "
            "WHERE estado='respondida' AND atendido >= CURRENT_DATE").fetchone()
        if limite["cantidad"] >= maximo or (
                limite["ultima"] and (conn.execute(
                    "SELECT EXTRACT(EPOCH FROM (NOW() - %s)) AS segundos", (limite["ultima"],)
                ).fetchone()["segundos"] < pausa)):
            return None
        event = conn.execute(
            "SELECT id, red, tipo, externo_id, remitente, contexto, texto, evento_ms, recibido "
            "FROM interacciones WHERE estado='pendiente' "
            "ORDER BY COALESCE(to_timestamp(evento_ms / 1000.0), recibido), recibido, id "
            "LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        if not event:
            return None
        conn.execute(
            "UPDATE interacciones SET estado='procesando', reservado_hasta=NOW() + INTERVAL '15 minutes' "
            "WHERE id=%s", (event["id"],))
        event["recibido"] = event["recibido"].isoformat()
        return event


def _completar(datos: dict) -> None:
    evento_id = datos.get("id")
    estado = datos.get("estado")
    if type(evento_id) is not int or evento_id < 1 or estado not in ("respondida", "revision"):
        raise ValueError("Datos de finalización inválidos")
    respuesta = str(datos.get("respuesta") or "")[:2000] or None
    detalle = str(datos.get("detalle") or "")[:500] or None
    with _db() as conn:
        cur = conn.execute(
            "UPDATE interacciones SET estado=%s, respuesta=%s, detalle=%s, "
            "texto=CASE WHEN %s='respondida' THEN '' ELSE texto END, "
            "contexto=CASE WHEN %s='respondida' THEN NULL ELSE contexto END, atendido=NOW(), "
            "reservado_hasta=NULL WHERE id=%s AND estado='procesando' RETURNING id",
            (estado, respuesta, detalle, estado, estado, evento_id))
        if not cur.fetchone():
            raise ValueError("La interacción no existe o perdió su reserva")


def _atender(datos: dict) -> None:
    evento_id = datos.get("id")
    if type(evento_id) is not int or evento_id < 1:
        raise ValueError("Interacción inválida")
    with _db() as conn:
        cur = conn.execute(
            "UPDATE interacciones SET estado='atendida', texto='', remitente=NULL, contexto=NULL, "
            "respuesta=NULL, atendido=NOW() "
            "WHERE id=%s AND estado='revision' RETURNING id", (evento_id,))
        if not cur.fetchone():
            raise ValueError("La interacción no existe o ya fue atendida")


def _validar_estado_panel(datos: dict) -> dict:
    agentes = datos.get("agentes")
    modelos = datos.get("modelos")
    if type(datos.get("ollama")) is not bool:
        raise ValueError("Estado de Ollama inválido")
    if not isinstance(agentes, list) or len(agentes) > 20 or not isinstance(modelos, list) or len(modelos) > 30:
        raise ValueError("Estado local inválido")
    salida_agentes = []
    for agente in agentes:
        if not isinstance(agente, dict):
            raise ValueError("Estado de agente inválido")
        nombre, estado = agente.get("agente"), agente.get("estado")
        if not isinstance(nombre, str) or len(nombre) > 80 or estado not in (
                "trabajando", "esperando", "bloqueado", "detenido", "caído", "sin señal", "iniciando",
                "desconocido"):
            raise ValueError("Estado de agente inválido")
        edad = agente.get("edad_s", 0)
        if type(edad) is not int or edad < 0:
            raise ValueError("Antigüedad de agente inválida")
        salida_agentes.append({
            "agente": nombre,
            "modelo": str(agente.get("modelo") or "")[:160],
            "estado": estado,
            "tarea": str(agente.get("tarea") or "")[:300],
            "actualizado": str(agente.get("actualizado") or "")[:40],
            "edad_s": min(edad, 2_147_483_647),
        })
    lista_modelos = []
    for modelo in modelos:
        if not isinstance(modelo, str) or len(modelo) > 160:
            raise ValueError("Modelo local inválido")
        lista_modelos.append(modelo)
    servicio = datos.get("servicio")
    if servicio not in ("corriendo", "detenido", "desconocido"):
        raise ValueError("Estado del servicio inválido")
    return {
        "servicio": servicio,
        "ollama": bool(datos.get("ollama")),
        "modelos": lista_modelos,
        "agentes": salida_agentes,
    }


def _panel_latido(datos: dict) -> None:
    payload = _validar_estado_panel(datos)
    with _db() as conn:
        conn.execute(
            "INSERT INTO panel_estado (id, payload, actualizado) VALUES (1, %s::jsonb, NOW()) "
            "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, actualizado=NOW()",
            (json.dumps(payload, ensure_ascii=False),))


def _limpiar_panel_comandos(conn) -> None:
    conn.execute(
        "DELETE FROM panel_comandos WHERE estado IN ('completado', 'fallido') "
        "AND terminado < NOW() - INTERVAL '30 days'")


def _panel_crear_comando(accion: str) -> int:
    if accion not in ("iniciar", "detener"):
        raise ValueError("Acción no permitida")
    with _db() as conn:
        _limpiar_panel_comandos(conn)
        cur = conn.execute(
            "INSERT INTO panel_comandos (accion) VALUES (%s) RETURNING id", (accion,))
        return cur.fetchone()["id"]


def _panel_reclamar() -> dict | None:
    with _db() as conn:
        _limpiar_panel_comandos(conn)
        evento = conn.execute(
            "SELECT id, accion FROM panel_comandos "
            "WHERE estado='pendiente' OR (estado='procesando' AND reservado_hasta < NOW()) "
            "ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        if not evento:
            return None
        conn.execute(
            "UPDATE panel_comandos SET estado='procesando', reservado_hasta=NOW() + INTERVAL '2 minutes' "
            "WHERE id=%s", (evento["id"],))
        return {"id": evento["id"], "accion": evento["accion"]}


def _panel_completar(datos: dict) -> None:
    comando_id = datos.get("id")
    estado = datos.get("estado")
    if type(comando_id) is not int or comando_id < 1 or estado not in ("completado", "fallido"):
        raise ValueError("Resultado de comando inválido")
    detalle = str(datos.get("detalle") or "")[:300] or None
    with _db() as conn:
        cur = conn.execute(
            "UPDATE panel_comandos SET estado=%s, detalle=%s, terminado=NOW(), reservado_hasta=NULL "
            "WHERE id=%s AND estado='procesando' RETURNING id",
            (estado, detalle, comando_id))
        if not cur.fetchone():
            raise ValueError("El comando no existe o ya fue finalizado")


def _panel_resumen() -> dict:
    with _db() as conn:
        _limpiar_panel_comandos(conn)
        fila = conn.execute(
            "SELECT payload, actualizado FROM panel_estado WHERE id=1").fetchone()
        comandos = conn.execute(
            "SELECT id, accion, estado, creado, terminado, detalle FROM panel_comandos "
            "ORDER BY id DESC LIMIT 10").fetchall()
    return {
        "local": ({**fila["payload"], "actualizado": fila["actualizado"].isoformat()}
                  if fila else None),
        "comandos": [{
            **comando,
            "creado": comando["creado"].isoformat(),
            "terminado": comando["terminado"].isoformat() if comando["terminado"] else None,
        } for comando in comandos],
        "interacciones": _resumen(),
    }


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def crear_servidor() -> ThreadingHTTPServer:
    secreto = os.environ.get("META_APP_SECRET", "").strip()
    verify = os.environ.get("META_WEBHOOK_VERIFY_TOKEN", "").strip()
    queue_token = os.environ.get("INTERACCIONES_QUEUE_TOKEN", "").strip()
    if len(queue_token) < 32:
        raise RuntimeError("Configura un INTERACCIONES_QUEUE_TOKEN de 32+ caracteres")

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def responder(self, status: int, body: bytes = b"", tipo: str = "application/json; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self'; img-src 'self' data:; manifest-src 'self'; "
                             "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            self.end_headers()
            self.wfile.write(body)

        def json(self, status: int, datos: dict) -> None:
            self.responder(status, json.dumps(datos, ensure_ascii=False, default=str).encode())

        def body_json(self) -> dict:
            data = self.body_bytes()
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("Se esperaba un objeto JSON")
            return value

        def body_bytes(self) -> bytes:
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as e:
                raise ValueError("Longitud inválida") from e
            if size <= 0 or size > 1_000_000:
                raise ValueError("Cuerpo vacío o demasiado grande")
            return self.rfile.read(size)

        def autorizado(self) -> bool:
            valor = self.headers.get("X-Queue-Token", "")
            return hmac.compare_digest(valor, queue_token)

        def cookie(self, nombre: str) -> str:
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
                return cookies[nombre].value if nombre in cookies else ""
            except (KeyError, ValueError):
                return ""

        def sesion(self) -> dict | None:
            return panel_auth.leer_sesion(self.cookie(panel_auth.COOKIE_SESSION))

        def admin_autorizado(self) -> dict | None:
            sesion = self.sesion()
            if not sesion:
                return None
            if self.command == "POST":
                origin = self.headers.get("Origin", "")
                base = os.environ.get("PANEL_PUBLIC_URL", "").rstrip("/")
                if not base or not hmac.compare_digest(origin.rstrip("/"), base):
                    return None
                csrf = self.headers.get("X-CSRF-Token", "")
                if not hmac.compare_digest(csrf, sesion["csrf"]):
                    return None
            return sesion

        def redirigir(self, destino: str, cookies: tuple[str, ...] = ()) -> None:
            self.send_response(303)
            self.send_header("Location", destino)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()

        def _logout(self, cookie: str):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/healthz":
                return self.responder(200, b"ok", "text/plain; charset=utf-8")
            if url.path == "/webhook":
                if not secreto or not verify:
                    return self.responder(503, b"webhook not configured", "text/plain; charset=utf-8")
                query = parse_qs(url.query)
                token = (query.get("hub.verify_token") or [""])[0]
                if query.get("hub.mode") == ["subscribe"] and hmac.compare_digest(token, verify):
                    return self.responder(200, (query.get("hub.challenge") or [""])[0].encode(),
                                          "text/plain; charset=utf-8")
                return self.responder(403, b"forbidden", "text/plain; charset=utf-8")
            if url.path == "/internal/summary":
                if not self.autorizado():
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                try:
                    return self.json(200, _resumen())
                except Exception as e:
                    print(f"queue summary error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"queue unavailable", "text/plain; charset=utf-8")
            if url.path == "/":
                return self.responder(200, PANEL_HTML.read_bytes(), "text/html; charset=utf-8")
            if url.path == "/manifest.webmanifest":
                return self.responder(200, PANEL_MANIFEST.read_bytes(), "application/manifest+json")
            if url.path == "/panel-icon.svg":
                return self.responder(200, PANEL_ICON.read_bytes(), "image/svg+xml")
            if url.path == "/apple-touch-icon.png":
                return self.responder(200, Path(__file__).with_name("apple-touch-icon.png").read_bytes(),
                                      "image/png")
            if url.path == "/sw.js":
                return self.responder(200, (Path(__file__).with_name("panel_sw.js").read_bytes()),
                                      "application/javascript; charset=utf-8")
            if url.path == "/panel.js":
                return self.responder(200, (Path(__file__).with_name("panel.js").read_bytes()),
                                      "application/javascript; charset=utf-8")
            if url.path == "/auth/status":
                return self.json(200, {"configurado": panel_auth.configurado()})
            if url.path == "/auth/github/login":
                if not panel_auth.configurado():
                    return self.responder(503, b"OAuth no configurado", "text/plain; charset=utf-8")
                state = panel_auth.nueva_state()
                public_url = os.environ["PANEL_PUBLIC_URL"].rstrip("/")
                query = urlencode({
                    "client_id": os.environ["GITHUB_OAUTH_CLIENT_ID"],
                    "redirect_uri": public_url + "/auth/github/callback",
                    "scope": "read:user",
                    "state": state,
                })
                cookie = f"{panel_auth.COOKIE_STATE}={state}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=600"
                self.redirigir("https://github.com/login/oauth/authorize?" + query, (cookie,))
                return
            if url.path == "/auth/github/callback":
                query = parse_qs(url.query)
                state = (query.get("state") or [""])[0]
                code = (query.get("code") or [""])[0]
                cookie_state = self.cookie(panel_auth.COOKIE_STATE)
                borrar_state = (f"{panel_auth.COOKIE_STATE}=; Path=/; Secure; HttpOnly; "
                                "SameSite=Lax; Max-Age=0")
                if (not state or not code or not cookie_state
                        or not hmac.compare_digest(state, cookie_state)):
                    self.redirigir("/?error=auth", (borrar_state,))
                    return
                try:
                    usuario = panel_auth.intercambiar_codigo(code)
                    sesion, _ = panel_auth.crear_sesion(usuario)
                except (RuntimeError, PermissionError) as e:
                    print(f"panel OAuth rejected: {type(e).__name__}", flush=True)
                    self.redirigir("/?error=auth", (borrar_state,))
                    return
                session_cookie = (f"{panel_auth.COOKIE_SESSION}={sesion}; Path=/; Secure; HttpOnly; "
                                  "SameSite=Lax; Max-Age=43200")
                self.redirigir("/", (borrar_state, session_cookie))
                return
            if url.path == "/api/panel":
                sesion = self.sesion()
                if not sesion:
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                try:
                    datos = _panel_resumen()
                    datos["usuario"] = sesion["usuario"]
                    datos["csrf"] = sesion["csrf"]
                    return self.json(200, datos)
                except Exception as e:
                    print(f"panel read error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"panel unavailable", "text/plain; charset=utf-8")
            if url.path == "/internal/panel/claim":
                if not self.autorizado():
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                try:
                    comando = _panel_reclamar()
                    return self.json(200, comando) if comando else self.responder(204, b"")
                except Exception as e:
                    print(f"panel command claim error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"panel unavailable", "text/plain; charset=utf-8")
            return self.responder(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):
            url = urlparse(self.path)
            if url.path == "/api/panel/command":
                if not self.admin_autorizado():
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                try:
                    datos = self.body_json()
                    command_id = _panel_crear_comando(datos.get("accion"))
                    return self.json(202, {"id": command_id})
                except ValueError as e:
                    return self.json(400, {"error": str(e)})
                except Exception as e:
                    print(f"panel command create error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"panel unavailable", "text/plain; charset=utf-8")
            if url.path == "/api/panel/attend":
                if not self.admin_autorizado():
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                try:
                    _atender(self.body_json())
                    return self.json(200, {"ok": True})
                except ValueError as e:
                    return self.json(400, {"error": str(e)})
                except Exception as e:
                    print(f"panel interaction update error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"panel unavailable", "text/plain; charset=utf-8")
            if url.path == "/api/panel/logout":
                if not self.admin_autorizado():
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                cookie = (f"{panel_auth.COOKIE_SESSION}=; Path=/; Secure; HttpOnly; "
                          "SameSite=Lax; Max-Age=0")
                return self._logout(cookie)
            if url.path == "/internal/panel/heartbeat":
                if not self.autorizado():
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                try:
                    _panel_latido(self.body_json())
                    return self.json(200, {"ok": True})
                except ValueError as e:
                    return self.json(400, {"error": str(e)})
                except Exception as e:
                    print(f"panel heartbeat error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"panel unavailable", "text/plain; charset=utf-8")
            if url.path == "/internal/panel/complete":
                if not self.autorizado():
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                try:
                    _panel_completar(self.body_json())
                    return self.json(200, {"ok": True})
                except ValueError as e:
                    return self.json(400, {"error": str(e)})
                except Exception as e:
                    print(f"panel command finish error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"panel unavailable", "text/plain; charset=utf-8")
            if url.path == "/webhook":
                if (not secreto or not verify
                        or not os.environ.get("META_PAGE_ID", "").strip()
                        or not os.environ.get("META_IG_ID", "").strip()):
                    return self.responder(503, b"webhook not configured", "text/plain; charset=utf-8")
                try:
                    body = self.body_bytes()
                except ValueError as e:
                    return self.responder(400, b"invalid payload", "text/plain; charset=utf-8")
                if not verificar_firma(body, self.headers.get("X-Hub-Signature-256", ""), secreto):
                    return self.responder(403, b"invalid signature", "text/plain; charset=utf-8")
                try:
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise ValueError("Se esperaba un objeto JSON")
                    pagina = os.environ.get("META_PAGE_ID", "").strip()
                    instagram = os.environ.get("META_IG_ID", "").strip()
                    if not pagina or not instagram:
                        raise RuntimeError("Faltan META_PAGE_ID o META_IG_ID")
                    insertados = _guardar(normalizar(payload, pagina, instagram))
                    print(f"Webhook Meta recibido; eventos nuevos: {insertados}", flush=True)
                    return self.responder(200, b"EVENT_RECEIVED", "text/plain; charset=utf-8")
                except (TypeError, ValueError) as e:
                    print(f"invalid Meta payload: {type(e).__name__}", flush=True)
                    return self.responder(400, b"invalid payload", "text/plain; charset=utf-8")
                except Exception as e:
                    print(f"webhook queue error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"queue unavailable", "text/plain; charset=utf-8")
            if url.path.startswith("/internal/"):
                if not self.autorizado():
                    return self.responder(401, b"unauthorized", "text/plain; charset=utf-8")
                try:
                    if url.path == "/internal/claim":
                        if int(self.headers.get("Content-Length", "0")) > 0:
                            self.body_json()
                        event = _reclamar()
                        return self.json(200, event) if event else self.responder(204, b"")
                    datos = self.body_json()
                    if url.path == "/internal/complete":
                        _completar(datos)
                    elif url.path == "/internal/attend":
                        _atender(datos)
                    else:
                        return self.responder(404, b"not found", "text/plain; charset=utf-8")
                    return self.json(200, {"ok": True})
                except ValueError as e:
                    return self.json(400, {"error": str(e)})
                except Exception as e:
                    print(f"queue request error: {type(e).__name__}: {e}", flush=True)
                    return self.responder(503, b"queue unavailable", "text/plain; charset=utf-8")
            return self.responder(404, b"not found", "text/plain; charset=utf-8")

    port = int(os.environ.get("PORT", "10000"))
    return Servidor(("0.0.0.0", port), Manejador)


def main() -> None:
    preparar_db()
    server = crear_servidor()
    print(f"Webhook de Meta listo en el puerto {server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
