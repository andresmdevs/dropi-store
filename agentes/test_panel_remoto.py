from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from pathlib import Path
from urllib import error, request
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import panel_auth
import webhook_render


class PruebasPanelRemoto(unittest.TestCase):
    def test_sesion_firmada_y_allowlist_github(self):
        variables = {
            "PANEL_SESSION_SECRET": "s" * 48,
            "PANEL_GITHUB_USERS": "andresmdevs",
            "PANEL_PUBLIC_URL": "https://panel.test",
            "GITHUB_OAUTH_CLIENT_ID": "client-id",
            "GITHUB_OAUTH_CLIENT_SECRET": "client-secret",
        }
        with mock.patch.dict(os.environ, variables):
            cookie, csrf = panel_auth.crear_sesion("andresmdevs")
            sesion = panel_auth.leer_sesion(cookie)
            self.assertEqual(sesion["usuario"], "andresmdevs")
            self.assertEqual(sesion["csrf"], csrf)
            self.assertIsNone(panel_auth.leer_sesion(cookie + "x"))
            with mock.patch.dict(os.environ, {"PANEL_GITHUB_USERS": "otra-cuenta"}):
                self.assertIsNone(panel_auth.leer_sesion(cookie))

    def test_snapshot_rechaza_campos_o_estados_no_permitidos(self):
        estado = webhook_render._validar_estado_panel({
            "servicio": "corriendo",
            "ollama": True,
            "modelos": ["qwen-local"],
            "agentes": [{"agente": "analista", "estado": "trabajando", "tarea": "Evalúa producto"}],
            "secreto": "no se persiste",
        })
        self.assertEqual(estado["modelos"], ["qwen-local"])
        self.assertNotIn("secreto", estado)
        with self.assertRaises(ValueError):
            webhook_render._validar_estado_panel({
                "servicio": "corriendo", "ollama": True, "modelos": [],
                "agentes": [{"agente": "agente", "estado": "arbitrary-command"}],
            })

    def test_api_de_panel_requiere_sesion_csrf_y_origin(self):
        variables = {
            "PORT": "0",
            "META_APP_SECRET": "app-secret",
            "META_WEBHOOK_VERIFY_TOKEN": "verify-token",
            "INTERACCIONES_QUEUE_TOKEN": "q" * 40,
            "PANEL_PUBLIC_URL": "https://panel.test",
            "PANEL_SESSION_SECRET": "s" * 48,
            "PANEL_GITHUB_USERS": "andresmdevs",
            "GITHUB_OAUTH_CLIENT_ID": "client-id",
            "GITHUB_OAUTH_CLIENT_SECRET": "client-secret",
        }
        with mock.patch.dict(os.environ, variables), \
                mock.patch.object(webhook_render, "_panel_resumen", return_value={
                    "local": None, "comandos": [], "interacciones": {"conteos": {}},
                }), \
                mock.patch.object(webhook_render, "_panel_crear_comando", return_value=9) as crear:
            servidor = webhook_render.crear_servidor()
            hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
            hilo.start()
            base = f"http://127.0.0.1:{servidor.server_address[1]}"
            try:
                with self.assertRaises(error.HTTPError) as respuesta:
                    request.urlopen(base + "/api/panel", timeout=3)
                self.assertEqual(respuesta.exception.code, 401)
                respuesta.exception.close()

                cookie, csrf = panel_auth.crear_sesion("andresmdevs")
                sesion = {"Cookie": f"{panel_auth.COOKIE_SESSION}={cookie}"}
                with request.urlopen(request.Request(base + "/api/panel", headers=sesion), timeout=3) as respuesta:
                    self.assertEqual(json.loads(respuesta.read())["usuario"], "andresmdevs")

                cabeceras = {**sesion, "Origin": "https://panel.test", "X-CSRF-Token": csrf}
                accion = request.Request(base + "/api/panel/command", data=b'{"accion":"iniciar"}',
                                         headers=cabeceras)
                with request.urlopen(accion, timeout=3) as respuesta:
                    self.assertEqual(respuesta.status, 202)
                    self.assertEqual(json.loads(respuesta.read()), {"id": 9})
                crear.assert_called_once_with("iniciar")

                sin_csrf = request.Request(base + "/api/panel/command", data=b'{"accion":"iniciar"}',
                                           headers={**sesion, "Origin": "https://panel.test"})
                with self.assertRaises(error.HTTPError) as respuesta:
                    request.urlopen(sin_csrf, timeout=3)
                self.assertEqual(respuesta.exception.code, 401)
                respuesta.exception.close()
            finally:
                servidor.shutdown()
                servidor.server_close()
                hilo.join(timeout=3)

    def test_panel_no_abre_oauth_ni_webhook_sin_secrets(self):
        with mock.patch.dict(os.environ, {"PORT": "0", "INTERACCIONES_QUEUE_TOKEN": "q" * 40}, clear=True):
            servidor = webhook_render.crear_servidor()
            hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
            hilo.start()
            base = f"http://127.0.0.1:{servidor.server_address[1]}"
            try:
                with request.urlopen(base + "/auth/status", timeout=3) as respuesta:
                    self.assertFalse(json.loads(respuesta.read())["configurado"])
                for path in ("/auth/github/login", "/webhook"):
                    with self.assertRaises(error.HTTPError) as respuesta:
                        request.urlopen(base + path, timeout=3)
                    self.assertEqual(respuesta.exception.code, 503)
                    respuesta.exception.close()
            finally:
                servidor.shutdown()
                servidor.server_close()
                hilo.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
