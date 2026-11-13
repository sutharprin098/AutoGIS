"""Geospatial Agentic Services (GAS) Integration for AutoGIS Studio.

Implements full client & server interoperability with the GIBD Lab GAS 1.0.0 standard:
  Repository: https://github.com/GIBD2015/geospatial-agentic-services
  Public Server: https://www.geospatial-agentic-services.online
  Public Registry: https://www.geospatial-agentic-services.online/registry

Operations supported:
  - GetCapabilities: `/?SERVICE=GAS&VERSION=1.0.0&REQUEST=GetCapabilities`
  - DescribeAgent:   `/?SERVICE=GAS&VERSION=1.0.0&REQUEST=DescribeAgent&agent_id={agent_id}`
  - GetAgentStatus:  `/agents/{agent_id}/status`
  - ExecuteTask:     `POST /agents/{agent_id}/tasks` (modes: sync, async, stream)
  - GetTaskStatus:   `GET /agents/{agent_id}/tasks/{task_id}/status`
  - GetTaskResult:   `GET /agents/{agent_id}/tasks/{task_id}/result`
  - CancelTask:      `POST /agents/{agent_id}/tasks/{task_id}/cancel`
  - GAS Registry:    `/registry/api/agents`, `/registry/api/servers`
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qgis.core import QgsMapLayer, QgsProject, QgsRasterLayer, QgsVectorFileWriter, QgsVectorLayer

from .config import AutoGISConfig, data_dir, log_info, log_warn

DEFAULT_GAS_SERVER_URL = "https://www.geospatial-agentic-services.online"
DEFAULT_GAS_REGISTRY_URL = "https://www.geospatial-agentic-services.online/registry"
USER_AGENT = "AutoGIS-Studio-GAS/1.0 (+https://autogis.princesite.in/)"

# Built-in fallback catalog of all 16 reference GAS 1.0.0 agents from GIBD2015/geospatial-agentic-services
BUILTIN_GAS_AGENTS: list[dict[str, Any]] = [
    {
        "agent_id": "autonmous_gis_orchestrator",
        "name": "Autonomous GIS Orchestrator",
        "description": "Composes multi-agent GIS pipelines from published GAS DescribeAgent URLs and a natural-language goal.",
        "skills": ["multi_agent_workflow_orchestration", "pipeline_composition"],
        "keywords": ["orchestrator", "multi-agent", "pipeline", "composition", "autonomous gis"],
    },
    {
        "agent_id": "geospatial_data_retrieval_agent",
        "name": "Geospatial Data Retrieval Agent",
        "description": "Retrieves authoritative spatial and demographic datasets from OpenStreetMap, US Census (boundaries & ACS demography), USGS Earthquake, OpenTopography DEMs, OpenWeather, EPA AQS, USDA ERS, and CDC PLACES.",
        "skills": ["handbook_guided_geospatial_data_retrieval"],
        "keywords": ["data retrieval", "osm", "census", "usgs", "opentopography", "cdc places", "epa"],
    },
    {
        "agent_id": "geospatial_data_inspection_agent",
        "name": "Geospatial Data Inspection Agent",
        "description": "Inspects vector, raster, and tabular geospatial datasets to report CRS, bounding box, geometry types, schema, missing values, and spatial validity.",
        "skills": ["geospatial_dataset_profiling_and_inspection"],
        "keywords": ["inspection", "metadata", "schema", "crs", "bbox", "profiling", "validation"],
    },
    {
        "agent_id": "geospatial_workflow_planning_agent",
        "name": "Geospatial Workflow Planning Agent",
        "description": "Generates structured, step-by-step spatial analysis workflow DAGs and execution plans from natural-language research questions.",
        "skills": ["geospatial_workflow_decomposition_and_planning"],
        "keywords": ["workflow planning", "dag", "spatial reasoning", "task decomposition"],
    },
    {
        "agent_id": "vector_analysis_agent",
        "name": "Vector Analysis Agent",
        "description": "Performs vector spatial analysis using verified GeoPandas workflows: clipping, spatial/attribute joins, point-in-polygon counts, buffering, intersections, dissolves, area/length/centroid calculation, nearest-distance, and geometry repair.",
        "skills": ["code_driven_vector_spatial_analysis"],
        "keywords": ["vector analysis", "buffer", "overlay", "spatial join", "clip", "dissolve", "geopandas"],
    },
    {
        "agent_id": "raster_agent",
        "name": "Raster Agent",
        "description": "Processes and analyzes raster datasets (GeoTIFF DEMs, imagery, land cover): clipping, reprojecting, resampling, terrain slope/aspect/hillshade, band math, and zonal statistics.",
        "skills": ["raster_processing_and_terrain_analysis"],
        "keywords": ["raster", "geotiff", "dem", "slope", "hillshade", "ndvi", "zonal statistics", "rasterio"],
    },
    {
        "agent_id": "spatial_analysis_agent",
        "name": "Spatial Analysis Agent",
        "description": "Executes integrated multi-step vector and raster spatial analysis workflows, accessibility modeling, and proximity calculations.",
        "skills": ["integrated_spatial_analysis"],
        "keywords": ["spatial analysis", "accessibility", "catchment", "proximity", "suitability"],
    },
    {
        "agent_id": "spatial_statistics_agent",
        "name": "Spatial Statistics Agent",
        "description": "Conducts inferential spatial statistics: Global & Local Moran's I (LISA cluster analysis), Getis-Ord Gi* hotspot analysis, Geographically Weighted Regression (GWR), and spatial autocorrelation.",
        "skills": ["spatial_autocorrelation_and_regression"],
        "keywords": ["spatial statistics", "moran's i", "lisa", "getis-ord", "hotspot", "gwr", "pysal"],
    },
    {
        "agent_id": "exploratory_spatial_data_analysis_agent",
        "name": "Exploratory Spatial Data Analysis Agent",
        "description": "Conducts descriptive and exploratory spatial data analysis (ESDA): attribute distributions, correlation matrices, spatial lag profiling, and diagnostic charts.",
        "skills": ["exploratory_spatial_data_profiling"],
        "keywords": ["esda", "exploratory", "distribution", "correlation", "spatial lag", "profiling"],
    },
    {
        "agent_id": "google_earth_engine_agent",
        "name": "Google Earth Engine Agent",
        "description": "Queries, filters, processes, and exports cloud satellite imagery, spectral indices (NDVI, NDWI, EVI), and climate datasets via Google Earth Engine.",
        "skills": ["cloud_earth_observation_analysis"],
        "keywords": ["google earth engine", "gee", "sentinel", "landsat", "modis", "ndvi", "remote sensing"],
    },
    {
        "agent_id": "usgs_earthquake_agent",
        "name": "USGS Earthquake Agent",
        "description": "Retrieves live and historical global seismic event feeds from USGS, filters by magnitude/depth/radius/timeline, and generates earthquake layers and seismic briefs.",
        "skills": ["seismic_event_retrieval_and_mapping"],
        "keywords": ["usgs", "earthquake", "seismic", "hazard", "magnitude", "epicenter"],
    },
    {
        "agent_id": "spatiotemporal_conflict_event_agent",
        "name": "Spatiotemporal Conflict Event Layer Agent",
        "description": "Extracts and geocodes structured spatiotemporal event layers (CSV, GeoJSON, reports) from unstructured conflict narratives or incident logs.",
        "skills": ["spatiotemporal_event_extraction"],
        "keywords": ["spatiotemporal", "conflict", "events", "incident extraction", "geocoding"],
    },
    {
        "agent_id": "map_projection_agent",
        "name": "Map Projection Agent",
        "description": "Recommends optimal coordinate reference systems (CRS / EPSG) for distortion-minimized area, distance, or conformal mapping and reprojects spatial datasets.",
        "skills": ["crs_selection_and_reprojection"],
        "keywords": ["projection", "crs", "epsg", "utm", "reproject", "datum"],
    },
    {
        "agent_id": "mapping_agent",
        "name": "Mapping Agent",
        "description": "Produces publication-quality thematic choropleth, proportional symbol, and multi-layer cartographic maps (PNG/PDF/HTML).",
        "skills": ["thematic_cartographic_mapping"],
        "keywords": ["mapping", "cartography", "choropleth", "thematic map", "legend", "symbology"],
    },
    {
        "agent_id": "web_mapping_app_agent",
        "name": "Web Mapping App Agent",
        "description": "Builds standalone interactive browser-ready web mapping applications and operational dashboards (Leaflet/MapLibre HTML) with layer controls, filters, and popups.",
        "skills": ["interactive_web_map_application_generation"],
        "keywords": ["web map", "leaflet", "dashboard", "interactive html", "folium", "webgis"],
    },
    {
        "agent_id": "pasda_agent",
        "name": "PASDA Discovery Agent",
        "description": "Searches and retrieves Pennsylvania Spatial Data Access (PASDA) clearinghouse datasets, metadata, and downloadable GIS layers.",
        "skills": ["pasda_catalog_search_and_retrieval"],
        "keywords": ["pasda", "pennsylvania", "clearinghouse", "catalog", "open data"],
    },
]


class GasClientError(RuntimeError):
    """Raised when a GAS service request fails."""


class GasTaskTimeoutError(TimeoutError):
    """Raised when a GAS task does not finish before the timeout."""


def _gas_outputs_dir() -> str:
    folder = os.path.join(data_dir(), "gas_artifacts")
    os.makedirs(folder, exist_ok=True)
    return folder


def _validate_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid HTTP/HTTPS URL: {url!r}")
    return url.strip()


def _http_request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    clean_url = _validate_http_url(url)
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    data_bytes = None
    if payload is not None:
        req_headers["Content-Type"] = "application/json; charset=utf-8"
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(clean_url, data=data_bytes, headers=req_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise GasClientError("GAS response JSON was not an object.")
        return parsed
    except urllib.error.HTTPError as he:
        err_body = ""
        try:
            err_body = he.read().decode("utf-8", errors="replace")
            err_payload = json.loads(err_body)
        except Exception:
            err_payload = err_body or he.reason
        raise GasClientError(f"GAS request failed with HTTP {he.code}: {err_payload}") from he
    except urllib.error.URLError as ue:
        raise GasClientError(f"GAS connection error for {clean_url}: {ue.reason}") from ue


class GasClient:
    """Pure-stdlib Python client for Geospatial Agentic Services (GAS 1.0.0).

    Mirrors the official `gas_client.GasClient` from
    https://github.com/GIBD2015/geospatial-agentic-services
    with zero external dependencies beyond Python's standard library.
    """

    TERMINAL_STATUSES = {"successful", "failed", "canceled", "rejected"}

    def __init__(
        self,
        server_url: str = DEFAULT_GAS_SERVER_URL,
        *,
        default_credentials: Mapping[str, Any] | None = None,
        artifact_delivery: str = "URL",
        timeout: int = 45,
        load_capabilities: bool = False,
    ) -> None:
        self.server_url = (server_url or DEFAULT_GAS_SERVER_URL).strip().rstrip("/")
        self.default_credentials = dict(default_credentials or {})
        self.artifact_delivery = artifact_delivery
        self.timeout = int(timeout)
        self._capabilities: dict[str, Any] | None = None
        self._agent_descriptions: dict[str, dict[str, Any]] = {}

        if load_capabilities:
            self.get_capabilities()

    def _capabilities_url(self) -> str:
        parsed = urllib.parse.urlparse(self.server_url)
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("REQUEST", [""])[0].lower() == "getcapabilities":
            return self.server_url
        params = urllib.parse.urlencode({
            "SERVICE": "GAS",
            "VERSION": "1.0.0",
            "REQUEST": "GetCapabilities",
        })
        return f"{self.server_url}/?{params}"

    def _server_root(self) -> str:
        parsed = urllib.parse.urlparse(self.server_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return self.server_url.rstrip("/")

    def _absolute_url(self, path_or_url: str) -> str:
        val = str(path_or_url or "").strip()
        if val.startswith(("http://", "https://")):
            return val
        return urllib.parse.urljoin(f"{self._server_root()}/", val.lstrip("/"))

    def _agent_base_url(self, agent_id: str) -> str:
        return self._absolute_url(f"/agents/{agent_id}")

    def _absolute_agent_url(self, agent_id: str, endpoint_url: str) -> str:
        ep = str(endpoint_url or "").strip()
        if ep.startswith(("http://", "https://")):
            return ep
        if ep.startswith("/agents/"):
            return self._absolute_url(ep)
        return f"{self._agent_base_url(agent_id).rstrip('/')}/{ep.lstrip('/')}"

    def get_capabilities(self, refresh: bool = False) -> dict[str, Any]:
        """Fetch the GAS GetCapabilities document."""
        if self._capabilities is not None and not refresh:
            return self._capabilities
        self._capabilities = _http_request_json(self._capabilities_url(), timeout=self.timeout)
        self._agent_descriptions.clear()
        return self._capabilities

    def list_agents(self, refresh: bool = False) -> list[str]:
        """Return agent IDs advertised by GetCapabilities."""
        caps = self.get_capabilities(refresh=refresh)
        return [
            str(a.get("agent_id") or a["name"])
            for a in caps.get("agents", [])
            if isinstance(a, dict) and (a.get("agent_id") or a.get("name"))
        ]

    def resolve_agent_id(self, agent_id: str) -> str:
        requested = str(agent_id or "").strip().strip("/")
        advertised = self.list_agents()
        if requested in advertised:
            return requested
        for item in advertised:
            if item.lower() == requested.lower():
                return item
        raise GasClientError(
            f"Unknown agent_id '{agent_id}'. Available agents: {', '.join(advertised) or '(none)'}"
        )

    def _agent_entry(self, agent_id: str) -> dict[str, Any]:
        for entry in self.get_capabilities().get("agents", []):
            if isinstance(entry, dict) and (entry.get("agent_id") == agent_id or entry.get("name") == agent_id):
                return entry
        raise GasClientError(f"Agent '{agent_id}' is not advertised by GetCapabilities.")

    def describe_agent(self, agent_id: str, refresh: bool = False) -> dict[str, Any]:
        """Fetch one DescribeAgent document."""
        resolved_id = self.resolve_agent_id(agent_id)
        if resolved_id in self._agent_descriptions and not refresh:
            return self._agent_descriptions[resolved_id]

        entry = self._agent_entry(resolved_id)
        describe_url = entry.get("DescribeAgent")
        if not isinstance(describe_url, str) or not describe_url:
            params = urllib.parse.urlencode({
                "SERVICE": "GAS",
                "VERSION": "1.0.0",
                "REQUEST": "DescribeAgent",
                "agent_id": resolved_id,
            })
            describe_url = f"{self.server_url}/?{params}"

        desc = _http_request_json(self._absolute_url(describe_url), timeout=self.timeout)
        self._agent_descriptions[resolved_id] = desc
        return desc

    def get_agent_catalog(self, refresh: bool = False, include_descriptions: bool = False) -> list[dict[str, Any]]:
        """Return a catalog of advertised GAS agents."""
        catalog: list[dict[str, Any]] = []
        for entry in self.get_capabilities(refresh=refresh).get("agents", []):
            if not isinstance(entry, dict):
                continue
            aid = entry.get("agent_id") or entry.get("name")
            if not aid:
                continue
            item: dict[str, Any] = {
                "agent_id": str(aid),
                "name": entry.get("name") or str(aid),
                "description": entry.get("description"),
                "DescribeAgent": entry.get("DescribeAgent"),
            }
            if include_descriptions:
                try:
                    desc = self.describe_agent(str(aid))
                    profile = desc.get("profile") if isinstance(desc.get("profile"), dict) else {}
                    item["description"] = item["description"] or profile.get("description")
                    item["skills"] = desc.get("skills", [])
                    item["keywords"] = desc.get("keywords", [])
                except Exception as exc:
                    log_warn(f"Could not fetch DescribeAgent for {aid}: {exc}")
            catalog.append(item)
        return catalog

    def find_agents(self, keyword: str, include_descriptions: bool = False) -> list[dict[str, Any]]:
        needle = str(keyword or "").strip().lower()
        catalog = self.get_agent_catalog(include_descriptions=include_descriptions)
        if not needle:
            return catalog
        return [
            item for item in catalog
            if needle in json.dumps(item, default=str).lower()
        ]

    def get_agent_status(self, agent_id: str) -> dict[str, Any]:
        resolved_id = self.resolve_agent_id(agent_id)
        url = self._absolute_agent_url(resolved_id, "status")
        return _http_request_json(url, timeout=self.timeout)

    def build_execute_task_request(
        self,
        instructions: str,
        *,
        mode: str = "sync",
        input_datasets: Any = None,
        artifact_delivery: str | None = None,
        parameters: dict[str, Any] | None = None,
        credentials: dict[str, Any] | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_mode = str(mode or "sync").strip().lower()
        if clean_mode not in {"sync", "async", "stream"}:
            raise ValueError("mode must be one of 'sync', 'async', or 'stream'.")

        delivery = str(artifact_delivery or self.artifact_delivery or "URL").strip()
        if delivery.lower() not in {"url", "encoded"}:
            raise ValueError("artifact_delivery must be either 'URL' or 'Encoded'.")

        req_params = dict(parameters or {})
        if model:
            req_params.setdefault("model", model)

        req_creds = dict(self.default_credentials)
        if credentials:
            req_creds.update(dict(credentials))

        payload: dict[str, Any] = {
            "task": {
                "instructions": str(instructions or "").strip(),
                "mode": clean_mode,
            },
            "outputs": {
                "artifact_delivery": "Encoded" if delivery.lower() == "encoded" else "URL",
            },
        }
        if input_datasets is not None:
            if isinstance(input_datasets, (str, Mapping)):
                items = [input_datasets]
            else:
                items = list(input_datasets)
            payload["inputs"] = {
                "input_datasets": [dict(x) if isinstance(x, Mapping) else x for x in items]
            }
        if req_params:
            payload["parameters"] = req_params
        if req_creds:
            payload["credentials"] = req_creds
        if metadata:
            payload["metadata"] = dict(metadata)
        return payload

    @staticmethod
    def encode_dataset_file(file_path: str | Path) -> dict[str, str]:
        """Encode a local file as a base64 GAS input dataset object."""
        p = Path(file_path)
        mime, _ = mimetypes.guess_type(p.name)
        if p.suffix.lower() == ".geojson":
            mime = "application/geo+json"
        elif p.suffix.lower() == ".gpkg":
            mime = "application/geopackage+sqlite3"
        elif p.suffix.lower() in (".tif", ".tiff"):
            mime = "image/tiff"
        obj: dict[str, str] = {
            "filename": p.name,
            "encoding": "base64",
            "data": base64.b64encode(p.read_bytes()).decode("ascii"),
        }
        if mime:
            obj["mime_type"] = mime
        return obj

    def execute_task(
        self,
        agent_id: str,
        instructions: str,
        *,
        mode: str = "sync",
        input_datasets: Any = None,
        artifact_delivery: str | None = None,
        parameters: dict[str, Any] | None = None,
        credentials: dict[str, Any] | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> Any:
        resolved_id = self.resolve_agent_id(agent_id)
        clean_mode = str(mode or "sync").strip().lower()
        body = self.build_execute_task_request(
            instructions,
            mode=clean_mode,
            input_datasets=input_datasets,
            artifact_delivery=artifact_delivery,
            parameters=parameters,
            credentials=credentials,
            model=model,
            metadata=metadata,
        )
        url = self._absolute_agent_url(resolved_id, "tasks")
        eff_timeout = float(timeout or self.timeout)

        if clean_mode == "stream":
            return self._execute_stream(url, body, timeout=eff_timeout)
        return _http_request_json(url, method="POST", payload=body, timeout=eff_timeout)

    def _execute_stream(self, url: str, body: dict[str, Any], timeout: float = 300.0) -> dict[str, Any]:
        """Execute a streaming GAS task, collecting progress events and returning the final task_result."""
        clean_url = _validate_http_url(url)
        data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            clean_url,
            data=data_bytes,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/x-ndjson, application/json",
            },
            method="POST",
        )
        events: list[dict[str, Any]] = []
        final_result: dict[str, Any] | None = None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(ev, dict):
                        events.append(ev)
                        if ev.get("event") == "task_result" and isinstance(ev.get("payload"), dict):
                            final_result = ev["payload"]
                        elif "task" in ev and "outputs" in ev:
                            final_result = ev
        except urllib.error.HTTPError as he:
            err_body = ""
            try:
                err_body = he.read().decode("utf-8", errors="replace")
            except Exception as _err:  # nosec B110
                _ = _err
            raise GasClientError(f"GAS stream failed with HTTP {he.code}: {err_body or he.reason}") from he

        if final_result is None:
            return {
                "task": {"status": "failed"},
                "stream_events": events,
                "error": "Stream ended without a final task_result payload.",
            }
        final_result["stream_events_count"] = len(events)
        final_result["stream_events"] = events[-25:]
        return final_result

    def get_task_status(self, agent_id: str, task_id: str, *, timeout: int | None = None) -> dict[str, Any]:
        resolved_id = self.resolve_agent_id(agent_id)
        url = self._absolute_agent_url(resolved_id, f"tasks/{task_id}/status")
        return _http_request_json(url, timeout=float(timeout or self.timeout))

    def get_task_result(self, agent_id: str, task_id: str, *, timeout: int | None = None) -> dict[str, Any]:
        resolved_id = self.resolve_agent_id(agent_id)
        url = self._absolute_agent_url(resolved_id, f"tasks/{task_id}/result")
        return _http_request_json(url, timeout=float(timeout or self.timeout))

    def cancel_task(self, agent_id: str, task_id: str, *, timeout: int | None = None) -> dict[str, Any]:
        resolved_id = self.resolve_agent_id(agent_id)
        url = self._absolute_agent_url(resolved_id, f"tasks/{task_id}/cancel")
        return _http_request_json(url, method="POST", payload={}, timeout=float(timeout or self.timeout))

    def wait_for_task(
        self,
        agent_id: str,
        task_id: str,
        *,
        poll_interval: float = 3.0,
        timeout_seconds: float = 600.0,
    ) -> dict[str, Any]:
        started = time.monotonic()
        while True:
            st = self.get_task_status(agent_id, task_id)
            status_val = str((st.get("task") or {}).get("status") or "").lower()
            if status_val in self.TERMINAL_STATUSES:
                return self.get_task_result(agent_id, task_id)
            if (time.monotonic() - started) > timeout_seconds:
                raise GasTaskTimeoutError(f"Task '{task_id}' did not finish within {timeout_seconds}s.")
            time.sleep(poll_interval)

    @staticmethod
    def get_artifacts(task_result: Mapping[str, Any], *, format: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
        outputs = task_result.get("outputs") if isinstance(task_result.get("outputs"), Mapping) else {}
        artifacts = outputs.get("artifacts") if isinstance(outputs.get("artifacts"), list) else []
        filtered = [dict(a) for a in artifacts if isinstance(a, Mapping)]
        if format:
            exp = format.lower().lstrip(".")
            filtered = [a for a in filtered if str(a.get("format") or "").lower().lstrip(".") == exp]
        if role:
            filtered = [a for a in filtered if a.get("role") == role]
        return filtered


# ============================================================================
# HELPER FUNCTIONS FOR QGIS LAYER EXPORT & ARTIFACT AUTO-LOADING
# ============================================================================

def _resolve_gas_credentials(config: AutoGISConfig, explicit_creds: dict[str, Any] | None = None) -> dict[str, str]:
    """Assemble GAS credentials from explicit args or AutoGISConfig."""
    creds: dict[str, str] = {}
    if config.gibd_api_key:
        creds["GIBD_API_KEY"] = config.gibd_api_key
    if config.gas_api_key:
        creds["OPENAI_API_KEY"] = config.gas_api_key
    elif config.openai_key and not config.openai_key.startswith("sk-or-"):
        creds["OPENAI_API_KEY"] = config.openai_key
    elif config.api_key:
        creds["OPENAI_API_KEY"] = config.api_key
    elif config.gemini_key:
        creds["GEMINI_API_KEY"] = config.gemini_key

    if isinstance(explicit_creds, Mapping):
        for k, v in explicit_creds.items():
            if v:
                creds[str(k)] = str(v)
    return creds


def _export_qgis_layer_to_encoded_dataset(layer: QgsMapLayer) -> dict[str, str] | None:
    """Export a live QGIS vector or raster layer to a base64-encoded GAS input_dataset object."""
    try:
        src = str(layer.source() or "").strip()
        if src and os.path.isfile(src) and os.path.getsize(src) <= 35 * 1024 * 1024:
            return GasClient.encode_dataset_file(src)

        if isinstance(layer, QgsVectorLayer):
            tmp_dir = tempfile.mkdtemp(prefix="autogis_gas_in_")
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in layer.name())[:40] or "layer"
            out_geojson = os.path.join(tmp_dir, f"{safe_name}.geojson")
            QgsVectorFileWriter.writeAsVectorFormat(layer, out_geojson, "UTF-8", layer.crs(), "GeoJSON")
            if os.path.isfile(out_geojson) and os.path.getsize(out_geojson) > 10:
                return GasClient.encode_dataset_file(out_geojson)
    except Exception as exc:
        log_warn(f"Could not encode QGIS layer '{layer.name()}' for GAS: {exc}")
    return None


def _prepare_gas_input_datasets(raw_inputs: Any, run_on_main=None) -> list[Any]:
    """Convert layer names, local file paths, or URLs into valid GAS input_datasets items."""
    if not raw_inputs:
        return []
    if isinstance(raw_inputs, (str, Mapping)):
        items = [raw_inputs]
    elif isinstance(raw_inputs, list):
        items = list(raw_inputs)
    else:
        return []

    prepared: list[Any] = []
    for item in items:
        if isinstance(item, Mapping):
            prepared.append(dict(item))
            continue
        s = str(item or "").strip()
        if not s:
            continue
        if s.startswith(("http://", "https://")):
            prepared.append(s)
            continue
        if os.path.isfile(s):
            prepared.append(GasClient.encode_dataset_file(s))
            continue

        # Otherwise check if it matches a loaded QGIS layer name or ID
        def _find_and_encode(lname=s):
            from .gis_tools import _resolve_layer
            lyr = _resolve_layer(lname)
            if lyr is not None:
                return _export_qgis_layer_to_encoded_dataset(lyr)
            return None

        encoded = run_on_main(_find_and_encode) if callable(run_on_main) else _find_and_encode()
        if encoded is not None:
            prepared.append(encoded)
        else:
            prepared.append(s)
    return prepared


def _download_and_load_gas_artifacts(
    client: GasClient,
    task_result: Mapping[str, Any],
    *,
    iface=None,
    run_on_main=None,
    auto_load_to_qgis: bool = True,
) -> list[dict[str, Any]]:
    """Download artifacts returned by a GAS task and load spatial layers (GeoJSON, GPKG, SHP, GeoTIFF, CSV) into QGIS."""
    artifacts = client.get_artifacts(task_result)
    if not artifacts:
        return []

    out_dir = _gas_outputs_dir()
    processed_artifacts: list[dict[str, Any]] = []

    for idx, art in enumerate(artifacts, 1):
        art_info = dict(art)
        raw_name = str(
            art.get("filename")
            or art.get("original_filename")
            or art.get("name")
            or f"gas_artifact_{idx}"
        ).strip()
        safe_fname = "".join(c if c.isalnum() or c in "._-" else "_" for c in os.path.basename(raw_name))
        if not safe_fname:
            safe_fname = f"gas_artifact_{idx}"

        fmt = str(art.get("format") or "").strip().lower().lstrip(".")
        if "." not in safe_fname and fmt:
            safe_fname = f"{safe_fname}.{fmt}"

        local_path = os.path.join(out_dir, f"{int(time.time())}_{idx}_{safe_fname}")
        downloaded = False

        # 1. Check inline base64 encoded payload
        b64_data = art.get("data") or art.get("content_base64")
        if isinstance(b64_data, str) and b64_data.strip():
            try:
                Path(local_path).write_bytes(base64.b64decode(b64_data))
                downloaded = True
            except Exception as exc:
                log_warn(f"Failed to decode inline base64 GAS artifact '{safe_fname}': {exc}")

        # 2. Download via URL if provided
        art_url = art.get("url")
        if not downloaded and isinstance(art_url, str) and art_url.strip():
            full_url = client._absolute_url(art_url)
            try:
                clean_url = _validate_http_url(full_url)
                req = urllib.request.Request(clean_url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=90) as resp:  # nosec B310
                    Path(local_path).write_bytes(resp.read())
                downloaded = True
                art_info["resolved_url"] = clean_url
            except Exception as exc:
                log_warn(f"Failed to download GAS artifact from {full_url}: {exc}")
                art_info["download_error"] = str(exc)

        if downloaded and os.path.isfile(local_path):
            art_info["local_path"] = local_path
            art_info["size_bytes"] = os.path.getsize(local_path)

            ext = os.path.splitext(local_path)[1].lower()
            layer_label = str(art.get("name") or art.get("label") or os.path.splitext(safe_fname)[0])

            if auto_load_to_qgis and ext in (".geojson", ".json", ".gpkg", ".shp", ".kml", ".gml", ".csv", ".tif", ".tiff"):
                def _load_layer(p=local_path, e=ext, lbl=layer_label):
                    proj = QgsProject.instance()
                    if e in (".tif", ".tiff"):
                        rlyr = QgsRasterLayer(p, lbl, "gdal")
                        if rlyr.isValid():
                            proj.addMapLayer(rlyr)
                            if iface and iface.mapCanvas():
                                iface.mapCanvas().setExtent(rlyr.extent())
                                iface.mapCanvas().refresh()
                            return {"layer_id": rlyr.id(), "layer_name": rlyr.name(), "layer_type": "raster"}
                    else:
                        vlyr = QgsVectorLayer(p, lbl, "ogr")
                        if vlyr.isValid():
                            from .gis_tools import _PROCESSING_LAYER_REFS
                            _PROCESSING_LAYER_REFS.append(vlyr)
                            proj.addMapLayer(vlyr)
                            if iface and iface.mapCanvas():
                                iface.mapCanvas().setExtent(vlyr.extent())
                                iface.mapCanvas().refresh()
                            return {
                                "layer_id": vlyr.id(),
                                "layer_name": vlyr.name(),
                                "layer_type": "vector",
                                "feature_count": vlyr.featureCount(),
                            }
                    return None

                try:
                    loaded_meta = run_on_main(_load_layer) if callable(run_on_main) else _load_layer()
                    if loaded_meta:
                        art_info["qgis_layer"] = loaded_meta
                except Exception as exc:
                    log_warn(f"Could not auto-load GAS artifact '{local_path}' into QGIS: {exc}")

        processed_artifacts.append(art_info)

    return processed_artifacts


# ============================================================================
# AUTOGIS TOOL HANDLERS FOR GAS
# ============================================================================

def tool_gas_discover_agents(iface, args: dict[str, Any], run_on_main=None) -> dict[str, Any]:
    """Discover and search published GAS agents from a GAS server or the GAS Registry."""
    _ = (iface, run_on_main)
    cfg = AutoGISConfig()
    server_url = str(args.get("server_url") or cfg.gas_server_url or DEFAULT_GAS_SERVER_URL).strip().rstrip("/")
    registry_url = str(args.get("registry_url") or cfg.gas_registry_url or DEFAULT_GAS_REGISTRY_URL).strip().rstrip("/")
    keyword = str(args.get("keyword") or args.get("query") or "").strip().lower()
    source = str(args.get("source") or "server").strip().lower()
    include_descriptions = bool(args.get("include_descriptions", False))

    if source == "registry":
        api_url = f"{registry_url}/api/agents"
        try:
            data = _http_request_json(api_url, timeout=20.0)
            agents = data.get("agents") if isinstance(data.get("agents"), list) else []
            if keyword:
                agents = [a for a in agents if keyword in json.dumps(a, default=str).lower()]
            return {
                "status": "ok",
                "source": "gas_registry",
                "registry_url": registry_url,
                "count": len(agents),
                "agents": agents,
            }
        except Exception as exc:
            log_warn(f"GAS Registry query failed ({api_url}): {exc}; falling back to server/builtin catalog.")

    client = GasClient(server_url, timeout=20)
    try:
        caps = client.get_capabilities(refresh=True)
        catalog = client.get_agent_catalog(include_descriptions=include_descriptions)
        # Enrich catalog descriptions from built-in reference if server GetCapabilities omits description
        builtin_map = {b["agent_id"]: b for b in BUILTIN_GAS_AGENTS}
        for item in catalog:
            b = builtin_map.get(item["agent_id"])
            if b and not item.get("description"):
                item["description"] = b["description"]
                item["keywords"] = b.get("keywords", [])
        if keyword:
            catalog = [item for item in catalog if keyword in json.dumps(item, default=str).lower()]
        return {
            "status": "ok",
            "source": "live_gas_server",
            "server_url": server_url,
            "gas_version": caps.get("version", "1.0.0"),
            "title": caps.get("title", "Geospatial Agentic Services"),
            "provider": caps.get("provider"),
            "count": len(catalog),
            "agents": catalog,
        }
    except Exception as exc:
        log_warn(f"Live GAS GetCapabilities failed ({server_url}): {exc}; using built-in GAS 1.0.0 reference catalog.")
        catalog = list(BUILTIN_GAS_AGENTS)
        if keyword:
            catalog = [item for item in catalog if keyword in json.dumps(item, default=str).lower()]
        return {
            "status": "ok",
            "source": "builtin_reference_catalog",
            "server_url": server_url,
            "live_connection_note": str(exc),
            "count": len(catalog),
            "agents": catalog,
        }


def tool_gas_describe_agent(iface, args: dict[str, Any], run_on_main=None) -> dict[str, Any]:
    """Fetch the full DescribeAgent capability document and status for a specific GAS agent."""
    _ = (iface, run_on_main)
    agent_id = str(args.get("agent_id") or "").strip()
    if not agent_id:
        return {"error": "'agent_id' is required (e.g. 'vector_analysis_agent', 'spatial_statistics_agent', 'usgs_earthquake_agent')."}

    cfg = AutoGISConfig()
    server_url = str(args.get("server_url") or cfg.gas_server_url or DEFAULT_GAS_SERVER_URL).strip().rstrip("/")
    include_status = bool(args.get("include_status", True))

    client = GasClient(server_url, timeout=20)
    try:
        desc = client.describe_agent(agent_id, refresh=True)
        out: dict[str, Any] = {
            "status": "ok",
            "source": "live_gas_server",
            "server_url": server_url,
            "agent_id": agent_id,
            "describe_agent": desc,
        }
        if include_status:
            try:
                out["agent_status"] = client.get_agent_status(agent_id)
            except Exception as st_err:
                out["agent_status"] = {"status": "unknown", "note": str(st_err)}
        return out
    except Exception as exc:
        builtin_map = {b["agent_id"]: b for b in BUILTIN_GAS_AGENTS}
        if agent_id in builtin_map:
            b = builtin_map[agent_id]
            return {
                "status": "ok",
                "source": "builtin_reference_catalog",
                "server_url": server_url,
                "agent_id": agent_id,
                "live_connection_note": str(exc),
                "describe_agent": {
                    "profile": {
                        "agent_id": b["agent_id"],
                        "name": b["name"],
                        "description": b["description"],
                        "version": "1.0.0",
                        "base_url": f"{server_url}/agents/{b['agent_id']}",
                    },
                    "keywords": b.get("keywords", []),
                    "skills": [{"skill_id": s, "name": s} for s in b.get("skills", [])],
                    "conformance": {"gas_version": "1.0.0"},
                },
            }
        return {"error": f"Could not describe GAS agent '{agent_id}': {exc}"}


def tool_gas_execute_task(iface, args: dict[str, Any], run_on_main=None) -> dict[str, Any]:
    """Execute a geospatial task on a remote or local GAS agent (sync, stream, or async) and optionally load returned artifacts into QGIS."""
    agent_id = str(args.get("agent_id") or "").strip()
    instructions = str(args.get("instructions") or "").strip()
    if not agent_id:
        return {"error": "'agent_id' is required (e.g. 'usgs_earthquake_agent', 'vector_analysis_agent')."}
    if not instructions:
        return {"error": "'instructions' (natural-language task instructions) is required."}

    cfg = AutoGISConfig()
    server_url = str(args.get("server_url") or cfg.gas_server_url or DEFAULT_GAS_SERVER_URL).strip().rstrip("/")
    mode = str(args.get("mode") or "sync").strip().lower()
    if mode not in {"sync", "async", "stream"}:
        mode = "sync"

    artifact_delivery = str(args.get("artifact_delivery") or "URL").strip()
    parameters = args.get("parameters") if isinstance(args.get("parameters"), dict) else {}
    model = str(args.get("model") or "").strip() or None
    auto_load = bool(args.get("auto_load_to_qgis", True))
    wait_async = bool(args.get("wait_for_completion", False))
    timeout_sec = int(args.get("timeout") or 180)

    creds = _resolve_gas_credentials(cfg, args.get("credentials"))
    input_datasets = _prepare_gas_input_datasets(args.get("input_datasets"), run_on_main=run_on_main)

    client = GasClient(
        server_url,
        default_credentials=creds,
        artifact_delivery=artifact_delivery,
        timeout=timeout_sec,
    )

    try:
        result = client.execute_task(
            agent_id,
            instructions,
            mode=mode,
            input_datasets=input_datasets if input_datasets else None,
            artifact_delivery=artifact_delivery,
            parameters=parameters,
            credentials=creds,
            model=model,
            timeout=timeout_sec,
        )
        if mode == "async" and wait_async and isinstance(result, dict):
            task_id = str((result.get("task") or {}).get("id") or "").strip()
            if task_id:
                result = client.wait_for_task(agent_id, task_id, timeout_seconds=float(timeout_sec))

        processed_artifacts = _download_and_load_gas_artifacts(
            client,
            result if isinstance(result, Mapping) else {},
            iface=iface,
            run_on_main=run_on_main,
            auto_load_to_qgis=auto_load,
        )

        task_meta = (result.get("task") or {}) if isinstance(result, Mapping) else {}
        outputs_meta = (result.get("outputs") or {}) if isinstance(result, Mapping) else {}
        diagnostics = (result.get("diagnostics") or {}) if isinstance(result, Mapping) else {}

        return {
            "status": task_meta.get("status", "completed"),
            "task_id": task_meta.get("id"),
            "agent_id": agent_id,
            "server_url": server_url,
            "mode": mode,
            "summary": outputs_meta.get("summary") or result.get("message") or "",
            "artifacts_count": len(processed_artifacts),
            "artifacts": processed_artifacts,
            "diagnostics": diagnostics,
            "raw_response": result,
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "agent_id": agent_id,
            "server_url": server_url,
            "mode": mode,
        }


def tool_gas_manage_task(iface, args: dict[str, Any], run_on_main=None) -> dict[str, Any]:
    """Check task status, retrieve final result, wait for completion, or cancel an asynchronous GAS task."""
    var_action = str(args.get("action") or "status").strip().lower()
    agent_id = str(args.get("agent_id") or "").strip()
    task_id = str(args.get("task_id") or "").strip()
    if not agent_id or not task_id:
        return {"error": "Both 'agent_id' and 'task_id' are required."}

    cfg = AutoGISConfig()
    server_url = str(args.get("server_url") or cfg.gas_server_url or DEFAULT_GAS_SERVER_URL).strip().rstrip("/")
    auto_load = bool(args.get("auto_load_to_qgis", True))
    timeout_sec = int(args.get("timeout") or 120)

    client = GasClient(server_url, timeout=timeout_sec)
    try:
        if var_action == "status":
            res = client.get_task_status(agent_id, task_id, timeout=timeout_sec)
            return {"status": "ok", "action": "status", "agent_id": agent_id, "task_id": task_id, "task_status": res}
        if var_action == "cancel":
            res = client.cancel_task(agent_id, task_id, timeout=timeout_sec)
            return {"status": "ok", "action": "cancel", "agent_id": agent_id, "task_id": task_id, "result": res}
        if var_action == "wait":
            res = client.wait_for_task(agent_id, task_id, timeout_seconds=float(timeout_sec))
        elif var_action == "result":
            res = client.get_task_result(agent_id, task_id, timeout=timeout_sec)
        else:
            return {"error": f"Unknown action '{var_action}'. Valid actions: 'status', 'result', 'wait', 'cancel'."}

        processed_artifacts = _download_and_load_gas_artifacts(
            client,
            res if isinstance(res, Mapping) else {},
            iface=iface,
            run_on_main=run_on_main,
            auto_load_to_qgis=auto_load,
        )
        return {
            "status": "ok",
            "action": var_action,
            "agent_id": agent_id,
            "task_id": task_id,
            "task_status": (res.get("task") or {}).get("status"),
            "summary": (res.get("outputs") or {}).get("summary", ""),
            "artifacts_count": len(processed_artifacts),
            "artifacts": processed_artifacts,
            "raw_response": res,
        }
    except Exception as exc:
        return {"error": str(exc), "action": var_action, "agent_id": agent_id, "task_id": task_id}


def tool_gas_registry_search(iface, args: dict[str, Any], run_on_main=None) -> dict[str, Any]:
    """Query the distributed GAS Registry for registered servers, agents, or specific agent details."""
    _ = (iface, run_on_main)
    cfg = AutoGISConfig()
    registry_url = str(args.get("registry_url") or cfg.gas_registry_url or DEFAULT_GAS_REGISTRY_URL).strip().rstrip("/")
    action = str(args.get("action") or "list_agents").strip().lower()
    keyword = str(args.get("keyword") or args.get("query") or "").strip().lower()
    server_filter = str(args.get("server_url") or "").strip()
    registry_id = str(args.get("registry_id") or "").strip()

    try:
        if action == "list_servers":
            data = _http_request_json(f"{registry_url}/api/servers", timeout=20.0)
            servers = data.get("servers") if isinstance(data.get("servers"), list) else []
            return {
                "status": "ok",
                "action": "list_servers",
                "registry_url": registry_url,
                "count": len(servers),
                "servers": servers,
            }

        if action == "agent_detail":
            if not registry_id:
                return {"error": "'registry_id' is required for action='agent_detail' (e.g. 'vector_analysis_agent@www.geospatial-agentic-services.online')."}
            encoded_id = urllib.parse.quote(registry_id, safe="")
            data = _http_request_json(f"{registry_url}/api/agents/{encoded_id}", timeout=20.0)
            return {
                "status": "ok",
                "action": "agent_detail",
                "registry_url": registry_url,
                "registry_id": registry_id,
                "detail": data,
            }

        # Default: list_agents
        url = f"{registry_url}/api/agents"
        if server_filter:
            url += "?" + urllib.parse.urlencode({"server": server_filter})
        data = _http_request_json(url, timeout=20.0)
        agents = data.get("agents") if isinstance(data.get("agents"), list) else []
        if keyword:
            agents = [a for a in agents if keyword in json.dumps(a, default=str).lower()]
        return {
            "status": "ok",
            "action": "list_agents",
            "registry_url": registry_url,
            "count": len(agents),
            "agents": agents,
        }
    except Exception as exc:
        log_warn(f"GAS Registry API warning ({registry_url}): {exc}")
        fallback_agents = list(BUILTIN_GAS_AGENTS)
        if keyword:
            fallback_agents = [a for a in fallback_agents if keyword in json.dumps(a, default=str).lower()]
        return {
            "status": "ok",
            "source": "builtin_fallback",
            "registry_url": registry_url,
            "live_connection_note": str(exc),
            "count": len(fallback_agents),
            "agents": fallback_agents,
        }
