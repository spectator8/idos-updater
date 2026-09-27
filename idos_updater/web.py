"""Lokální webové rozhraní pro IDOS Updater."""

import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from idos_updater.core import (
    BackupManager,
    ChapsScraper,
    ConfigManager,
    IdosEnvironment,
    PRESETS,
    UpdateItem,
    UpdateManager,
)


MAX_REQUEST_BYTES = 65536
MAX_LOG_ENTRIES = 500


class WebApplication:
    """Sdílí stav webového UI a spouští dlouhé operace na pozadí."""

    def __init__(
        self,
        idos_path: Optional[str] = None,
        config_mgr: Optional[ConfigManager] = None,
    ):
        self.config_mgr = config_mgr or ConfigManager()
        self.config = self.config_mgr.load_config()
        if idos_path:
            self.config["idos_path"] = os.path.abspath(idos_path)
        self.idos_path = self.config.get("idos_path", r"C:\IDOS")
        self.scan_result = IdosEnvironment.scan_local_files(self.idos_path)
        self.items = []  # type: List[UpdateItem]
        self.selected_filenames = set()
        self.logs = []  # type: List[str]
        self.lock = threading.RLock()
        self.refresh_state = "idle"
        self.refresh_error = ""
        self.update_state = "idle"
        self.update_error = ""
        self.update_summary = ""
        self.progress = {
            "filename": "",
            "item_index": 0,
            "item_count": 0,
            "downloaded": 0,
            "total": 0,
            "ratio": 0.0,
            "overall_ratio": 0.0,
            "speed": "",
        }
        self.cancel_event = threading.Event()
        self._append_log("Načítám seznam balíčků z CHAPS.")
        self.refresh_updates()

    def _append_log(self, message: str) -> None:
        with self.lock:
            self.logs.append(message)
            del self.logs[:-MAX_LOG_ENTRIES]

    def refresh_updates(self) -> None:
        with self.lock:
            if self.refresh_state == "loading":
                return
            self.refresh_state = "loading"
            self.refresh_error = ""

        def worker() -> None:
            try:
                items = ChapsScraper().fetch_updates()
                with self.lock:
                    self.items = items
                    self.refresh_state = "ready"
                    self.scan_result = IdosEnvironment.scan_local_files(self.idos_path)
                    self.selected_filenames = {
                        name for name in self.selected_filenames
                        if name.upper() in {item.filename.upper() for item in items}
                    }
                    if not self.selected_filenames:
                        outdated = [
                            item.filename for item in items
                            if IdosEnvironment.get_item_update_status(item, self.scan_result)[0] == "outdated"
                        ]
                        if outdated:
                            self.selected_filenames = set(outdated)
                        else:
                            self.selected_filenames = {
                                item.filename for item in items
                                if PRESETS["quick"]["filter"](item)
                            }
                self._append_log("Načteno {} balíčků z CHAPS.".format(len(items)))
            except Exception as exc:
                with self.lock:
                    self.refresh_state = "error"
                    self.refresh_error = str(exc)
                self._append_log("Nepodařilo se načíst seznam balíčků: {}".format(exc))

        threading.Thread(target=worker, daemon=True).start()

    def set_settings(self, data: Dict[str, Any]) -> None:
        path = data.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Zadejte cestu ke složce IDOS.")
        if any(ord(char) < 32 for char in path):
            raise ValueError("Cesta obsahuje nepovolené řídicí znaky.")

        booleans = ("create_backup", "auto_kill_idos", "launch_after_update")
        for key in booleans:
            if key in data and type(data[key]) is not bool:
                raise ValueError("Neplatná hodnota nastavení: {}.".format(key))

        with self.lock:
            if self.update_state == "running":
                raise RuntimeError("Nastavení nelze měnit během aktualizace.")
            self.idos_path = os.path.abspath(os.path.expanduser(path.strip()))
            self.config["idos_path"] = self.idos_path
            for key in booleans:
                if key in data:
                    self.config[key] = data[key]
            self.config_mgr.save_config(self.config)
            self.scan_result = IdosEnvironment.scan_local_files(self.idos_path)
        self._append_log("Nastavení uloženo. Cílová složka: {}".format(self.idos_path))

    def set_selection(self, filenames: Any) -> None:
        if not isinstance(filenames, list) or any(not isinstance(name, str) for name in filenames):
            raise ValueError("Výběr balíčků musí být seznam názvů souborů.")
        with self.lock:
            available = {item.filename.upper(): item.filename for item in self.items}
            requested = set()
            for name in filenames:
                key = name.upper()
                if key not in available:
                    raise ValueError("Neznámý balíček: {}.".format(name))
                requested.add(available[key])
            self.selected_filenames = requested

    def select_action(self, action: str) -> None:
        with self.lock:
            if action == "clear":
                self.selected_filenames.clear()
            elif action in ("outdated", "not_installed"):
                self.selected_filenames = {
                    item.filename for item in self.items
                    if IdosEnvironment.get_item_update_status(item, self.scan_result)[0]
                    == action
                }
            elif action in PRESETS:
                self.selected_filenames = {
                    item.filename for item in self.items
                    if PRESETS[action]["filter"](item)
                }
            elif action == "all":
                self.selected_filenames = {item.filename for item in self.items}
            else:
                raise ValueError("Neznámá akce výběru.")

    def start_update(self) -> None:
        with self.lock:
            if self.update_state == "running":
                raise RuntimeError("Aktualizace už běží.")
            if self.refresh_state != "ready":
                raise RuntimeError("Nejdřív načtěte seznam balíčků z CHAPS.")
            items = [
                item for item in self.items
                if item.filename in self.selected_filenames
            ]
            if not items:
                raise ValueError("Vyberte alespoň jeden balíček k aktualizaci.")
            if not self.idos_path.strip():
                raise ValueError("Zadejte cestu ke složce IDOS.")

            self.update_state = "running"
            self.update_error = ""
            self.update_summary = ""
            self.cancel_event.clear()
            self.progress = {
                "filename": "",
                "item_index": 0,
                "item_count": len(items),
                "downloaded": 0,
                "total": 0,
                "ratio": 0.0,
                "overall_ratio": 0.0,
                "speed": "",
            }
            path = self.idos_path
            create_backup = bool(self.config.get("create_backup", True))
            auto_kill = bool(self.config.get("auto_kill_idos", True))
            launch_after = bool(self.config.get("launch_after_update", False))

        threading.Thread(
            target=self._update_worker,
            args=(path, items, create_backup, auto_kill, launch_after),
            daemon=True,
        ).start()

    def _update_worker(
        self,
        path: str,
        items: List[UpdateItem],
        create_backup: bool,
        auto_kill: bool,
        launch_after: bool,
    ) -> None:
        try:
            self._append_log("Začíná aktualizace {} balíčků do {}.".format(len(items), path))
            if IdosEnvironment.is_idos_running():
                if not auto_kill:
                    raise RuntimeError("IDOS běží. Ukončete TT.exe nebo povolte jeho automatické ukončení.")
                self._append_log("Ukončuji běžící proces IDOS.")
                if not IdosEnvironment.kill_idos():
                    raise RuntimeError("Běžící IDOS se nepodařilo ukončit.")

            if create_backup and os.path.isdir(path) and os.listdir(path):
                BackupManager.create_backup(path, log_callback=self._append_log)

            updater = UpdateManager(path)
            item_count = len(items)

            def progress_callback(item, downloaded, total, ratio, speed):
                item_index = items.index(item) + 1
                with self.lock:
                    self.progress = {
                        "filename": item.filename,
                        "item_index": item_index,
                        "item_count": item_count,
                        "downloaded": downloaded,
                        "total": total,
                        "ratio": ratio,
                        "overall_ratio": ((item_index - 1) + ratio) / item_count,
                        "speed": speed,
                    }

            succeeded, failed, errors = updater.download_and_extract(
                items=items,
                progress_callback=progress_callback,
                log_callback=self._append_log,
                cancel_check=self.cancel_event.is_set,
            )

            cancelled = self.cancel_event.is_set()
            if errors:
                for error in errors:
                    self._append_log("Chyba: {}".format(error))
            summary = "Aktualizace {}: {} úspěšných, {} chyb.".format(
                "zrušena" if cancelled else "dokončena", succeeded, failed
            )
            self._append_log(summary)
            if launch_after and failed == 0 and not cancelled:
                if IdosEnvironment.launch_idos(path):
                    self._append_log("IDOS byl spuštěn.")
                else:
                    self._append_log("IDOS se nepodařilo spustit: TT.exe nebyl nalezen.")

            with self.lock:
                self.update_state = "cancelled" if cancelled else "done"
                self.update_summary = summary
                self.scan_result = IdosEnvironment.scan_local_files(path)
        except Exception as exc:
            with self.lock:
                self.update_state = "error"
                self.update_error = str(exc)
                self.update_summary = str(exc)
            self._append_log("Aktualizace selhala: {}".format(exc))

    def cancel_update(self) -> None:
        with self.lock:
            if self.update_state != "running":
                raise RuntimeError("Momentálně neběží žádná aktualizace.")
            self.cancel_event.set()
        self._append_log("Požadavek na zrušení aktualizace byl přijat.")

    def autodetect_path(self) -> None:
        path = IdosEnvironment.find_default_path()
        if not path:
            raise RuntimeError("Instalaci IDOS se nepodařilo automaticky najít.")
        self.set_settings({
            "path": path,
            "create_backup": bool(self.config.get("create_backup", True)),
            "auto_kill_idos": bool(self.config.get("auto_kill_idos", True)),
            "launch_after_update": bool(self.config.get("launch_after_update", False)),
        })

    def launch_idos(self) -> None:
        with self.lock:
            path = self.idos_path
        if not IdosEnvironment.launch_idos(path):
            raise RuntimeError("IDOS se nepodařilo spustit: TT.exe nebyl nalezen.")
        self._append_log("IDOS byl spuštěn z {}.".format(path))

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
            items = []
            for item in self.items:
                status, label, local_date = IdosEnvironment.get_item_update_status(
                    item, self.scan_result
                )
                items.append({
                    "filename": item.filename,
                    "title": item.title,
                    "description": item.description,
                    "category": item.category_label,
                    "date": item.date,
                    "size": item.size_str,
                    "size_bytes": item.size_bytes,
                    "status": status,
                    "status_label": label,
                    "local_date": local_date,
                    "selected": item.filename in self.selected_filenames,
                })
            return {
                "path": self.idos_path,
                "create_backup": bool(self.config.get("create_backup", True)),
                "auto_kill_idos": bool(self.config.get("auto_kill_idos", True)),
                "launch_after_update": bool(self.config.get("launch_after_update", False)),
                "refresh_state": self.refresh_state,
                "refresh_error": self.refresh_error,
                "update_state": self.update_state,
                "update_error": self.update_error,
                "update_summary": self.update_summary,
                "progress": dict(self.progress),
                "items": items,
                "logs": list(self.logs),
                "idos_running": IdosEnvironment.is_idos_running(),
            }


