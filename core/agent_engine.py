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

from .config import DEFAULT_BASE_URL, FALLBACK_CHAIN, AutoGISConfig, log_info, log_warn
from .document_tools import summarize_attached_path
from .extended_gis_tools import _read_persistent_memory
from .gis_tools import GISToolSpec, _tool_get_project_overview, build_autogis_tools

MAX_AUTONOMOUS_STEPS = 30


# ── Thematic Tool Clusters for Dynamic Intent Routing ────────────────────────
CORE_TOOL_NAMES = frozenset({
    "update_agent_plan",
    "get_project_overview",
    "get_layer_info",
    "execute_pyqgis",
    "run_processing_algorithm",
    "search_processing_algorithms",
    "get_algorithm_help",
    "spatial_buffer",
    "spatial_overlay",
    "clip_raster_by_mask",
    "run_raster_calculator",
    "apply_layer_style",
    "create_print_layout",
    "export_map_image",
    "export_layer",
    "load_vector_file",
    "load_raster_file",
    "create_vector_layer",
    "zoom_to_layer",
    "zoom_to_coordinate",
    "set_layer_visibility",
    "remove_layer",
    "undo_project_checkpoint",
    "create_project_checkpoint",
})

ACQUISITION_TOOL_NAMES = frozenset({
    "fetch_place_boundary",
    "fetch_osm_features",
    "compute_road_route",
    "georeference_helper",
})

GEE_STAC_RASTER_TOOL_NAMES = frozenset({
    "gee_download_dem",
    "gee_export_image",
    "gee_compute_index",
    "gee_image_collection",
    "gee_image_preview",
    "fetch_stac_earth_data",
    "classify_crops_sentinel1_sar",
    "inspect_raster_layer",
    "style_raster_layer",
    "hillshade_analysis",
    "generate_contours",
})

INDIA_LIVE_TOOL_NAMES = frozenset({
    "load_india_national_gis",
    "load_india_rail_and_metro",
    "fetch_imd_weather_data",
    "load_india_census_data",
    "fetch_air_quality_heatmap",
})

HAZARD_TOOL_NAMES = frozenset({
    "fetch_live_hazard_feed",
})

CARTOGRAPHY_3D_TOOL_NAMES = frozenset({
    "create_map_graticule",
    "visualize_3d_terrain",
    "export_temporal_animation",
    "generate_spatial_report",
    "analyze_map_vision",
})

VERIGEO_MCDM_TOOL_NAMES = frozenset({
    "verigeo_verify_and_repair",
    "verigeo_maup_and_physics_guard",
    "datacube_manage_100_layers",
    "autonomous_mcdm_100plus",
    "autonomous_datalake_crawl",
})

GAS_AGENTIC_TOOL_NAMES = frozenset({
    "gas_discover_agents",
    "gas_describe_agent",
    "gas_execute_task",
    "gas_manage_task",
    "gas_registry_search",
})

DOCUMENT_RAG_TOOL_NAMES = frozenset({
    "read_uploaded_file_or_pdf",
    "xerj_document_intelligence",
    "query_xerj_corpus",
    "manage_agent_memory",
})

GEOSAM_TOOL_NAMES = frozenset({
    "geosam_segment_features",
})

GEORAG_TOOL_NAMES = frozenset({
    "georag_spatial_query",
})

WEBGIS_TOOL_NAMES = frozenset({
    "export_interactive_webgis",
})

CHANGE_DETECTION_TOOL_NAMES = frozenset({
    "detect_raster_change",
})

LIDAR_3D_TOOL_NAMES = frozenset({
    "drone_lidar_lod2_builder",
})

SWARM_GAS_TOOL_NAMES = frozenset({
    "gas_multi_agent_swarm",
})

ASSETOPS_TOOL_NAMES = frozenset({
    "assetops_iot_telemetry",
    "assetops_fmsr_diagnostics",
    "assetops_tsfm_forecast",
    "assetops_work_order_dispatch",
    "geo_assetops_benchmark_eval",
})


