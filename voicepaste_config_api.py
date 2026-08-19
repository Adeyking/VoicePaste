#!/usr/bin/env python3
"""VoicePaste Config API — tiny HTTP server exposing config and inbox to home dashboard.

Runs on Windows Desktop, port 8766.
home-dashboard-smoke on NucBox calls this instead of trying to read Windows files directly.

Endpoints:
  GET    /health            -> {"ok": true}
  GET    /config            -> voicepaste.config.json as JSON
  POST   /config            -> merge updated key/value pairs into config (partial update safe)
  GET    /inbox             -> list of .md notes from voice_paste/inbox/
  GET    /snippets          -> {"trigger": "expansion", ...}
  POST   /snippets          -> add/update snippet {"trigger": "...", "expansion": "..."}
  DELETE /snippets          -> remove snippet {"trigger": "..."}
  GET    /phrases           -> {"heard_as": "replace_with", ...}
  POST   /phrases           -> add/update phrase {"heard_as": "...", "replace_with": "..."}
  DELETE /phrases           -> remove phrase {"heard_as": "..."}
"""

import json
import os
import socket
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

PORT = int(os.getenv("VOICEPASTE_API_PORT", "8766"))
HOST = os.getenv("VOICEPASTE_API_HOST", "0.0.0.0")
CONFIG_PATH = Path(__file__).parent / "voicepaste.config.json"
START_TIME = time.time()



def _expand_win_path(raw: str) -> Path:
    return Path(os.path.expandvars(raw))


def _voice_paste_root(config: dict) -> Path:
    raw = str(config.get("VOICE_PASTE_ROOT", "") or "").strip()
    if raw:
        return _expand_win_path(raw)
    return Path(os.path.expandvars(r"%USERPROFILE%\Documents\VoicePaste\voice_paste"))


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _read_json_file(path_str: str) -> dict:
    """Read a JSON data file; return {"exact": {}} if missing or unreadable."""
    try:
        p = _expand_win_path(path_str)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {"exact": {}}


def _write_json_file(path_str: str, data: dict) -> None:
    p = _expand_win_path(path_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _snippets_path(config: dict) -> str:
    return config.get(
        "SNIPPETS_PATH",
        r"%USERPROFILE%\Documents\VoicePaste\snippets.json",
    )


def _phrases_path(config: dict) -> str:
    return config.get(
        "PHRASE_CORRECTIONS_PATH",
        r"%USERPROFILE%\Documents\VoicePaste\phrase_corrections.json",
    )


class ConfigHandler(BaseHTTPRequestHandler):

    def _json(self, code: int, data: object) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/health":
            self._json(200, {
                "ok": True,
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "uptime_seconds": int(time.time() - START_TIME),
                "config": str(CONFIG_PATH),
                "exists": CONFIG_PATH.exists(),
            })

        elif path == "/config":
            config = _read_config()
            if not config and not CONFIG_PATH.exists():
                self._json(404, {"error": f"Config not found: {CONFIG_PATH}"})
            else:
                self._json(200, config)

        elif path == "/inbox":
            config = _read_config()
            root = _voice_paste_root(config)
            inbox = root / "inbox"
            notes = []
            if inbox.exists():
                files = sorted(inbox.rglob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
                for f in files:
                    try:
                        lines = f.read_text(encoding="utf-8").splitlines()
                        preview = "\n".join(lines[-5:]).strip()
                        notes.append({
                            "filename": f.stem,
                            "preview": preview,
                            "updated_at": datetime.fromtimestamp(
                                f.stat().st_mtime
                            ).strftime("%Y-%m-%d %H:%M:%S"),
                        })
                    except OSError:
                        continue
            self._json(200, {"notes": notes, "inbox_path": str(inbox)})

        elif path == "/snippets":
            config = _read_config()
            data = _read_json_file(_snippets_path(config))
            self._json(200, data.get("exact", {}))

        elif path == "/phrases":
            config = _read_config()
            data = _read_json_file(_phrases_path(config))
            self._json(200, data.get("exact", {}))

        else:
            self._json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/config":
            try:
                payload = json.loads(self._body())
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                # Merge into existing config (safe partial update)
                existing = _read_config()
                existing.update(payload)
                CONFIG_PATH.write_text(
                    json.dumps(existing, indent=2), encoding="utf-8"
                )
                self._json(200, {"ok": True})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})

        elif path == "/snippets":
            try:
                payload = json.loads(self._body())
                trigger = payload.get("trigger", "").strip()
                expansion = payload.get("expansion", "").strip()
                if not trigger:
                    raise ValueError("trigger is required")
                config = _read_config()
                p = _snippets_path(config)
                data = _read_json_file(p)
                data.setdefault("exact", {})[trigger] = expansion
                _write_json_file(p, data)
                self._json(200, {"ok": True})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})

        elif path == "/phrases":
            try:
                payload = json.loads(self._body())
                heard = payload.get("heard_as", "").strip()
                replace = payload.get("replace_with", "").strip()
                if not heard:
                    raise ValueError("heard_as is required")
                config = _read_config()
                p = _phrases_path(config)
                data = _read_json_file(p)
                data.setdefault("exact", {})[heard] = replace
                _write_json_file(p, data)
                self._json(200, {"ok": True})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})

        else:
            self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/snippets":
            try:
                payload = json.loads(self._body())
                trigger = payload.get("trigger", "").strip()
                config = _read_config()
                p = _snippets_path(config)
                data = _read_json_file(p)
                data.get("exact", {}).pop(trigger, None)
                _write_json_file(p, data)
                self._json(200, {"ok": True})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})

        elif path == "/phrases":
            try:
                payload = json.loads(self._body())
                heard = payload.get("heard_as", "").strip()
                config = _read_config()
                p = _phrases_path(config)
                data = _read_json_file(p)
                data.get("exact", {}).pop(heard, None)
                _write_json_file(p, data)
                self._json(200, {"ok": True})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})

        else:
            self._json(404, {"error": "Not found"})

    def log_message(self, fmt, *args):
        if sys.stdout is not None:
            try:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] {self.address_string()} {fmt % args}", flush=True)
            except Exception:
                pass


def run_api_server() -> None:
    try:
        server = HTTPServer((HOST, PORT), ConfigHandler)
        server.serve_forever()
    except Exception:
        pass


if __name__ == "__main__":
    if sys.stdout is not None:
        try:
            print(f"VoicePaste Config API", flush=True)
            print(f"  port   : {PORT}", flush=True)
            print(f"  config : {CONFIG_PATH}", flush=True)
            print(f"  exists : {CONFIG_PATH.exists()}", flush=True)
        except Exception:
            pass
    run_api_server()
