from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import log_info, log_warn

DEFAULT_MCP_PORT = 8765


class AutoGISMCPBridge:
    """Loopback-only HTTP JSON-RPC / MCP bridge for controlling live QGIS from external AI agents."""

    def __init__(self, engine, host: str = "127.0.0.1", port: int = DEFAULT_MCP_PORT) -> None:
        self._engine = engine
        self._host = "127.0.0.1"
        self._port = int(port)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def start(self) -> bool:
        if self._httpd is not None:
            return True
        bridge = self

        class _Handler(BaseHTTPRequestHandler):
            def _send_json(self, status: int, payload: dict[str, Any]) -> None:
                raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path in ("/", "/status", "/autogis/status"):
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "service": "AutoGIS Live MCP Bridge",
                            "tool_count": len(bridge._engine.tools),
                            "url": bridge.url,
                        },
                    )
                    return
                if path in ("/tools", "/autogis/tools"):
                    tools_list = [
                        {
                            "name": spec.name,
                            "description": spec.description,
                            "risk": spec.risk,
                            "parameters": spec.parameters,
                        }
                        for spec in bridge._engine.tools.values()
                    ]
                    self._send_json(200, {"ok": True, "tools": tools_list})
                    return
                self._send_json(404, {"ok": False, "error": f"Unknown endpoint: {path}"})

            def do_POST(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path not in ("/call", "/autogis/call", "/mcp"):
                    self._send_json(404, {"ok": False, "error": f"Unknown endpoint: {path}"})
                    return
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"ok": False, "error": f"Invalid JSON: {exc}"})
                    return

                tool_name = str(body.get("tool") or body.get("name") or body.get("method") or "").strip()
                args = body.get("arguments") or body.get("params") or body.get("args") or {}
                if not isinstance(args, dict):
                    args = {}

                spec = bridge._engine.tools.get(tool_name)
                if spec is None:
                    self._send_json(404, {"ok": False, "error": f"Unknown AutoGIS tool: {tool_name!r}"})
                    return

                try:
                    if tool_name in bridge._engine.ASYNC_NETWORK_TOOLS:
                        res = spec.handler(
                            bridge._engine._iface,
                            args,
                            run_on_main=bridge._engine.run_on_main_thread,
                        )
                    else:
                        res = bridge._engine.run_on_main_thread(
                            lambda: spec.handler(bridge._engine._iface, args)
                        )
                    self._send_json(200, {"ok": True, "tool": tool_name, "result": res})
                except Exception as exc:
                    self._send_json(500, {"ok": False, "tool": tool_name, "error": str(exc)})

            def log_message(self, format: str, *args: object) -> None:
                return

        for candidate_port in (self._port, self._port + 1, 0):
            try:
                self._httpd = ThreadingHTTPServer((self._host, candidate_port), _Handler)
                self._port = int(self._httpd.server_address[1])
                self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
                self._thread.start()
                log_info(f"AutoGIS Live MCP Bridge listening at {self.url}")
                return True
            except OSError as exc:
                log_warn(f"AutoGIS MCP Bridge port {candidate_port} busy: {exc}")
                continue
        return False

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception as err:
                _ = err  # nosec B110
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
