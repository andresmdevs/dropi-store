"""Validación de firmas y normalización de notificaciones Meta."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime


def verificar_firma(cuerpo: bytes, firma: str, secreto: str) -> bool:
    if not firma.startswith("sha256="):
        return False
    esperado = "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, firma)


def _timestamp_ms(valor) -> int | None:
    if isinstance(valor, (int, float)):
        return int(valor if valor > 10_000_000_000 else valor * 1000)
    if not isinstance(valor, str) or not valor.strip():
        return None
    if valor.strip().isdigit():
        return _timestamp_ms(int(valor.strip()))
    try:
        return int(datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _evento(red: str, tipo: str, externo_id: str, remitente: str | None, contexto: str | None,
            texto: str, evento_ms: int | None, cuenta: str) -> dict | None:
    texto = " ".join(str(texto or "").split())[:2000]
    if not externo_id or not texto or (remitente and remitente == cuenta):
        return None
    dedupe = f"{red}:{tipo}:{externo_id}"
    return {"dedupe": dedupe, "red": red, "tipo": tipo, "externo_id": str(externo_id),
            "remitente": str(remitente) if remitente else None,
            "contexto": str(contexto) if contexto else None, "texto": texto, "evento_ms": evento_ms}


def normalizar(payload: dict, pagina_id: str, instagram_id: str) -> list[dict]:
    """Extrae solo comentarios y mensajes entrantes de la Página y el Instagram configurados."""
    out = []
    objeto = payload.get("object")
    for entry in payload.get("entry") or []:
        cuenta = str(entry.get("id") or "")
        if objeto == "page" and cuenta == pagina_id:
            for mensaje in entry.get("messaging") or []:
                body = mensaje.get("message") or {}
                if body.get("is_echo") or mensaje.get("read") or mensaje.get("delivery"):
                    continue
                event = _evento("facebook", "mensaje", body.get("mid"),
                                (mensaje.get("sender") or {}).get("id"),
                                (mensaje.get("referral") or {}).get("ref"),
                                body.get("text"), _timestamp_ms(mensaje.get("timestamp")), cuenta)
                if event:
                    out.append(event)
            for cambio in entry.get("changes") or []:
                if cambio.get("field") != "feed":
                    continue
                valor = cambio.get("value") or {}
                if valor.get("item") != "comment" or valor.get("verb") != "add":
                    continue
                event = _evento("facebook", "comentario", valor.get("comment_id"),
                                (valor.get("from") or {}).get("id"), valor.get("post_id"),
                                valor.get("message"), _timestamp_ms(valor.get("created_time")), cuenta)
                if event:
                    out.append(event)
        elif objeto == "instagram" and cuenta == instagram_id:
            for mensaje in entry.get("messaging") or []:
                body = mensaje.get("message") or {}
                if body.get("is_echo") or mensaje.get("read") or mensaje.get("delivery"):
                    continue
                event = _evento("instagram", "mensaje", body.get("mid"),
                                (mensaje.get("sender") or {}).get("id"),
                                (mensaje.get("referral") or {}).get("ref"),
                                body.get("text"), _timestamp_ms(mensaje.get("timestamp")), cuenta)
                if event:
                    out.append(event)
            for cambio in entry.get("changes") or []:
                if cambio.get("field") != "comments":
                    continue
                valor = cambio.get("value") or {}
                event = _evento("instagram", "comentario", valor.get("id"),
                                (valor.get("from") or {}).get("id"),
                                (valor.get("media") or {}).get("id"),
                                valor.get("text"), _timestamp_ms(valor.get("timestamp")), cuenta)
                if event:
                    out.append(event)
    return sorted(out, key=lambda event: (event["evento_ms"] is not None, event["evento_ms"] or 0))
