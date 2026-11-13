from __future__ import annotations

import base64
import json
import mimetypes
import os
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import data_dir, log_info, log_warn

DEFAULT_MCP_PORT = 8765
AUTOGIS_GAS_AGENT_ID = "autogis_qgis_agent"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutoGISMCPBridge:
    """Loopback HTTP JSON-RPC / MCP & GAS 1.0.0 Server Bridge for controlling live QGIS from external AI agents and GAS orchestrators."""

    def __init__(self, engine, host: str = "127.0.0.1", port: int = DEFAULT_MCP_PORT) -> None:
        self._engine = engine
        self._host = "127.0.0.1"
        self._port = int(port)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._gas_tasks: dict[str, dict[str, Any]] = {}
        self._gas_lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def _build_gas_capabilities(self) -> dict[str, Any]:
        base = self.url
        return {
            "$schema": "https://www.geospatial-agentic-services.online/schemas/capabilities.schema.json",
            "service": "GAS",
            "version": "1.0.0",
            "base_url": base,
            "request": "GetCapabilities",
            "title": "AutoGIS Studio Live QGIS GAS Server",
            "description": "Geospatial Agentic Services (GAS 1.0.0) endpoint embedded in AutoGIS Studio for QGIS.",
            "provider": {
                "name": "AutoGIS Studio for QGIS",
                "website": "https://autogis.princesite.in",
                "contact": {
                    "name": "Prince Suthar",
                    "email": "sutharprince098@gmail.com",
                },
            },
            "operations": [
                {
                    "operation_id": "get_capabilities",
                    "name": "GetCapabilities",
                    "method": "GET",
                    "path": "/?SERVICE=GAS&VERSION=1.0.0&REQUEST=GetCapabilities",
                    "url": f"{base}/?SERVICE=GAS&VERSION=1.0.0&REQUEST=GetCapabilities",
                    "description": "Returns the service-level GAS capabilities document.",
                },
                {
                    "operation_id": "describe_agent",
                    "name": "DescribeAgent",
                    "method": "GET",
                    "path": "/?SERVICE=GAS&VERSION=1.0.0&REQUEST=DescribeAgent&agent_id={agent_id}",
                    "url": f"{base}/?SERVICE=GAS&VERSION=1.0.0&REQUEST=DescribeAgent&agent_id={{agent_id}}",
                    "description": "Returns the DescribeAgent capability document for a published agent.",
                },
                {
                    "operation_id": "execute_task",
                    "name": "ExecuteTask",
                    "method": "POST",
                    "path": "/agents/{agent_id}/tasks",
                    "url": f"{base}/agents/{{agent_id}}/tasks",
                    "description": "Executes an agent task using sync, async, or stream mode.",
                },
                {
                    "operation_id": "get_task_status",
                    "name": "GetTaskStatus",
                    "method": "GET",
                    "path": "/agents/{agent_id}/tasks/{task_id}/status",
                    "url": f"{base}/agents/{{agent_id}}/tasks/{{task_id}}/status",
                    "description": "Returns the current status for an accepted task.",
                },
                {
                    "operation_id": "get_task_result",
                    "name": "GetTaskResult",
                    "method": "GET",
                    "path": "/agents/{agent_id}/tasks/{task_id}/result",
                    "url": f"{base}/agents/{{agent_id}}/tasks/{{task_id}}/result",
                    "description": "Returns the final standard GAS task response.",
                },
                {
                    "operation_id": "cancel_task",
                    "name": "CancelTask",
                    "method": "POST",
                    "path": "/agents/{agent_id}/tasks/{task_id}/cancel",
                    "url": f"{base}/agents/{{agent_id}}/tasks/{{task_id}}/cancel",
                    "description": "Requests cancellation for a running or queued task.",
                },
                {
                    "operation_id": "get_agent_status",
                    "name": "GetAgentStatus",
                    "method": "GET",
                    "path": "/agents/{agent_id}/status",
                    "url": f"{base}/agents/{{agent_id}}/status",
                    "description": "Returns status and health information for a published agent service.",
                },
            ],
            "agents": [
                {
                    "agent_id": AUTOGIS_GAS_AGENT_ID,
                    "name": "AutoGIS QGIS Autonomous Agent",
                    "description": f"Live QGIS Autonomous Geospatial Agent exposing {len(self._engine.tools)} GIS tools via GAS 1.0.0.",
                    "DescribeAgent": f"{base}/?SERVICE=GAS&VERSION=1.0.0&REQUEST=DescribeAgent&agent_id={AUTOGIS_GAS_AGENT_ID}",
                }
            ],
        }

    def _build_gas_describe_agent(self, agent_id: str) -> dict[str, Any]:
        base = self.url
        skills = [
            {
                "skill_id": spec.name,
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in list(self._engine.tools.values())[:65]
        ]
        return {
            "$schema": "https://www.geospatial-agentic-services.online/schemas/describe_agent.schema.json",
            "profile": {
                "agent_id": agent_id,
                "name": "AutoGIS QGIS Autonomous Agent",
                "description": f"Autonomous QGIS Geospatial Agent providing {len(self._engine.tools)} tools for vector/raster processing, GEE, OSM, STAC, PyQGIS, and cartography.",
                "version": "1.0.6",
                "base_url": f"{base}/agents/{agent_id}",
                "provider": {
                    "name": "AutoGIS Studio for QGIS",
                    "website": "https://autogis.princesite.in",
                },
            },
            "keywords": ["qgis", "pyqgis", "autogis", "vector", "raster", "gee", "osm", "gas"],
            "skills": skills,
            "execute_task": {
                "operation_id": "execute_task",
                "name": "ExecuteTask",
                "modes": ["sync", "async", "stream"],
                "task": {"instructions": {"required": True, "description": "Natural-language instructions or tool name."}},
                "inputs": {"input_datasets": {"required": False, "supported_item_types": ["URL", "server_path", "encoded_file_object"]}},
                "outputs": {"artifact_delivery": {"default": "URL", "allowed_values": ["URL", "Encoded"]}},
            },
            "conformance": {"gas_version": "1.0.0"},
        }

    def _execute_gas_task_payload(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        t0 = time.monotonic()
        task_id = "task_" + uuid.uuid4().hex[:12]
        task_block = body.get("task") if isinstance(body.get("task"), dict) else {}
        instructions = str(task_block.get("instructions") or body.get("instructions") or "").strip()
        params = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
        outputs_req = body.get("outputs") if isinstance(body.get("outputs"), dict) else {}
        delivery = str(outputs_req.get("artifact_delivery") or "URL").strip()

        # Materialize any base64-encoded input datasets to disk
        inputs_block = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}
        raw_datasets = inputs_block.get("input_datasets") if isinstance(inputs_block.get("input_datasets"), list) else []
        materialized_files: list[str] = []
        for idx, ds in enumerate(raw_datasets):
            if isinstance(ds, dict) and ds.get("data"):
                fname = str(ds.get("filename") or f"input_{idx}.dat")
                safe_fname = "".join(c if c.isalnum() or c in "._-" else "_" for c in os.path.basename(fname))
                out_dir = os.path.join(data_dir(), "gas_inputs")
                os.makedirs(out_dir, exist_ok=True)
                fpath = os.path.join(out_dir, f"{task_id}_{safe_fname}")
                try:
                    Path(fpath).write_bytes(base64.b64decode(str(ds["data"])))
                    materialized_files.append(fpath)
                except Exception as exc:
                    log_warn(f"Could not decode GAS input dataset: {exc}")
            elif isinstance(ds, str) and ds.strip():
                materialized_files.append(ds.strip())

        # Determine which AutoGIS tool to invoke
        tool_name = str(params.get("tool") or params.get("tool_name") or "").strip()
        tool_args = dict(params.get("arguments") or params.get("tool_args") or params)
        tool_args.pop("tool", None)
        tool_args.pop("tool_name", None)
        tool_args.pop("arguments", None)
        tool_args.pop("tool_args", None)

        if not tool_name:
            # Match tool name if instructions directly name a tool or default to get_project_overview
            if instructions in self._engine.tools:
                tool_name = instructions
            else:
                for cand_name in self._engine.tools:
                    if cand_name in instructions.lower():
                        tool_name = cand_name
                        break
            if not tool_name:
                tool_name = "get_project_overview"

        spec = self._engine.tools.get(tool_name)
        has_error = False
        err_msg = None
        if spec is None:
            res: dict[str, Any] = {"error": f"Unknown AutoGIS tool '{tool_name}'"}
            has_error = True
            err_msg = res["error"]
        else:
            try:
                if tool_name in self._engine.ASYNC_NETWORK_TOOLS:
                    res = spec.handler(
                        self._engine._iface,
                        tool_args,
                        run_on_main=self._engine.run_on_main_thread,
                    )
                else:
                    res = self._engine.run_on_main_thread(
                        lambda: spec.handler(self._engine._iface, tool_args)
                    )
                if isinstance(res, dict) and "error" in res:
                    has_error = True
                    err_msg = str(res["error"])
            except Exception as exc:
                res = {"error": str(exc)}
                has_error = True
                err_msg = str(exc)

        # Build GAS artifacts from any file paths returned by the tool
        artifacts: list[dict[str, Any]] = []
        if isinstance(res, dict):
            for key in ("file_path", "geojson_file", "geojson_layer", "html_report", "html_player_path", "interactive_3d_html", "interactive_report_html", "image_path"):
                fpath = res.get(key)
                if isinstance(fpath, str) and os.path.isfile(fpath):
                    p = Path(fpath)
                    mime, _ = mimetypes.guess_type(p.name)
                    art_entry: dict[str, Any] = {
                        "name": p.stem,
                        "role": "dataset" if p.suffix.lower() in (".geojson", ".gpkg", ".tif", ".tiff", ".shp", ".csv") else "output",
                        "format": p.suffix.lstrip(".") or "dat",
                        "filename": p.name,
                        "original_filename": p.name,
                        "type": "downloadable_file",
                        "mime_type": mime or "application/octet-stream",
                        "size_bytes": p.stat().st_size,
                        "url": f"{self.url}/agents/{agent_id}/data/{urllib.parse.quote(p.name)}?path={urllib.parse.quote(str(p))}",
                    }
                    if delivery.lower() == "encoded" and p.stat().st_size <= 25 * 1024 * 1024:
                        art_entry["encoding"] = "base64"
                        art_entry["data"] = base64.b64encode(p.read_bytes()).decode("ascii")
                    artifacts.append(art_entry)

        duration = round(time.monotonic() - t0, 3)
        status_str = "failed" if has_error else "successful"
        task_resp = {
            "response": {
                "service": "GAS",
                "version": "1.0.0",
                "completed_at": _iso_now(),
            },
            "task": {
                "id": task_id,
                "status": status_str,
                "mode": str(task_block.get("mode") or "sync"),
                "terminal": True,
            },
            "agent": {
                "id": agent_id,
                "name": "AutoGIS QGIS Autonomous Agent",
                "version": "1.0.6",
            },
            "outputs": {
                "summary": f"Executed AutoGIS tool '{tool_name}'." if not has_error else f"Error in '{tool_name}': {err_msg}",
                "result": res,
                "artifacts": artifacts,
                "materialized_inputs": materialized_files,
            },
            "execution": {
                "status": status_str,
                "duration_seconds": duration,
                "iterations": 1,
                "tool_executed": tool_name,
            },
            "provenance": {
                "llm_calls": 0,
                "tool_calls": 1,
                "number_of_artifacts": len(artifacts),
            },
            "diagnostics": {
                "has_error": has_error,
                "error": err_msg,
                "warnings": [],
            },
        }
        with self._gas_lock:
            self._gas_tasks[task_id] = task_resp
        return task_resp

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
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(parsed.query).items() if v}

                # 1. Check GAS 1.0.0 query interface (`/?SERVICE=GAS&VERSION=1.0.0&REQUEST=...`)
                if q.get("service", "").upper() == "GAS" or q.get("request", "").lower() in ("getcapabilities", "describeagent"):
                    req_type = q.get("request", "GetCapabilities").lower()
                    if req_type == "getcapabilities":
                        self._send_json(200, bridge._build_gas_capabilities())
                        return
                    if req_type == "describeagent":
                        aid = q.get("agent_id", AUTOGIS_GAS_AGENT_ID)
                        self._send_json(200, bridge._build_gas_describe_agent(aid))
                        return
                    self._send_json(400, {"error": {"code": "INVALID_ARGUMENT", "message": f"Unknown GAS request '{req_type}'."}})
                    return

                # 2. Check GAS `/agents/{agent_id}...` routes
                if path.startswith("/agents/"):
                    parts = [p for p in path.split("/") if p]
                    # parts[0] == "agents", parts[1] == agent_id
                    if len(parts) >= 2:
                        aid = parts[1]
                        if len(parts) == 2:
                            self._send_json(200, bridge._build_gas_describe_agent(aid))
                            return
                        if len(parts) == 3 and parts[2] == "status":
                            self._send_json(200, {
                                "status": "available",
                                "agent_id": aid,
                                "service_base": f"/agents/{aid}",
                                "tool_count": len(bridge._engine.tools),
                            })
                            return
                        if len(parts) == 4 and parts[2] == "data":
                            raw_file = q.get("path", "")
                            if raw_file and os.path.isfile(raw_file):
                                data_bytes = Path(raw_file).read_bytes()
                                mime, _ = mimetypes.guess_type(raw_file)
                                self.send_response(200)
                                self.send_header("Content-Type", mime or "application/octet-stream")
                                self.send_header("Content-Length", str(len(data_bytes)))
                                self.end_headers()
                                self.wfile.write(data_bytes)
                                return
                            self._send_json(404, {"error": "Artifact file not found"})
                            return
                        if len(parts) == 5 and parts[2] == "tasks":
                            tid = parts[3]
                            op = parts[4]
                            with bridge._gas_lock:
                                task_obj = bridge._gas_tasks.get(tid)
                            if task_obj is None:
                                self._send_json(404, {"error": {"code": "TASK_NOT_FOUND", "message": f"Task '{tid}' not found."}})
                                return
                            if op == "status":
                                self._send_json(200, {"task": task_obj.get("task", {})})
                                return
                            if op == "result":
                                self._send_json(200, task_obj)
                                return

                # 3. Standard AutoGIS MCP routes
                if path in ("/", "/status", "/autogis/status"):
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "service": "AutoGIS Live MCP & GAS 1.0.0 Bridge",
                            "gas_version": "1.0.0",
                            "gas_agent_id": AUTOGIS_GAS_AGENT_ID,
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
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"ok": False, "error": f"Invalid JSON: {exc}"})
                    return

                # 1. Check GAS `/agents/{agent_id}/tasks` and `/agents/{agent_id}/tasks/{task_id}/cancel`
                if path.startswith("/agents/"):
                    parts = [p for p in path.split("/") if p]
                    if len(parts) == 3 and parts[2] == "tasks":
                        aid = parts[1]
                        task_block = body.get("task") if isinstance(body.get("task"), dict) else {}
                        mode = str(task_block.get("mode") or "sync").strip().lower()
                        task_resp = bridge._execute_gas_task_payload(aid, body)
                        if mode == "stream":
                            ev1 = {
                                "timestamp": _iso_now(),
                                "event": "progress",
                                "agent": {"id": aid, "name": "AutoGIS QGIS Autonomous Agent"},
                                "message": "Executing task in AutoGIS Studio...",
                            }
                            ev2 = {
                                "timestamp": _iso_now(),
                                "event": "task_result",
                                "payload": task_resp,
                            }
                            ndjson_bytes = (json.dumps(ev1) + "\n" + json.dumps(ev2) + "\n").encode("utf-8")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                            self.send_header("Content-Length", str(len(ndjson_bytes)))
                            self.end_headers()
                            self.wfile.write(ndjson_bytes)
                            return
                        self._send_json(200, task_resp)
                        return

                    if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "cancel":
                        tid = parts[3]
                        with bridge._gas_lock:
                            task_obj = bridge._gas_tasks.get(tid)
                            if task_obj is not None:
                                task_obj["task"]["status"] = "canceled"
                                task_obj["execution"]["status"] = "canceled"
                        if task_obj is None:
                            self._send_json(404, {"error": {"code": "TASK_NOT_FOUND", "message": f"Task '{tid}' not found."}})
                            return
                        self._send_json(200, task_obj)
                        return

                # 2. Standard AutoGIS MCP `/call` route
                if path not in ("/call", "/autogis/call", "/mcp"):
                    self._send_json(404, {"ok": False, "error": f"Unknown endpoint: {path}"})
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
                log_info(f"AutoGIS Live MCP & GAS 1.0.0 Bridge listening at {self.url}")
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