def make_handler(app: WebApplication, token: str):
    html_path = Path(__file__).with_name("web_ui.html")
    page = html_path.read_text(encoding="utf-8").replace("__CSRF_TOKEN__", token)

    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "IDOSUpdaterWeb/1.0"

        def log_message(self, format_string, *args):
            _ = (format_string, args)

        def _local_host_is_valid(self) -> bool:
            host = self.headers.get("Host", "")
            try:
                parsed_host = urlsplit("//" + host)
                if parsed_host.hostname not in ("127.0.0.1", "localhost"):
                    return False
                if parsed_host.port != self.server.server_port:
                    return False
            except ValueError:
                return False
            return True

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, value: Dict[str, Any]) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _read_json(self) -> Dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "")
            try:
                length = int(raw_length)
            except ValueError:
                raise ValueError("Neplatná délka požadavku.")
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("Požadavek je prázdný nebo příliš velký.")
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ValueError("Tělo požadavku musí být platný JSON.")
            if not isinstance(data, dict):
                raise ValueError("Tělo požadavku musí být JSON objekt.")
            return data

        def _discard_request_body(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.close_connection = True
                return
            if 0 <= length <= MAX_REQUEST_BYTES:
                self.rfile.read(length)
            else:
                self.close_connection = True

        def _is_authorized_post(self) -> bool:
            if not self._local_host_is_valid():
                return False
            if not secrets.compare_digest(self.headers.get("X-IDO-CSRF-Token", ""), token):
                return False
            origin = self.headers.get("Origin")
            if origin:
                parsed_origin = urlsplit(origin)
                if parsed_origin.scheme != "http" or parsed_origin.netloc.lower() != self.headers.get("Host", "").lower():
                    return False
            return True

        def do_GET(self):
            if not self._local_host_is_valid():
                self._send_json(403, {"error": "Přístup je povolen pouze z tohoto počítače."})
                return
            if self.path == "/":
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._send_json(200, app.get_state())
            else:
                self._send_json(404, {"error": "Cesta nebyla nalezena."})

        def do_POST(self):
            if not self._is_authorized_post():
                self._discard_request_body()
                self._send_json(403, {"error": "Neplatný nebo vzdálený požadavek."})
                return
            try:
                data = self._read_json()
                if self.path == "/api/settings":
                    app.set_settings(data)
                elif self.path == "/api/selection":
                    app.set_selection(data.get("filenames"))
                elif self.path == "/api/select-action":
                    action = data.get("action")
                    if not isinstance(action, str):
                        raise ValueError("Chybí akce výběru.")
                    app.select_action(action)
                elif self.path == "/api/refresh":
                    app.refresh_updates()
                elif self.path == "/api/update":
                    app.start_update()
                elif self.path == "/api/cancel":
                    app.cancel_update()
                elif self.path == "/api/launch":
                    app.launch_idos()
                elif self.path == "/api/autodetect":
                    app.autodetect_path()
                else:
                    self._send_json(404, {"error": "Cesta nebyla nalezena."})
                    return
                response = {"ok": True, "state": app.get_state()}
                if self.path == "/api/launch":
                    response["message"] = "IDOS byl spuštěn."
                self._send_json(200, response)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self._send_json(409, {"error": str(exc)})
            except Exception as exc:
                app._append_log("Chyba webového požadavku: {}".format(exc))
                self._send_json(500, {"error": "Požadavek se nepodařilo dokončit."})

    return RequestHandler


def run_web(idos_path: Optional[str] = None) -> None:
    app = WebApplication(idos_path)
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, token))
    server.daemon_threads = True
    url = "http://127.0.0.1:{}/".format(server.server_port)
    print("IDOS Updater webové rozhraní: {}".format(url))
    print("Server je dostupný pouze na tomto počítači. Ukončete jej pomocí Ctrl+C.")
    webbrowser.open_new_tab(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nUkončuji webové rozhraní.")
    finally:
        server.shutdown()
        server.server_close()
