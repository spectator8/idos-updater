"""Focused tests for the local web interface."""

import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from idos_updater.core import ConfigManager, UpdateItem, UpdateManager
from idos_updater.web import WebApplication, make_handler


def sample_item():
    return UpdateItem(
        filename="TTAKT.ZIP",
        title="Testovací balíček",
        description="Test",
        section="Test",
        subsection="",
        date="1.1.2026",
        size_str="1 MB",
        size_bytes=1024,
        url="https://example.invalid/TEST.ZIP",
    )


class WebInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config = ConfigManager(
            config_file=os.path.join(self.temp_dir.name, "config.json")
        )
        with patch("idos_updater.web.ChapsScraper.fetch_updates", return_value=[sample_item()]):
            self.app = WebApplication(self.temp_dir.name, config_mgr=config)
            deadline = time.time() + 2
            while self.app.refresh_state == "loading" and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.app.refresh_state, "ready")
        self.token = "test-token"
        self.static_root = Path(self.temp_dir.name) / "web_dist"
        self.static_root.mkdir()
        (self.static_root / "index.html").write_text(
            '<meta name="csrf-token" content="__CSRF_TOKEN__"><title>IDOS Updater</title>',
            encoding="utf-8",
        )
        (self.static_root / "app.js").write_text("console.log('web app');", encoding="utf-8")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.app, self.token, self.static_root)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            request_headers["Content-Length"] = str(len(body))
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        result = response.read()
        status = response.status
        connection.close()
        return status, result

    def test_state_endpoint_returns_local_package_data(self):
        status, body = self.request("GET", "/api/state")
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["items"][0]["filename"], "TTAKT.ZIP")
        self.assertTrue(result["items"][0]["selected"])

    def test_homepage_serves_csrf_token_and_ui(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'name="csrf-token" content="test-token"', body)
        self.assertIn(b"IDOS Updater", body)

    def test_static_assets_are_served_and_traversal_is_blocked(self):
        status, body = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"console.log", body)
        status, _ = self.request("GET", "/%2e%2e/config.json")
        self.assertEqual(status, 404)

    def test_built_frontend_and_hashed_assets_are_served(self):
        frontend_root = Path(__file__).parent / "idos_updater" / "web_dist"
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.app, self.token, frontend_root)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=2
            )
            connection.request("GET", "/")
            response = connection.getresponse()
            html = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn('content="test-token"', html)
            asset_paths = re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', html)
            self.assertGreaterEqual(len(asset_paths), 2)

            for asset_path in asset_paths:
                connection.request("GET", asset_path)
                asset_response = connection.getresponse()
                self.assertEqual(asset_response.status, 200, asset_path)
                self.assertGreater(len(asset_response.read()), 0)
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_csrf_bootstrap_rejects_foreign_origins(self):
        status, _ = self.request(
            "GET",
            "/api/csrf",
            headers={"Origin": "http://evil.example"},
        )
        self.assertEqual(status, 403)

    def test_csrf_bootstrap_returns_the_session_token(self):
        status, body = self.request("GET", "/api/csrf")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["csrf_token"], self.token)

    def test_selection_endpoint_requires_csrf_token(self):
        status, _ = self.request("POST", "/api/selection", {"filenames": []})
        self.assertEqual(status, 403)

    def test_selection_endpoint_rejects_unknown_package(self):
        headers = {
            "X-IDO-CSRF-Token": self.token,
            "Origin": "http://127.0.0.1:{}".format(self.port),
        }
        status, body = self.request(
            "POST",
            "/api/selection",
            {"filenames": ["UNKNOWN.ZIP"]},
            headers,
        )
        self.assertEqual(status, 400)
        self.assertIn("Neznámý balíček", json.loads(body)["error"])

    def test_requests_with_non_loopback_host_are_rejected(self):
        status, _ = self.request(
            "GET", "/api/state", headers={"Host": "example.com:{}".format(self.port)}
        )
        self.assertEqual(status, 403)

    def test_settings_cannot_change_during_update(self):
        with self.app.lock:
            self.app.update_state = "running"
        headers = {
            "X-IDO-CSRF-Token": self.token,
            "Origin": "http://127.0.0.1:{}".format(self.port),
        }
        status, body = self.request(
            "POST",
            "/api/settings",
            {"path": self.temp_dir.name},
            headers,
        )
        self.assertEqual(status, 409)
        self.assertIn("během aktualizace", json.loads(body)["error"])

    def test_update_endpoint_runs_selected_packages(self):
        headers = {
            "X-IDO-CSRF-Token": self.token,
            "Origin": "http://127.0.0.1:{}".format(self.port),
        }
        with patch("idos_updater.web.IdosEnvironment.is_idos_running", return_value=False):
            with patch.object(UpdateManager, "download_and_extract", return_value=(1, 0, [])):
                status, _ = self.request("POST", "/api/update", {}, headers)
                deadline = time.time() + 2
                while self.app.update_state == "running" and time.time() < deadline:
                    time.sleep(0.01)
        self.assertEqual(status, 200)
        self.assertEqual(self.app.update_state, "done")
        self.assertIn("1 úspěšných", self.app.update_summary)


if __name__ == "__main__":
    unittest.main()
