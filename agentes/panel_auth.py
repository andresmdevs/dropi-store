"""Autenticación GitHub OAuth y sesiones firmadas del panel remoto."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib import error, parse, request


COOKIE_SESSION = "__Host-monkey-panel"
COOKIE_STATE = "__Host-monkey-oauth-state"


def configurado() -> bool:
    url = os.environ.get("PANEL_PUBLIC_URL", "").strip()
    secreto = os.environ.get("PANEL_SESSION_SECRET", "").strip()
    return url.startswith("https://") and len(secreto) >= 32 and all(
        os.environ.get(k, "").strip() for k in (
        "GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET",
    )) and bool(usuarios_permitidos())


def usuarios_permitidos() -> set[str]:
    return {u.strip().casefold() for u in os.environ.get("PANEL_GITHUB_USERS", "").split(",") if u.strip()}


def nueva_state() -> str:
    return secrets.token_urlsafe(32)


def _firma(valor: str) -> str:
    secreto = os.environ.get("PANEL_SESSION_SECRET", "").strip()
    if len(secreto) < 32:
        raise RuntimeError("PANEL_SESSION_SECRET debe tener al menos 32 caracteres")
    return hmac.new(secreto.encode(), valor.encode(), hashlib.sha256).hexdigest()


def crear_sesion(usuario: str) -> tuple[str, str]:
    csrf = secrets.token_urlsafe(24)
    payload = {
        "usuario": usuario.casefold(),
        "csrf": csrf,
        "exp": int(time.time()) + 12 * 60 * 60,
    }
    codificado = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{codificado}.{_firma(codificado)}", csrf


def leer_sesion(cookie: str) -> dict | None:
    if not configurado():
        return None
    try:
        codificado, firma = cookie.split(".", 1)
        if not hmac.compare_digest(firma, _firma(codificado)):
            return None
        raw = base64.urlsafe_b64decode(codificado + "=" * (-len(codificado) % 4))
        sesion = json.loads(raw)
        if (not isinstance(sesion, dict) or type(sesion.get("exp")) is not int
                or sesion["exp"] <= time.time()
                or sesion.get("usuario") not in usuarios_permitidos()
                or not isinstance(sesion.get("csrf"), str)):
            return None
        return sesion
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def intercambiar_codigo(codigo: str) -> str:
    if not configurado():
        raise RuntimeError("Configura GitHub OAuth y PANEL_PUBLIC_URL en Render")
    payload = parse.urlencode({
        "client_id": os.environ["GITHUB_OAUTH_CLIENT_ID"],
        "client_secret": os.environ["GITHUB_OAUTH_CLIENT_SECRET"],
        "code": codigo,
        "redirect_uri": os.environ["PANEL_PUBLIC_URL"].rstrip("/") + "/auth/github/callback",
    }).encode()
    req = request.Request("https://github.com/login/oauth/access_token", data=payload, headers={
        "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "monkey-store-panel",
    })
    try:
        with request.urlopen(req, timeout=8) as response:
            token_data = json.loads(response.read())
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("No se pudo completar el inicio de sesión GitHub") from exc
    token = token_data.get("access_token")
    if not token:
        raise RuntimeError("GitHub no autorizó la sesión")
    perfil_req = request.Request("https://api.github.com/user", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "monkey-store-panel",
    })
    try:
        with request.urlopen(perfil_req, timeout=8) as response:
            perfil = json.loads(response.read())
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("No se pudo verificar la cuenta GitHub") from exc
    usuario = perfil.get("login")
    if not isinstance(usuario, str) or usuario.casefold() not in usuarios_permitidos():
        raise PermissionError("Esta cuenta GitHub no está autorizada para el panel")
    return usuario
