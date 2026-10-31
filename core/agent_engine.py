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
    _main_invoke_sig = pyqtSignal(object)               # internal main-thread trampoline
    _async_tool_done_sig = pyqtSignal(object)           # internal async tool completion

    ASYNC_NETWORK_TOOLS = frozenset({
        "fetch_place_boundary",
        "fetch_osm_features",
        "compute_road_route",
        "fetch_stac_earth_data",
        "fetch_live_hazard_feed",
        "load_india_national_gis",
        "gee_download_dem", "gee_export_image", "gee_compute_index",
        "gee_image_collection", "gee_image_preview",
    })

    def __init__(self, iface, config: AutoGISConfig, parent=None) -> None:
        super().__init__(parent)
        self._iface = iface
        self._config = config
        self._tools: dict[str, GISToolSpec] = build_autogis_tools()
        self._messages: list[dict[str, Any]] = []
        self._active_run_id: str | None = None
        self._cancelled_runs: set[str] = set()
        self._step_count = 0
        self._current_plan_steps: list[dict[str, Any]] = []
        self._auto_nudge_count = 0
        self._lock = threading.Lock()
        self._active_workers = 0

        # Pending write-tool approval queue when in 'ask_write' mode
        self._awaiting_permission: dict[str, tuple[str, list[dict], int]] = {}

        # Main-thread event dispatch queue
        self._queue: queue.Queue[tuple] = queue.Queue()
        self._in_drain = False
        self._executing_tools = False
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._drain_queue)

        self._main_invoke_sig.connect(self._on_main_invoke)
        self._async_tool_done_sig.connect(self._on_async_tool_done)

        from .mcp_bridge import AutoGISMCPBridge

        self._mcp_bridge = AutoGISMCPBridge(self)
        self._mcp_bridge.start()

    def _on_main_invoke(self, pkg: object) -> None:
        fn, res_q = pkg
        try:
            QCoreApplication.processEvents()
            res = fn()
            QCoreApplication.processEvents()
            res_q.put(("ok", res))
        except Exception as exc:
            res_q.put(("err", exc))

    def run_on_main_thread(self, fn, timeout: float = 300.0) -> Any:
        res_q: queue.Queue = queue.Queue()
        self._main_invoke_sig.emit((fn, res_q))
        tag, payload = res_q.get(timeout=timeout)
        if tag == "err":
            raise payload
        return payload

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
        self._executing_tools = False
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
            ov = _tool_get_project_overview(self._iface, {})
            # Token-efficient compact serialization (saves ~65% tokens on large projects)
            lyrs = ov.get("layers") or []
            compact_lyrs = []
            for layer_item in lyrs[:40]:
                tag = f"{layer_item.get('name')}[{layer_item.get('geometry')},{layer_item.get('crs')},{layer_item.get('units')}]"
                if "feature_count" in layer_item:
                    tag += f"({layer_item['feature_count']} feats"
                    if layer_item.get("fields"):
                        tag += f", fields:{','.join(layer_item['fields'][:6])}"
                    tag += ")"
                compact_lyrs.append(tag)
            ctx_summary = (
                f"Project: {ov.get('project_file')} | CRS: {ov.get('crs')} ({ov.get('crs_units')}) | "
                f"Active: {ov.get('active_layer')} | Layers ({ov.get('layer_count')}): "
                + "; ".join(compact_lyrs)
            )
            if ov.get("crs_mismatches"):
                ctx_summary += f" | CRS Mismatches: {', '.join(ov['crs_mismatches'][:8])}"
        except Exception as exc:
            ctx_summary = f"Project context unavailable: {exc}"

        custom = self._config.custom_instructions.strip()
        custom_block = f"\nUser Preferences: {custom}\n" if custom else ""

        return (
            "You are **AutoGIS**, an Autonomous Geospatial AI Agent built into QGIS.\n"
            f"Live QGIS State: {ctx_summary}\n"
            f"{custom_block}"
            "Core Rules:\n"
            "1. **CRS Intelligence (CRITICAL)**: Always check project and layer CRS (`EPSG`, projected meters vs geographic degrees). "
            "`spatial_buffer` and `spatial_overlay` automatically reproject/align CRSs to metric UTM/Project CRS, and for custom `run_processing_algorithm` or `execute_pyqgis` always verify CRS alignment (`native:reprojectlayer`) before distance/area calculations.\n"
            "2. **Fast Step-by-Step Execution**: For multi-step workflows (2+ actions), call `update_agent_plan` to track phases (`pending`/`in_progress`/`completed`), and ALWAYS combine `update_agent_plan` with actual execution tool calls in the same turn (you may also batch multiple independent tool calls, such as multiple `fetch_osm_features` calls, in a single turn). Never waste a turn calling only `update_agent_plan`, and NEVER stop or report completion while any step in your plan is still `pending` or `in_progress`.\n"
            "3. **Universal Geospatial Workflow (NO TASK-SPECIFIC HARDCODING)**: Treat every user request as a general geospatial goal, not as a predefined recipe. Do not assume a specific index, city, dataset, layer name, CRS, or output layout unless the user specifies it. Inspect the current project and available inputs first. For QGIS operations, discover algorithms with `search_processing_algorithms`, inspect exact parameters with `get_algorithm_help`, and run suitable algorithms through `run_processing_algorithm`. For Earth Engine, use the user's configured credentials and choose datasets, bands and filters based on the request; use available GEE tools where they fit. Use STAC only as a disclosed alternative when GEE is unavailable or the user permits it.\n"
            "4. **Autonomous Execution and Verification (DO NOT DUMP CODE)**: Orchestrate a complete workflow using generic tools. Use `execute_pyqgis` only when generic QGIS Processing tools cannot express the operation; do not create or rely on one-off hardcoded implementations for NDVI or any other named analysis. Never tell the user to run code manually. Before processing, inspect the AOI, source data, CRS, resolution, NoData and output destination. Clip raster/vector outputs to the actual AOI polygon when available; use a bbox only when no polygon exists and disclose that. Preserve original user layers. Keep intermediate downloads, bands, temporary rasters and scratch layers out of the visible project unless requested. Add only final deliverables, use meaningful names, apply suitable styling, and make NoData transparent outside the AOI. On reruns, replace only prior AutoGIS-generated outputs for the same task; never delete user-owned layers. If a step fails, diagnose/retry safely or return the actual error—never claim success from partial/raw inputs. Verify output validity, dimensions/feature count, CRS, resolution and path before reporting completion.\n"
            "5. **Concise & Token-Efficient**: Keep responses clear, professional, direct, and without emojis."
        )

    def start_user_turn(self, user_text: str, attachments: list[str] | None = None,
                        layer_mentions: list[str] | None = None) -> str:
        run_id = "run_" + uuid.uuid4().hex[:10]
        selected_model = self._config.model.strip()
        if not selected_model:
            self.run_started.emit(run_id, "Select Model")
            self.token_chunk.emit(
                run_id,
                "**No AI Model Selected**\n\nPlease select your preferred AI Model from the **Model dropdown** at the bottom (or in **Settings**) before sending a message.",
            )
            self.run_finished.emit(run_id, "failed", "No AI Model selected")
            return run_id

        provider, api_key, _base_url, _api_model = self._config.resolve_connection(selected_model)
        if not api_key:
            self.run_started.emit(run_id, selected_model)
            self.token_chunk.emit(
                run_id,
                "**API Key Required**\n\nPlease click the **Settings** button in the top bar and enter your API Key (**Gemini**, **ChatGPT**, **Claude**, **DeepSeek**, or **OpenRouter**).",
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
            self._current_plan_steps = []
            self._auto_nudge_count = 0
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
        """Keep older tool outputs compact during long multi-step workflows to save user tokens."""
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        if len(tool_indices) <= 4:
            return messages
        older_set = set(tool_indices[:-4])
        compacted: list[dict[str, Any]] = []
        for idx, msg in enumerate(messages):
            if idx in older_set:
                content = str(msg.get("content") or "")
                if len(content) > 700:
                    m_copy = dict(msg)
                    m_copy["content"] = content[:700] + "\n...[step output summarized]"
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
        or_key = self._config.api_key
        max_tokens = self._config.max_tokens
        auto_fallback = self._config.auto_fallback_free
        tools_schema = self._build_tools_schema()

        self.status_updated.emit(run_id, "Thinking...")

        if not self._timer.isActive():
            self._timer.start()

        worker = threading.Thread(
            target=self._http_worker,
            args=(run_id, provider, api_key, or_key, base_url, api_model, max_tokens, auto_fallback, messages_snapshot, tools_schema),
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

        if hasattr(req, "full_url"):
            _parsed_req_url = urllib.parse.urlparse(req.full_url)
            if _parsed_req_url.scheme not in ("http", "https"):
                raise ValueError(f"Disallowed URL scheme: {_parsed_req_url.scheme}")
        with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310
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

    def _http_worker(self, run_id: str, provider: str, api_key: str, or_key: str, base_url: str, model: str,
                     max_tokens: int, auto_fallback: bool, messages: list[dict], tools: list[dict]) -> None:
        try:
            if run_id in self._cancelled_runs:
                return

            try:
                text_acc, reasoning_acc, tool_calls = self._stream_once(
                    run_id, api_key, base_url, model, max_tokens, messages, tools
                )
                # Free OpenRouter models occasionally emit an empty stream (0 tokens, 0 tool_calls) mid-workflow.
                # Retry once after a brief pause, and if still empty, try fallback models before giving up.
                if not text_acc.strip() and not tool_calls and run_id not in self._cancelled_runs:
                    log_info(f"Model {model} returned an empty stream; retrying once after 1.2s...")
                    self._post("status", run_id, f"Retrying {model.split('/')[-1]}...")
                    time.sleep(1.2)
                    text_acc, reasoning_acc, tool_calls = self._stream_once(
                        run_id, api_key, base_url, model, max_tokens, messages, tools
                    )
                    if not text_acc.strip() and not tool_calls and auto_fallback and or_key:
                        for fb_model in FALLBACK_CHAIN:
                            if fb_model == model and provider == "openrouter":
                                continue
                            try:
                                log_info(f"Model {model} returned empty stream twice; falling back to {fb_model}")
                                self._post("status", run_id, f"Switching to {fb_model.split('/')[-1]}...")
                                text_acc, reasoning_acc, tool_calls = self._stream_once(
                                    run_id, or_key, DEFAULT_BASE_URL, fb_model, min(max_tokens, 2048), messages, tools
                                )
                                if text_acc.strip() or tool_calls:
                                    break
                            except Exception as fb_exc:
                                log_warn(f"Empty-stream fallback {fb_model} failed: {fb_exc}")
            except urllib.error.HTTPError as he:
                body = ""
                try:
                    body = he.read().decode("utf-8", errors="replace")
                    err_json = json.loads(body)
                    err_msg = err_json.get("error", {}).get("message", str(he))
                except Exception:
                    err_msg = f"HTTP {he.code}: {he.reason}"

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
                    self._post("token", run_id, f"\n\n**AI Provider Error ({he.code}):** {err_msg}")
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
                # Check if there are still incomplete steps in the active agent plan
                with self._lock:
                    incomplete_steps = [
                        str(s.get("step") or s.get("title") or "").strip()
                        for s in self._current_plan_steps
                        if isinstance(s, dict)
                        and str(s.get("status") or "").strip().lower() not in ("completed", "done")
                        and str(s.get("step") or s.get("title") or "").strip()
                    ]
                    nudge_cnt = self._auto_nudge_count

                if incomplete_steps and nudge_cnt < 5 and self._step_count < MAX_AUTONOMOUS_STEPS:
                    with self._lock:
                        self._auto_nudge_count += 1
                        if text_acc.strip():
                            self._messages.append({"role": "assistant", "content": text_acc})
                        next_step_label = incomplete_steps[0]
                        self._messages.append({
                            "role": "user",
                            "content": (
                                f"[System Auto-Continue]: Your plan still has {len(incomplete_steps)} incomplete step(s), "
                                f"starting with: '{next_step_label}'. Do NOT stop early. "
                                "Call the required tool(s) now to execute the remaining steps and update_agent_plan."
                            ),
                        })
                    if text_acc.strip():
                        self._post("assistant_step_done", run_id, text_acc)
                    self._post("status", run_id, f"Continuing: {next_step_label[:48]}...")
                    self._post("continue_step", run_id)
                    return

                if not text_acc.strip():
                    text_acc = reasoning_acc.strip() or "Task complete. Let me know how else I can help with your QGIS project!"
                    self._post("token", run_id, text_acc)
                with self._lock:
                    self._messages.append({"role": "assistant", "content": text_acc})
                self._post("status", run_id, "")
                self._post("run_finished", run_id, "done", text_acc)

        except Exception as exc:
            log_warn(f"AutoGIS Engine worker error: {exc}")
            self._post("token", run_id, f"\n\n**Connection Error:** {exc}")
            self._post("run_finished", run_id, "failed", str(exc))
        finally:
            with self._lock:
                self._active_workers = max(0, self._active_workers - 1)

    def _drain_queue(self) -> None:
        if self._in_drain or self._executing_tools:
            return
        self._in_drain = True
        try:
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

            pending_tools: tuple[str, list[dict]] | None = None
            count = 0
            while count < 80:
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
                    pending_tools = payload
                    break
                elif kind == "continue_step":
                    rid = payload[0]
                    QTimer.singleShot(40, lambda r=rid: self._launch_step(r))
                elif kind == "run_finished":
                    self.status_updated.emit(payload[0], "")
                    self.run_finished.emit(*payload)

            _flush_tokens()

            if pending_tools is not None:
                rid, calls = pending_tools
                self._timer.stop()
                self._executing_tools = True
                QTimer.singleShot(
                    20,
                    lambda r=rid, c=calls: self._execute_tool_batch_main_thread(r, c, 0),
                )
                return

            with self._lock:
                workers = self._active_workers
                awaiting = bool(self._awaiting_permission)
            if workers <= 0 and not awaiting and self._queue.empty():
                self._timer.stop()
        finally:
            self._in_drain = False

    def _execute_tool_batch_main_thread(self, run_id: str, calls: list[dict], start_idx: int) -> None:
        if run_id in self._cancelled_runs:
            self._executing_tools = False
            return
        if start_idx >= len(calls):
            self._executing_tools = False
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
            self._executing_tools = False
            with self._lock:
                self._awaiting_permission[cid] = (run_id, calls, start_idx)
            self.status_updated.emit(run_id, f"Waiting for approval: {cname}")
            self.permission_requested.emit(run_id, cid, cname, cargs)
            return

        total_in_batch = len(calls)
        step_prefix = f"[{start_idx + 1}/{total_in_batch}] " if total_in_batch > 1 else ""
        self.status_updated.emit(run_id, f"{step_prefix}Running {cname}...")
        self.tool_call_started.emit(run_id, cid, cname, cargs)

        t0 = time.monotonic()

        # Execute network-heavy download tools on a background worker thread
        # so the QGIS GUI and live timer never freeze while downloading from Overpass/Nominatim/STAC!
        if spec is not None and cname in self.ASYNC_NETWORK_TOOLS:
            def _bg_worker(r=run_id, c=calls, idx=start_idx, call_id=cid, name=cname, args=cargs, s=spec, start_t=t0) -> None:
                err_flag = False
                try:
                    out = s.handler(self._iface, args, run_on_main=self.run_on_main_thread)
                    if isinstance(out, dict) and "error" in out:
                        err_flag = True
                except Exception as exc:
                    out = {"error": str(exc)}
                    err_flag = True
                ms = int((time.monotonic() - start_t) * 1000)
                self._async_tool_done_sig.emit((r, c, idx, call_id, name, out, ms, err_flag))

            threading.Thread(target=_bg_worker, daemon=True).start()
            return

        is_err = False
        if spec is None:
            res = {"error": f"Unknown tool '{cname}'."}
            is_err = True
        else:
            try:
                QCoreApplication.processEvents()
                res = spec.handler(self._iface, cargs)
                QCoreApplication.processEvents()
                if isinstance(res, dict) and "error" in res:
                    is_err = True
            except Exception as exc:
                res = {"error": str(exc)}
                is_err = True

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        self._finish_single_tool_main_thread(run_id, calls, start_idx, cid, cname, res, elapsed_ms, is_err)

    def _on_async_tool_done(self, payload: object) -> None:
        run_id, calls, start_idx, cid, cname, res, elapsed_ms, is_err = payload
        self._finish_single_tool_main_thread(run_id, calls, start_idx, cid, cname, res, elapsed_ms, is_err)

    def _finish_single_tool_main_thread(self, run_id: str, calls: list[dict], start_idx: int,
                                        cid: str, cname: str, res: Any, elapsed_ms: int, is_err: bool) -> None:
        if run_id in self._cancelled_runs:
            self._executing_tools = False
            return

        self.tool_call_finished.emit(run_id, cid, cname, res, elapsed_ms, is_err)

        if cname == "update_agent_plan" and isinstance(res, dict) and not is_err:
            steps_list = list(res.get("steps") or [])
            with self._lock:
                self._current_plan_steps = steps_list
            self.plan_updated.emit(
                run_id,
                str(res.get("plan_title") or "Autonomous GIS Plan"),
                steps_list,
            )
        elif not is_err:
            with self._lock:
                self._auto_nudge_count = 0

        if isinstance(res, dict) and res.get("image_path") and not is_err:
            self.map_captured.emit(run_id, str(res["image_path"]))

        try:
            res_str = json.dumps(res, ensure_ascii=False, default=str)
        except Exception:
            res_str = str(res)
        if len(res_str) > 8000:
            res_str = res_str[:8000] + "\n...[truncated]"

        with self._lock:
            self._messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "content": res_str,
            })

        # Yield 80ms back to the Qt event loop before the next tool in the batch so QGIS renders cleanly!
        if start_idx + 1 < len(calls):
            QTimer.singleShot(
                80,
                lambda r=run_id, c=calls, nxt=start_idx + 1: self._execute_tool_batch_main_thread(r, c, nxt),
            )
        else:
            self._executing_tools = False
            QTimer.singleShot(60, lambda r=run_id: self._launch_step(r))

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
