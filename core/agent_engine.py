from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from qgis.PyQt.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal

from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, FALLBACK_CHAIN, AutoGISConfig, log_info, log_warn
from .document_tools import summarize_attached_path
from .gis_tools import GISToolSpec, _tool_get_project_overview, build_autogis_tools

MAX_AUTONOMOUS_STEPS = 30


class AutoGISEngine(QObject):
    """Thread-safe, multi-step autonomous AI agent engine for AutoGIS Studio."""

    run_started = pyqtSignal(str, str)                  # (run_id, model)
    status_updated = pyqtSignal(str, str)               # (run_id, status_text)
    reasoning_chunk = pyqtSignal(str, str)              # (run_id, reasoning_delta)
    token_chunk = pyqtSignal(str, str)                  # (run_id, content_delta)
    assistant_step_done = pyqtSignal(str, str)          # (run_id, step_text)
    tool_call_started = pyqtSignal(str, str, str, object)  # (run_id, call_id, name, args)
    tool_call_finished = pyqtSignal(str, str, str, object, int, bool)  # (run_id, call_id, name, result, ms, is_err)
    plan_updated = pyqtSignal(str, str, object)         # (run_id, plan_title, steps_list)
    map_captured = pyqtSignal(str, str)                 # (run_id, image_path)
    permission_requested = pyqtSignal(str, str, str, object)  # (run_id, call_id, name, args)
    run_finished = pyqtSignal(str, str, str)            # (run_id, status, final_text)

    def __init__(self, iface, config: AutoGISConfig, parent=None) -> None:
        super().__init__(parent)
        self._iface = iface
        self._config = config
        self._tools: dict[str, GISToolSpec] = build_autogis_tools()
        self._messages: list[dict[str, Any]] = []
        self._active_run_id: str | None = None
        self._cancelled_runs: set[str] = set()
        self._step_count = 0
        self._lock = threading.Lock()
        self._active_workers = 0

        # Pending write-tool approval queue when in 'ask_write' mode
        self._awaiting_permission: dict[str, tuple[str, list[dict], int]] = {}

        # Main-thread event dispatch queue
        self._queue: queue.Queue[tuple] = queue.Queue()
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._drain_queue)

    @property
    def tools(self) -> dict[str, GISToolSpec]:
        return self._tools

    @property
    def messages(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._messages)

    def load_messages(self, history: list[dict[str, Any]]) -> None:
        with self._lock:
            self._messages = list(history or [])

    def clear_conversation(self) -> None:
        with self._lock:
            self._messages.clear()
            self._awaiting_permission.clear()

    def cancel_current_run(self) -> None:
        with self._lock:
            rid = self._active_run_id
            if rid:
                self._cancelled_runs.add(rid)
                self._awaiting_permission.clear()
        if rid:
            self.status_updated.emit(rid, "Stopped by user")
            self.run_finished.emit(rid, "cancelled", "Run cancelled by user.")

    def _post(self, kind: str, *payload: Any) -> None:
        self._queue.put((kind, payload))

    def _build_tools_schema(self) -> list[dict[str, Any]]:
        if self._config.execution_mode == "chat_only":
            return []
        schemas = []
        for spec in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            })
        return schemas

    def _build_system_prompt(self) -> str:
        try:
            overview = _tool_get_project_overview(self._iface, {})
            ctx_json = json.dumps(overview, ensure_ascii=False, indent=2)
        except Exception as exc:
            ctx_json = f'{{"note": "Could not read project context: {exc}"}}'

        custom = self._config.custom_instructions.strip()
        custom_block = f"\nUser Custom Preferences:\n{custom}\n" if custom else ""

        return (
            "You are **AutoGIS**, an elite Autonomous Geospatial AI Agent and Spatial Analysis Studio built directly into QGIS.\n"
            "You have 34+ native GIS, Live Earth Data, and Document/PDF tools to download real-world boundaries, OpenStreetMap vectors, OSRM routes, "
            "STAC satellite/DEM rasters, read large PDFs/documents/folders, style layers, run QGIS Processing algorithms, and execute PyQGIS code.\n\n"
            f"### Live QGIS Project State:\n```json\n{ctx_json}\n```\n"
            f"{custom_block}\n"
            "### Autonomous GIS Agent Capabilities & Rules:\n"
            "1. **Live Data Connectors (No external files needed)**:\n"
            "   - **Place / Admin Boundaries**: Use `fetch_place_boundary(place='...')` to geocode and load exact polygon boundaries for any city, district, state, or country.\n"
            "   - **OpenStreetMap Vectors**: Use `fetch_osm_features(category=..., place=...)` to download live `buildings`, `roads`, `rivers`, `water`, `railways`, `landuse`, `parks`, `hospitals`, `schools`, `power`, or `boundary` directly into QGIS.\n"
            "   - **Road Routing**: Use `compute_road_route(origin=..., destination=..., profile='driving'|'walking'|'cycling')` for real OSRM shortest paths.\n"
            "   - **Earth Observation & Terrain Rasters (STAC)**: Use `fetch_stac_earth_data(dataset='dem'|'sentinel2'|'lulc', place=...)` to stream 30m Copernicus Elevation DEM, 10m Sentinel-2 True Color imagery, or 10m Esri Land Cover.\n"
            "   - **Saved QGIS Servers**: Use `list_saved_qgis_connections` and `load_saved_qgis_connection` for user's saved XYZ, WMS (Bhuvan), or WFS servers.\n"
            "   - **Uploaded PDFs, Documents & Folders**: Use `read_uploaded_file_or_pdf` to read, paginate, or search inside large PDFs, Word docs, Excel sheets, CSVs, or folders.\n"
            "2. **Large-Task Decomposition & Step-by-Step Execution (CRITICAL)**:\n"
            "   - Whenever the user gives a large, multi-layer, or complex workflow (2+ actions, suitability modeling, batch processing, or multi-dataset analysis), **ALWAYS divide the work into clear sequential parts/phases**.\n"
            "   - First call `update_agent_plan` to display all steps (`pending` / `in_progress` / `completed`) in the UI checklist.\n"
            "   - Execute **step by step (1 to 2 tool calls per turn)** instead of firing many heavy tools at once. After each phase completes, verify the result, update `update_agent_plan`, and proceed to the next part until 100% of the user's request is finished.\n"
            "3. **Self-Healing & Zero-Error Recovery**: If any tool returns an error (e.g. missing field name, CRS mismatch, or invalid parameter), inspect the layer (`inspect_layer`) or algorithm help (`get_algorithm_help`) and automatically retry with corrected parameters or `execute_pyqgis` instead of stopping.\n"
            "4. **Visual Polish**: When loading new layers or finishing a spatial analysis, add a basemap (`add_basemap`) if none is loaded, apply clean cartographic styling (`style_vector_layer`), and summarize key findings clearly in Markdown."
        )

    def start_user_turn(self, user_text: str, attachments: list[str] | None = None,
                        layer_mentions: list[str] | None = None) -> str:
        run_id = "run_" + uuid.uuid4().hex[:10]
        selected_model = self._config.model.strip()
        if not selected_model:
            self.run_started.emit(run_id, "Select Model")
            self.token_chunk.emit(
                run_id,
                "ℹ️ **No AI Model Selected**\n\nPlease select your preferred AI Model from the **Model dropdown** at the bottom (or in **⚙ Settings**) before sending a message.",
            )
            self.run_finished.emit(run_id, "failed", "No AI Model selected")
            return run_id

        provider, api_key, _base_url, _api_model = self._config.resolve_connection(selected_model)
        if not api_key:
            self.run_started.emit(run_id, selected_model)
            self.token_chunk.emit(
                run_id,
                "⚠️ **API Key Required**\n\nPlease click the **⚙ Settings** button in the top bar and enter your API Key (**Gemini**, **ChatGPT**, **Claude**, **DeepSeek**, or **Gateway Key**).",
            )
            self.run_finished.emit(run_id, "failed", "Missing API Key")
            return run_id

        extra_blocks = []
        if layer_mentions:
            extra_blocks.append("Referenced Layers: " + ", ".join(f"`{m}`" for m in layer_mentions))
        if attachments:
            att_summaries = [summarize_attached_path(p) for p in attachments]
            extra_blocks.append("### Attached User Files / Documents / Folders:\n" + "\n\n".join(att_summaries))
        full_user_prompt = user_text.strip()
        if extra_blocks:
            full_user_prompt += "\n\n" + "\n".join(extra_blocks)

        sys_prompt = self._build_system_prompt()
        with self._lock:
            self._active_run_id = run_id
            self._step_count = 0
            if not self._messages or self._messages[0].get("role") != "system":
                self._messages.insert(0, {"role": "system", "content": sys_prompt})
            else:
                self._messages[0] = {"role": "system", "content": sys_prompt}
            self._messages.append({"role": "user", "content": full_user_prompt})

        self.run_started.emit(run_id, self._config.model)
        self._launch_step(run_id)
        return run_id

    @staticmethod
    def _compact_messages_for_llm(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep older tool outputs compact during long multi-step workflows to prevent context bloat."""
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        if len(tool_indices) <= 6:
            return messages
        older_set = set(tool_indices[:-6])
        compacted: list[dict[str, Any]] = []
        for idx, msg in enumerate(messages):
            if idx in older_set:
                content = str(msg.get("content") or "")
                if len(content) > 1500:
                    m_copy = dict(msg)
                    m_copy["content"] = content[:1500] + "\n...[completed step output summarized]"
                    compacted.append(m_copy)
                    continue
            compacted.append(msg)
        return compacted

    def _launch_step(self, run_id: str) -> None:
        with self._lock:
            if run_id in self._cancelled_runs:
                return
            self._step_count += 1
            if self._step_count > MAX_AUTONOMOUS_STEPS:
                self._post("run_finished", run_id, "done", "Reached maximum autonomous tool steps.")
                return
            messages_snapshot = self._compact_messages_for_llm(list(self._messages))
            self._active_workers += 1

        provider, api_key, base_url, api_model = self._config.resolve_connection(self._config.model)
        max_tokens = self._config.max_tokens
        auto_fallback = self._config.auto_fallback_free
        tools_schema = self._build_tools_schema()

        self.status_updated.emit(run_id, "Thinking...")

        if not self._timer.isActive():
            self._timer.start()

        worker = threading.Thread(
            target=self._http_worker,
            args=(run_id, provider, api_key, base_url, api_model, max_tokens, auto_fallback, messages_snapshot, tools_schema),
            daemon=True,
        )
        worker.start()

    def _stream_once(self, run_id: str, api_key: str, base_url: str, model: str,
                     max_tokens: int, messages: list[dict], tools: list[dict]) -> tuple[str, str, list[dict]]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://qgis.org",
                "X-Title": "AutoGIS Studio for QGIS",
            },
            method="POST",
        )

        text_acc = ""
        reasoning_acc = ""
        tc_map: dict[int, dict[str, str]] = {}
        short_model = model.split("/")[-1] if "/" in model else model
        last_status_at = time.monotonic()

        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw_line in resp:
                if run_id in self._cancelled_runs:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if isinstance(chunk, dict) and "error" in chunk:
                    err = chunk["error"]
                    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    raise RuntimeError(msg)

                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                r_delta = delta.get("reasoning") or delta.get("reasoning_content")
                if r_delta:
                    reasoning_acc += str(r_delta)
                    self._post("reasoning", run_id, str(r_delta))
                    now = time.monotonic()
                    if not text_acc and (now - last_status_at) >= 0.7:
                        last_status_at = now
                        self._post("status", run_id, "Reasoning...")

                c_delta = delta.get("content")
                if c_delta:
                    text_acc += str(c_delta)
                    self._post("token", run_id, str(c_delta))

                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    if idx not in tc_map:
                        tc_map[idx] = {
                            "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.get("id"):
                        tc_map[idx]["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        tc_map[idx]["name"] += fn["name"]
                    if fn.get("arguments"):
                        tc_map[idx]["arguments"] += fn["arguments"]

        tool_calls = [tc_map[k] for k in sorted(tc_map.keys()) if tc_map[k].get("name")]
        return text_acc, reasoning_acc, tool_calls

    def _http_worker(self, run_id: str, provider: str, api_key: str, base_url: str, model: str,
                     max_tokens: int, auto_fallback: bool, messages: list[dict], tools: list[dict]) -> None:
        try:
            if run_id in self._cancelled_runs:
                return

            try:
                text_acc, reasoning_acc, tool_calls = self._stream_once(
                    run_id, api_key, base_url, model, max_tokens, messages, tools
                )
            except urllib.error.HTTPError as he:
                body = ""
                try:
                    body = he.read().decode("utf-8", errors="replace")
                    err_json = json.loads(body)
                    err_msg = err_json.get("error", {}).get("message", str(he))
                except Exception:
                    err_msg = f"HTTP {he.code}: {he.reason}"

                or_key = self._config.api_key
                recovered = False

                if tools and he.code in (400, 422) and ("tool" in err_msg.lower() or "tool" in body.lower()):
                    try:
                        log_info(f"Model {model} rejected tools; retrying in direct chat mode.")
                        self._post("status", run_id, f"Retrying {model.split('/')[-1]} without tools...")
                        text_acc, reasoning_acc, tool_calls = self._stream_once(
                            run_id, api_key, base_url, model, max_tokens, messages, []
                        )
                        recovered = True
                    except Exception:
                        recovered = False

                if not recovered and auto_fallback and or_key and he.code in (400, 401, 402, 403, 404, 429, 500, 502, 503):
                    for fb_model in FALLBACK_CHAIN:
                        if fb_model == model and provider == "openrouter":
                            continue
                        try:
                            log_info(f"Model {model} returned {he.code}; auto-falling back to {fb_model}")
                            self._post("status", run_id, f"Auto-switching to {fb_model.split('/')[-1]}...")
                            text_acc, reasoning_acc, tool_calls = self._stream_once(
                                run_id, or_key, DEFAULT_BASE_URL, fb_model, min(max_tokens, 2048), messages, tools
                            )
                            recovered = True
                            break
                        except Exception as fb_exc:
                            log_warn(f"Fallback model {fb_model} also failed: {fb_exc}")
                            continue

                if not recovered:
                    self._post("token", run_id, f"\n\n⚠️ **AI Provider Error ({he.code}):** {err_msg}")
                    self._post("run_finished", run_id, "failed", err_msg)
                    return

            if run_id in self._cancelled_runs:
                return

            if tool_calls:
                assistant_tc_payload = []
                parsed_calls = []
                for tc in tool_calls:
                    cid = tc["id"]
                    cname = tc["name"].strip()
                    raw_args = tc["arguments"].strip() or "{}"
                    try:
                        args_dict = json.loads(raw_args)
                        if not isinstance(args_dict, dict):
                            args_dict = {}
                    except json.JSONDecodeError:
                        args_dict = {}
                    assistant_tc_payload.append({
                        "id": cid,
                        "type": "function",
                        "function": {"name": cname, "arguments": raw_args},
                    })
                    parsed_calls.append({"id": cid, "name": cname, "args": args_dict})

                with self._lock:
                    self._messages.append({
                        "role": "assistant",
                        "content": text_acc or "",
                        "tool_calls": assistant_tc_payload,
                    })

                if text_acc.strip():
                    self._post("assistant_step_done", run_id, text_acc)
                self._post("exec_tools", run_id, parsed_calls)
            else:
                if not text_acc.strip():
                    text_acc = reasoning_acc.strip() or "Task complete. Let me know how else I can help with your QGIS project!"
                    self._post("token", run_id, text_acc)
                with self._lock:
                    self._messages.append({"role": "assistant", "content": text_acc})
                self._post("status", run_id, "")
                self._post("run_finished", run_id, "done", text_acc)

        except Exception as exc:
            log_warn(f"AutoGIS Engine worker error: {exc}")
            self._post("token", run_id, f"\n\n⚠️ **Connection Error:** {exc}")
            self._post("run_finished", run_id, "failed", str(exc))
        finally:
            with self._lock:
                self._active_workers = max(0, self._active_workers - 1)

    def _drain_queue(self) -> None:
        token_buf_run: str | None = None
        token_buf: list[str] = []

        def _flush_tokens() -> None:
            nonlocal token_buf_run
            if token_buf_run is not None and token_buf:
                text = "".join(token_buf)
                token_buf.clear()
                rid = token_buf_run
                token_buf_run = None
                self.token_chunk.emit(rid, text)

        count = 0
        while count < 100:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            count += 1

            if kind == "token":
                rid, chunk = payload
                if token_buf_run in (None, rid):
                    token_buf_run = rid
                    token_buf.append(chunk)
                    continue
                _flush_tokens()
                token_buf_run = rid
                token_buf.append(chunk)
                continue

            _flush_tokens()
            if kind == "status":
                self.status_updated.emit(*payload)
            elif kind == "reasoning":
                self.reasoning_chunk.emit(*payload)
            elif kind == "assistant_step_done":
                self.assistant_step_done.emit(*payload)
            elif kind == "exec_tools":
                rid, calls = payload
                self._execute_tool_batch_main_thread(rid, calls, 0)
            elif kind == "run_finished":
                self.status_updated.emit(payload[0], "")
                self.run_finished.emit(*payload)

        _flush_tokens()

        with self._lock:
            workers = self._active_workers
            awaiting = bool(self._awaiting_permission)
        if workers <= 0 and not awaiting and self._queue.empty():
            self._timer.stop()

    def _execute_tool_batch_main_thread(self, run_id: str, calls: list[dict], start_idx: int) -> None:
        if run_id in self._cancelled_runs:
            return
        if start_idx >= len(calls):
            self._launch_step(run_id)
            return

        mode = self._config.execution_mode
        tc = calls[start_idx]
        cid = tc["id"]
        cname = tc["name"]
        cargs = tc["args"]
        spec = self._tools.get(cname)

        # Check if write permission is needed
        if mode == "ask_write" and spec is not None and spec.risk == "write" and not tc.get("_approved"):
            with self._lock:
                self._awaiting_permission[cid] = (run_id, calls, start_idx)
            self.status_updated.emit(run_id, f"Waiting for approval: {cname}")
            self.permission_requested.emit(run_id, cid, cname, cargs)
            return

        total_in_batch = len(calls)
        step_prefix = f"[{start_idx + 1}/{total_in_batch}] " if total_in_batch > 1 else ""
        self.status_updated.emit(run_id, f"{step_prefix}Running {cname}...")
        self.tool_call_started.emit(run_id, cid, cname, cargs)

        try:
            QCoreApplication.processEvents()
        except Exception:
            pass

        t0 = time.monotonic()
        is_err = False
        if spec is None:
            res = {"error": f"Unknown tool '{cname}'."}
            is_err = True
        else:
            try:
                res = spec.handler(self._iface, cargs)
                if isinstance(res, dict) and "error" in res:
                    is_err = True
            except Exception as exc:
                res = {"error": str(exc)}
                is_err = True

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        self.tool_call_finished.emit(run_id, cid, cname, res, elapsed_ms, is_err)

        if cname == "update_agent_plan" and isinstance(res, dict) and not is_err:
            self.plan_updated.emit(
                run_id,
                str(res.get("plan_title") or "Autonomous GIS Plan"),
                list(res.get("steps") or []),
            )

        if isinstance(res, dict) and res.get("image_path") and not is_err:
            self.map_captured.emit(run_id, str(res["image_path"]))

        try:
            res_str = json.dumps(res, ensure_ascii=False, default=str)
        except Exception:
            res_str = str(res)
        if len(res_str) > 16000:
            res_str = res_str[:16000] + "\n...[truncated]"

        with self._lock:
            self._messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "content": res_str,
            })

        try:
            QCoreApplication.processEvents()
        except Exception:
            pass

        # Yield 35ms back to the Qt event loop before the next tool in the batch so QGIS never freezes!
        if start_idx + 1 < len(calls):
            QTimer.singleShot(
                35,
                lambda r=run_id, c=calls, nxt=start_idx + 1: self._execute_tool_batch_main_thread(r, c, nxt),
            )
        else:
            self._launch_step(run_id)

    def resolve_permission(self, call_id: str, approved: bool) -> None:
        with self._lock:
            entry = self._awaiting_permission.pop(call_id, None)
        if entry is None:
            return
        run_id, calls, idx = entry
        tc = calls[idx]
        if approved:
            tc["_approved"] = True
            self._execute_tool_batch_main_thread(run_id, calls, idx)
        else:
            res = {"error": "User declined permission to execute this write tool."}
            self.tool_call_started.emit(run_id, call_id, tc["name"], tc["args"])
            self.tool_call_finished.emit(run_id, call_id, tc["name"], res, 0, True)
            with self._lock:
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(res),
                })
            self._execute_tool_batch_main_thread(run_id, calls, idx + 1)
