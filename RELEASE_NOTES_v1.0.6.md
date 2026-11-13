# AutoGIS Studio v1.0.6 — Release Notes

**Release Date:** November 2026  
**Minimum QGIS Version:** 3.22  
**Supports Qt6:** Yes  
**Autonomous Tools:** 65  

---

## 🆕 What's New in v1.0.6

### 🌐 Geospatial Agentic Services (GAS 1.0.0) Integration (5 New Tools — #61 to #65)
Full standard client & server implementation of [Geospatial Agentic Services (GAS 1.0.0)](https://github.com/GIBD2015/geospatial-agentic-services) (`https://www.geospatial-agentic-services.online`):
- `gas_discover_agents` — Query any GAS 1.0.0 server (`GET /gas/v1/capabilities`) with natural-language or domain filtering (`spatial-statistics`, `mobility`, `network`, `environmental`, `social-media`, `qgis-desktop`).
- `gas_describe_agent` — Inspect detailed agent schemas, operations, input/output datasets, parameter schemas, and live runtime health (`GET /gas/v1/agents/{id}` + `/status`).
- `gas_execute_task` — Execute remote or local GAS agent operations in **synchronous (`sync`)** or **NDJSON streaming (`stream`)** modes (`POST /gas/v1/agents/{id}/tasks`).
  - **Automatic QGIS Layer Packaging**: Pass any loaded QGIS vector or raster layer name in `layer_inputs` — AutoGIS automatically exports and base64-encodes it into a GAS `DatasetInput` payload.
  - **Auto-Load Spatial Artifacts**: Automatically downloads returned GeoJSON, GeoPackage, Shapefile, GeoTIFF, CSV, and KML outputs (`data_url` or inline GeoJSON) and loads them directly onto the QGIS map canvas with auto-styling!
- `gas_manage_task` — Poll asynchronous task status, retrieve final results, or cancel running GAS tasks (`status`, `result`, `cancel`).
- `gas_registry_search` — Search and inspect the global GAS Registry (`GET /api/agents`) for public community geospatial agents.

### 🔌 Built-in GAS 1.0.0 Compliant Server on Local Loopback Bridge
- The local AutoGIS HTTP Bridge (`127.0.0.1:8765`) now acts as a full **GAS 1.0.0 Compliant Server** (`/gas/v1/capabilities`, `/gas/v1/agents/autogis-qgis-agent`, `/status`, `/tasks`, `/data/...`), allowing external GAS orchestrators and multi-agent pipelines to discover and invoke all 65 AutoGIS tools inside a live QGIS Desktop session!

### 🛡️ Security & Quality Verification
- **29/29 Automated PyQGIS & Integration Tests Passing** (including full GAS 1.0.0 sync/stream roundtrip and live registry discovery).
- **0 Bandit Security Vulnerabilities** across the entire codebase (`core/`, `ui/`, `plugin.py`, `__init__.py`).

---

## ⬆️ Upgrade Instructions

### In QGIS Desktop:
1. QGIS → Plugins → Manage and Install Plugins → Install from ZIP
2. Select `AutoGIS.zip` (v1.0.6)
3. Click **Install Plugin**
4. All 65 tools are immediately ready to use.

---

## 🔗 Links
- **Website**: https://autogis.princesite.in/
- **GitHub**: https://github.com/sutharprin098/AutoGIS
- **Download**: https://github.com/sutharprin098/AutoGIS/releases/download/v1.0.6/AutoGIS.zip