def repair_and_parse_json(raw_args: str) -> dict[str, Any]:
    """Robustly parse JSON arguments emitted by diverse AI models."""
    raw = (raw_args or "").strip()
    if not raw or raw in ("{}", '""', "null"):
        return {}

    # 1. Direct standard parse
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # 2. Strip markdown code fences ```json ... ```
    cleaned = raw
    if "```" in cleaned:
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

    # 3. Strip trailing commas before } or ]
    import re
    cleaned_commas = re.sub(r",\s*([\}\]])", r"\1", cleaned)
    try:
        parsed = json.loads(cleaned_commas)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # 4. Extract outer { ... }
    b_start = cleaned.find("{")
    b_end = cleaned.rfind("}")
    if b_start != -1 and b_end > b_start:
        snippet = cleaned[b_start:b_end + 1]
        snippet_commas = re.sub(r",\s*([\}\]])", r"\1", snippet)
        try:
            parsed = json.loads(snippet_commas)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # 5. ast.literal_eval fallback (single-quoted python dicts)
    try:
        import ast
        eval_res = ast.literal_eval(cleaned)
        if isinstance(eval_res, dict):
            return eval_res
    except Exception:
        pass

    return {}


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
        "query_xerj_corpus",
        "gee_download_dem", "gee_export_image", "gee_compute_index",
        "gee_image_collection", "gee_image_preview",
        "load_india_rail_and_metro",
        "fetch_imd_weather_data",
        "load_india_census_data",
        "fetch_air_quality_heatmap",
        "analyze_map_vision",
        "classify_crops_sentinel1_sar",
        "detect_buildings_from_raster",
        "gas_discover_agents",
        "gas_describe_agent",
        "gas_execute_task",
        "gas_manage_task",
        "gas_registry_search",
        "verigeo_verify_and_repair",
        "verigeo_maup_and_physics_guard",
        "datacube_manage_100_layers",
        "autonomous_mcdm_100plus",
        "autonomous_datalake_crawl",
        "xerj_document_intelligence",
        "geosam_segment_features",
        "export_interactive_webgis",
        "detect_raster_change",
        "drone_lidar_lod2_builder",
        "gas_multi_agent_swarm",
        "assetops_iot_telemetry",
        "assetops_fmsr_diagnostics",
        "assetops_tsfm_forecast",
        "assetops_work_order_dispatch",
        "geo_assetops_benchmark_eval",
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
        self._active_user_prompt: str = ""
        self._executed_tools_in_run: set[str] = set()

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

    def _select_active_tool_names(self, prompt: str) -> set[str]:
        p = prompt.lower()
        active = set(CORE_TOOL_NAMES)
        active.update(ACQUISITION_TOOL_NAMES)

        if any(k in p for k in ("gee", "earth engine", "dem", "elevation", "sentinel", "landsat", "satellite", "ndvi", "ndwi", "sar", "crop", "raster", "contour", "hillshade", "stac", "stretch", "terrain")):
            active.update(GEE_STAC_RASTER_TOOL_NAMES)

        if any(k in p for k in ("india", "census", "imd", "weather", "railway", "rail", "metro", "cpcb", "aqi", "air quality", "pm2.5", "pm10", "tehsil", "taluk", "panchayat", "state boundary")):
            active.update(INDIA_LIVE_TOOL_NAMES)

        if any(k in p for k in ("hazard", "disaster", "flood", "earthquake", "fire", "alert", "gdacs", "usgs")):
            active.update(HAZARD_TOOL_NAMES)

        if any(k in p for k in ("mcdm", "suitability", "verigeo", "entropy", "ahp", "topsis", "datacube", "solar", "wind", "criteria", "maup", "datalake", "100")):
            active.update(VERIGEO_MCDM_TOOL_NAMES)

        if any(k in p for k in ("3d", "graticule", "animation", "temporal", "vision", "screenshot", "atlas", "report", "cartography")):
            active.update(CARTOGRAPHY_3D_TOOL_NAMES)

        if any(k in p for k in ("gas", "remote agent", "external agent", "registry", "getcapabilities")):
            active.update(GAS_AGENTIC_TOOL_NAMES)

        if any(k in p for k in ("pdf", "document", "docx", "excel", "csv", "upload", "xerj", "corpus")):
            active.update(DOCUMENT_RAG_TOOL_NAMES)

        if any(k in p for k in ("sam", "segment", "sam 2", "geosam", "extract building", "extract tree")):
            active.update(GEOSAM_TOOL_NAMES)

        if any(k in p for k in ("georag", "spatial query", "sql", "select where", "database query", "filter where")):
            active.update(GEORAG_TOOL_NAMES)

        if any(k in p for k in ("webgis", "web map", "maplibre", "kepler", "cesium", "export html", "browser map")):
            active.update(WEBGIS_TOOL_NAMES)

        if any(k in p for k in ("change detection", "deforestation", "forest loss", "urban sprawl", "burn severity", "wildfire", "difference")):
            active.update(CHANGE_DETECTION_TOOL_NAMES)

        if any(k in p for k in ("lidar", "drone", "lod2", "lod-2", "ndsm", "canopy height", "3d building", "extrusion", "dsm", "dtm")):
            active.update(LIDAR_3D_TOOL_NAMES)

        if any(k in p for k in ("swarm", "gas 2", "multi-agent", "agent team", "consensus", "roster", "agenthive", "metaagent")):
            active.update(SWARM_GAS_TOOL_NAMES)

        if any(k in p for k in (
            "assetops", "assetopsbench", "iot", "sensor", "telemetry", "fmsr", "failure mode",
            "root cause", "tsfm", "time series forecast", "remaining useful life", "rul",
            "work order", "maximo", "maintenance", "dispatch", "crew", "transformer",
            "power grid", "pipeline", "telecom tower", "benchmark", "industry 4.0", "anomaly",
        )):
            active.update(ASSETOPS_TOOL_NAMES)
            active.update(SWARM_GAS_TOOL_NAMES)

        if self._executed_tools_in_run:
            active.update(self._executed_tools_in_run)

        return active

    def _build_tools_schema(self, user_prompt: str = "") -> list[dict[str, Any]]:
        if self._config.execution_mode == "chat_only":
            return []
        active_names = self._select_active_tool_names(user_prompt)
        schemas = []
        for name, spec in self._tools.items():
            if name in active_names:
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                })
        return schemas

    def _get_canvas_context_markdown(self) -> str:
        """Extract structured, clear markdown representation of the live QGIS canvas."""
        try:
            from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer
            proj = QgsProject.instance()
            proj_crs = proj.crs()
            crs_authid = proj_crs.authid() if proj_crs.isValid() else "EPSG:4326"
            crs_units = "degrees (geographic)" if (proj_crs.isValid() and proj_crs.isGeographic()) else "meters (projected)"

            active_lyr = self._iface.activeLayer() if self._iface else None
            active_name = active_lyr.name() if active_lyr else None

            extent_str = ""
            if self._iface and self._iface.mapCanvas():
                ext = self._iface.mapCanvas().extent()
                if ext.isValid():
                    extent_str = f"[{round(ext.xMinimum(), 4)}, {round(ext.yMinimum(), 4)}, {round(ext.xMaximum(), 4)}, {round(ext.yMaximum(), 4)}]"

            root = proj.layerTreeRoot()
            layers_lines = []
            for lyr in proj.mapLayers().values():
                node = root.findLayer(lyr.id()) if root else None
                vis = "visible" if (node is None or node.isVisible()) else "hidden"
                lcrs = lyr.crs().authid() if lyr.crs().isValid() else ""

                if isinstance(lyr, QgsVectorLayer):
                    gtype = lyr.geometryType()
                    gname = {0: "Point", 1: "LineString", 2: "Polygon", 3: "Unknown", 4: "Null"}.get(int(gtype), "Vector")
                    fcount = lyr.featureCount()
                    fnames = [f.name() for f in lyr.fields()][:8]
                    f_str = f" | Fields: [{', '.join(fnames)}]" if fnames else ""
                    layers_lines.append(f"- \"{lyr.name()}\" [Vector: {gname} | {fcount} features | CRS: {lcrs} | {vis}{f_str}]")
                elif isinstance(lyr, QgsRasterLayer):
                    layers_lines.append(f"- \"{lyr.name()}\" [Raster: {lyr.bandCount()} bands | CRS: {lcrs} | {vis}]")
                else:
                    layers_lines.append(f"- \"{lyr.name()}\" [Layer | CRS: {lcrs} | {vis}]")

            md_parts = [
                "### Live QGIS Project Canvas Context:",
                f"- **Project CRS**: `{crs_authid}` ({crs_units})",
                f"- **Active Layer**: {f'`{active_name}`' if active_name else 'None'}",
            ]
            if extent_str:
                md_parts.append(f"- **Canvas View Extent**: {extent_str}")
            if layers_lines:
                md_parts.append(f"- **Available Project Layers ({len(layers_lines)})**:")
                md_parts.extend(layers_lines[:25])
            else:
                md_parts.append("- **Available Project Layers**: *(None - Canvas is currently empty)*")

            return "\n".join(md_parts)
        except Exception as exc:
            return f"### Live QGIS Canvas Context: (unavailable: {exc})"

    def _build_system_prompt(self) -> str:
        canvas_md = self._get_canvas_context_markdown()
        custom = self._config.custom_instructions.strip()
        extra = f"\nUser Preferences:\n{custom}" if custom else ""

        try:
            persisted_mem = _read_persistent_memory()
            if persisted_mem:
                mem_items = [f"{k}={v.get('value')}" for k, v in list(persisted_mem.items())[:5]]
                extra += "\nAgent Memory: " + ", ".join(mem_items)
        except Exception as _mem_err:
            _ = _mem_err

        return (
            "You are AutoGIS, an Autonomous Geospatial AI Agent in QGIS.\n\n"
            f"{canvas_md}\n{extra}\n\n"
            "Execution Rules:\n"
            "1. Inspect Available Project Layers above before writing code. Use exact layer names in quotes.\n"
            "2. CRS Awareness: Always check layer CRS. AutoGIS tools auto-reproject, but for run_processing_algorithm verify CRS alignment first.\n"
            "3. Plans: For multi-step workflows, call update_agent_plan AND execution tools in same turn. Never stop while steps are pending.\n"
            "4. Self-Healing & Verification: If a tool fails with an error, inspect the provided hint and available layers, correct your parameters or code, and retry.\n"
            "5. Safety & Rollback: Checkpoints are automatically recorded before write actions. You can call undo_project_checkpoint if a step fails irreversibly.\n"
            "6. Execute directly: Use tools to load and style layers directly in QGIS; do not ask the user to run scripts manually.\n"
            "7. Target Layer Constraint: When a Target Layer is selected by the user, prioritize and operate strictly on that layer.\n"
            "8. Physical Resolution & Buildings: Sentinel-2 optical resolution is 10m/pixel; individual building footprints (8-15m) cannot be resolved directly from 10m raster pixels. For building footprints, use High-Resolution imagery (<1m drone/aerial) with GeoSAM, OR fetch true surveyed building vector footprints using fetch_osm_features(category='buildings').\n"
            "9. Concise professional responses, no emojis."
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
            target_lyr = layer_mentions[0]
            extra_blocks.append(
                f"### 🎯 Explicit Target Working Layer: `{target_lyr}`\n"
                f"STRICT CONSTRAINT: The user explicitly selected `{target_lyr}`. All geoprocessing, GeoSAM segmentation, "
                f"GeoRAG queries, buffering, and analysis MUST strictly execute on `{target_lyr}`."
            )
            if len(layer_mentions) > 1:
                extra_blocks.append("Additional Context Layers: " + ", ".join(f"`{m}`" for m in layer_mentions[1:]))
        if attachments:
            att_summaries = [summarize_attached_path(p) for p in attachments]
            extra_blocks.append("### Attached User Files / Documents / Folders:\n" + "\n\n".join(att_summaries))
        full_user_prompt = user_text.strip()
        if extra_blocks:
            full_user_prompt += "\n\n" + "\n".join(extra_blocks)

        sys_prompt = self._build_system_prompt()
        with self._lock:
            self._active_run_id = run_id
            self._active_user_prompt = full_user_prompt
            self._executed_tools_in_run.clear()
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
        tools_schema = self._build_tools_schema(self._active_user_prompt)

        self.status_updated.emit(run_id, "Thinking...")

        if not self._timer.isActive():
            self._timer.start()

        worker = threading.Thread(
            target=self._http_worker,
            args=(run_id, provider, api_key, or_key, base_url, api_model, max_tokens, auto_fallback, messages_snapshot, tools_schema),
            daemon=True,
        )
        worker.start()

    # Models that perform slow extended chain-of-thought reasoning — suppress it via OpenRouter param
    _REASONING_MODELS: frozenset[str] = frozenset({
        "deepseek/deepseek-r1",
        "deepseek/deepseek-r1:free",
        "qwq-32b",
        "o1",
        "o3",
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
    })

    def _stream_once(self, run_id: str, api_key: str, base_url: str, model: str,
                     max_tokens: int, messages: list[dict], tools: list[dict]) -> tuple[str, str, list[dict]]:
        is_openrouter = "openrouter.ai" in base_url
        is_anthropic = ("anthropic.com" in base_url) or (not is_openrouter and (model.startswith("claude-") or "anthropic" in model.lower()))
        is_free_model = model.endswith(":free")

        if is_anthropic:
            # Build native Anthropic Messages API request
            clean_m = model.split("/", 1)[1] if "/" in model else model
            alias_map = {
                "claude-3.7-sonnet": "claude-3-7-sonnet-20250219",
                "claude-sonnet-4.5": "claude-3-7-sonnet-20250219",
                "claude-3.5-sonnet": "claude-3-5-sonnet-20241022",
                "claude-3.5-haiku": "claude-3-5-haiku-20241022",
                "claude-haiku-4.5": "claude-3-5-haiku-20241022",
                "claude-3-haiku": "claude-3-haiku-20240307",
            }
            clean_m = alias_map.get(clean_m, clean_m)

            sys_parts = []
            ant_msgs = []
            for m in messages:
                role = m.get("role")
                content = m.get("content", "")
                if role == "system":
                    sys_parts.append(str(content))
                elif role == "tool":
                    ant_msgs.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": m.get("tool_call_id", f"call_{uuid.uuid4().hex[:8]}"),
                            "content": str(content),
                        }],
                    })
                elif role == "assistant" and m.get("tool_calls"):
                    blocks = []
                    if content:
                        blocks.append({"type": "text", "text": str(content)})
                    for tc in m["tool_calls"]:
                        fn = tc.get("function") or {}
                        blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                            "name": fn.get("name", ""),
                            "input": repair_and_parse_json(fn.get("arguments", "{}")),
                        })
                    ant_msgs.append({"role": "assistant", "content": blocks})
                elif role in ("user", "assistant"):
                    ant_msgs.append({"role": role, "content": str(content)})

            ant_tools = []
            for t in tools:
                fn = t.get("function") or {}
                ant_tools.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                })

            payload: dict[str, Any] = {
                "model": clean_m,
                "max_tokens": max(512, min(max_tokens, 4096)),
                "messages": ant_msgs,
                "stream": True,
            }
            if sys_parts:
                payload["system"] = "\n\n".join(sys_parts)
            if ant_tools:
                payload["tools"] = ant_tools

            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/messages",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                    "User-Agent": "AutoGIS-Studio/1.0",
                },
                method="POST",
            )
        else:
            # Standard OpenAI-compatible payload (Gemini, OpenAI, DeepSeek, OpenRouter, Ollama, Xerj)
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                # Cap free model tokens to avoid long slow responses; paid models keep user setting
                "max_tokens": min(max_tokens, 1536) if is_free_model else max_tokens,
                "stream": True,
            }
            if tools:
                payload["tools"] = tools

            # OpenRouter: disable extended chain-of-thought reasoning for ALL free models
            # (reasoning = 60s+ "Reasoning..." freeze with no useful output for GIS tasks)
            if is_openrouter and is_free_model:
                payload["reasoning"] = {"exclude": True}
            # For known reasoning models on paid tier, also disable to keep responses fast
            elif is_openrouter and any(rm in model for rm in self._REASONING_MODELS):
                payload["reasoning"] = {"max_tokens": 300}

            # OpenRouter compression — reduces input token cost and latency
            if is_openrouter:
                payload["transforms"] = ["middle-out"]

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
        last_status_at = time.monotonic()
        first_token_at: float | None = None
        REASONING_TIMEOUT = 45.0   # bail out if reasoning takes >45s with no content

        if hasattr(req, "full_url"):
            _parsed_req_url = urllib.parse.urlparse(req.full_url)
            if _parsed_req_url.scheme not in ("http", "https"):
                raise ValueError(f"Disallowed URL scheme: {_parsed_req_url.scheme}")

        # Shorter timeout for free models — they should respond in <30s or we fall back
        conn_timeout = 55 if is_free_model else 120
        with urllib.request.urlopen(req, timeout=conn_timeout) as resp:  # nosec B310
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

                # --- 1. Anthropic Native Stream Event Handling ---
                chunk_type = chunk.get("type")
                if chunk_type == "content_block_start":
                    cb = chunk.get("content_block") or {}
                    if cb.get("type") == "tool_use":
                        idx = chunk.get("index", len(tc_map))
                        tc_map[idx] = {
                            "id": cb.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                            "name": cb.get("name", ""),
                            "arguments": "",
                        }
                    continue
                elif chunk_type == "content_block_delta":
                    d = chunk.get("delta") or {}
                    if d.get("type") == "text_delta":
                        t = d.get("text", "")
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                            self._post("status", run_id, "")
                        text_acc += t
                        self._post("token", run_id, t)
                    elif d.get("type") == "input_json_delta":
                        idx = chunk.get("index", 0)
                        if idx in tc_map:
                            tc_map[idx]["arguments"] += d.get("partial_json", "")
                    continue
                elif chunk_type in ("message_start", "message_delta", "message_stop", "ping"):
                    continue

                # --- 2. OpenAI / Gemini / DeepSeek / OpenRouter / Ollama Choices Handling ---
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                r_delta = delta.get("reasoning") or delta.get("reasoning_content")
                if r_delta:
                    reasoning_acc += str(r_delta)
                    # Only surface reasoning to UI if it's a deliberate reasoning model
                    if any(rm in model for rm in self._REASONING_MODELS):
                        self._post("reasoning", run_id, str(r_delta))
                    now = time.monotonic()
                    if not text_acc and (now - last_status_at) >= 1.5:
                        last_status_at = now
                        elapsed = int(now - (first_token_at or now))
                        self._post("status", run_id, f"Thinking... ({elapsed}s)")
                    # Abort runaway reasoning early for free models
                    if is_free_model and first_token_at and (time.monotonic() - first_token_at) > REASONING_TIMEOUT:
                        log_warn(f"Model {model} reasoning exceeded {REASONING_TIMEOUT}s — aborting stream")
                        break

                c_delta = delta.get("content")
                if c_delta:
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                        self._post("status", run_id, "")
                    text_acc += str(c_delta)
                    self._post("token", run_id, str(c_delta))

                for tc in (delta.get("tool_calls") or []):
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                        self._post("status", run_id, "")
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
                    log_info(f"Model {model} returned an empty stream; retrying once after 0.3s...")
                    self._post("status", run_id, f"Retrying {model.split('/')[-1]}...")
                    time.sleep(0.3)
                    text_acc, reasoning_acc, tool_calls = self._stream_once(
                        run_id, api_key, base_url, model, max_tokens, messages, tools
                    )
                    if not text_acc.strip() and not tool_calls and auto_fallback and or_key:
                        for fb_model in FALLBACK_CHAIN:
                            if fb_model == model and provider == "openrouter":
                                continue
                            if not fb_model.endswith(":free") and not or_key:
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
                    # For 404, the configured model is dead — try free models first
                    fb_chain = list(FALLBACK_CHAIN)
                    if he.code == 404:
                        free_first = [m for m in fb_chain if m.endswith(":free")]
                        paid = [m for m in fb_chain if not m.endswith(":free")]
                        fb_chain = free_first + paid
                    for fb_model in fb_chain:
                        if fb_model == model and provider == "openrouter":
                            continue
                        try:
                            log_info(f"Model {model} returned {he.code}; auto-falling back to {fb_model}")
                            self._post("status", run_id, f"Auto-switching to {fb_model.split('/')[-1]}...")
                            text_acc, reasoning_acc, tool_calls = self._stream_once(
                                run_id, or_key, DEFAULT_BASE_URL, fb_model, min(max_tokens, 2048), messages, tools
                            )
                            # Dead model (404) — persist the working fallback so user doesn't see this again
                            if he.code == 404:
                                try:
                                    self._config.model = fb_model
                                    log_info(f"AutoGIS: Saved working model {fb_model} (replaced dead {model})")
                                except Exception as _cfg_err:
                                    _ = _cfg_err
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
                    args_dict = repair_and_parse_json(raw_args)
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

        # Automatic Checkpoint before write operations
        if spec is not None and getattr(spec, "risk", "") == "write" and not getattr(tc, "_checkpoint_taken", False):
            try:
                from .checkpoint_manager import ProjectCheckpointManager
                ProjectCheckpointManager.get_instance(self._iface).create_checkpoint(f"Before tool '{cname}'")
                tc["_checkpoint_taken"] = True
            except Exception as _chk_err:
                log_warn(f"AutoGIS Checkpoint error: {_chk_err}")

        t0 = time.monotonic()

        # Execute network-heavy download tools on a background worker thread
        # so the QGIS GUI and live timer never freeze while downloading from Overpass/Nominatim/STAC!
        if spec is not None and cname in self.ASYNC_NETWORK_TOOLS:
            def _bg_worker(r=run_id, c=calls, idx=start_idx, call_id=cid, name=cname, args=cargs, s=spec, start_t=t0) -> None:
                err_flag = False
                try:
                    try:
                        out = s.handler(self._iface, args, run_on_main=self.run_on_main_thread)
                    except TypeError as te:
                        if "run_on_main" in str(te):
                            out = s.handler(self._iface, args)
                        else:
                            raise
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

        with self._lock:
            self._executed_tools_in_run.add(cname)

        if is_err and isinstance(res, dict):
            res["_self_healing_directive"] = (
                "Notice: This tool step failed. Review the error details and live canvas context above, "
                "correct your parameters or PyQGIS code, and call the tool again to self-heal."
            )

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
