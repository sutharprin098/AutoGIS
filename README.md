<div align="center">

<img src="icons/icon.svg" width="108" height="108" alt="AutoGIS Logo" />

# AutoGIS Studio (`v1.0.0`)

**Autonomous Geospatial AI Agent & Spatial Analysis Studio for QGIS (100% Pure Python / PyQGIS)**

[![Download ZIP for QGIS](https://img.shields.io/badge/⬇_Download_Plugin_ZIP-AutoGIS.zip_(v1.0.0)-0284C7?style=for-the-badge&logo=qgis&logoColor=white)](https://github.com/sutharprin098/AutoGIS/releases/latest/download/AutoGIS.zip)
[![QGIS 3.22 - 3.40+](https://img.shields.io/badge/QGIS-3.22%20--%203.40%2B-589632?style=for-the-badge&logo=qgis&logoColor=white)](https://qgis.org)
[![100% Python](https://img.shields.io/badge/100%25_Python-PyQGIS_%2B_PyQt5-2563EB?style=for-the-badge&logo=python&logoColor=white)](https://github.com/sutharprin098/AutoGIS)
[![License: MIT](https://img.shields.io/badge/License-MIT-0D9488?style=for-the-badge)](LICENSE)

</div>

---

## 🖼️ AutoGIS Studio Live inside QGIS Desktop

<div align="center">
  <img src="docs/autogis_screenshot.png" alt="AutoGIS Studio v1.0.0 Live in QGIS Desktop analyzing a 37-layer Solar Suitability Project" width="100%" />
  <p><em>AutoGIS Studio v1.0.0 running live inside QGIS Desktop — automatically inspecting a 37-layer Multi-Criteria Solar Suitability project, understanding raster/vector hierarchies, and executing step-by-step spatial workflows.</em></p>
</div>

---

## 🌍 What is AutoGIS Studio?

**AutoGIS Studio (`v1.0.0`)** is a 100% original, open-source **Autonomous Geospatial AI Agent** built natively in **Python (`PyQGIS + PyQt5`)** for **QGIS Desktop**.

It connects your choice of frontier AI models (**Google Gemini, OpenAI ChatGPT, Anthropic Claude, DeepSeek, or OpenRouter**) directly to your live QGIS map canvas, Processing toolbox, real-time satellite/OSM spatial APIs, and local documents/PDFs — capable of handling everything from quick map styling to **massive 30+ layer multi-step spatial modeling pipelines** without freezing or crashing QGIS.

### ✨ Key Highlights of `v1.0.0`
- 🧠 **Smart Large-Task Decomposition (Phase-by-Phase Execution):** Automatically breaks complex, multi-layer GIS workflows into sequential steps (`update_agent_plan`), executing 1–2 tools per turn with non-blocking `35ms` Qt event-loop pacing so QGIS never freezes.
- 🛡️ **Crash-Proof Multi-Thread Architecture:** LLM streaming runs on a background daemon thread while all PyQGIS layer/canvas operations run on the **QGIS Main GUI Thread** via a thread-safe `QTimer` queue and `QgsProcessingContext` invalid-geometry guards (`GeometrySkipInvalid`).
- 🌐 **Zero-Setup Live Spatial Data Connectors:** Download administrative boundaries (**Nominatim/Photon**), live **OpenStreetMap** vectors (**Overpass API** with automatic mirror failover), **OSRM** road routes, and **Microsoft Planetary Computer STAC** Cloud-Optimized GeoTIFFs (`30m Copernicus DEM`, `10m Sentinel-2`, `10m Esri LULC`) directly into QGIS.
- 📄 **Universal Large PDF, GeoPDF & Folder Reader:** Attach 200+ page PDF reports, GeoPDF maps, `.docx`, `.xlsx`, `.csv`, `.geojson`, or entire project folders — with instant page pagination and full-document keyword search.
- ⚡ **Unified 5-Provider Settings with `<2s` Connection Test:** Connect **Gemini**, **ChatGPT**, **Claude**, **DeepSeek**, or **OpenRouter** from a single clean dialog with a thread-safe `<2s` live connection test and automatic rate-limit (`HTTP 429`) model fallback.

---

## 📥 1-Click Download & Direct Install in QGIS (`Install from ZIP`)

You can install **AutoGIS Studio (`v1.0.0`)** directly inside QGIS in **under 30 seconds**:

### 👉 [**Click Here to Download `AutoGIS.zip` (`v1.0.0`) Directly**](https://github.com/sutharprin098/AutoGIS/releases/latest/download/AutoGIS.zip)
*(Also available directly inside the repository at [`releases/AutoGIS.zip`](releases/AutoGIS.zip))*

### Method 1: Install from ZIP in QGIS (Recommended)
1. Download **`AutoGIS.zip`** from the link above to your computer.
2. Open **QGIS Desktop**.
3. In the top menu bar, click **`Plugins`** → **`Manage and Install Plugins...`**
4. In the left sidebar, click **`Install from ZIP`**.
5. Click **`...`** (Browse), select **`AutoGIS.zip`**, and click **`Install Plugin`**.
6. Click **`AutoGIS Studio`** in the QGIS toolbar (or press **`Ctrl+Shift+G`**) to launch the AI studio!

---

### Method 2: Add via QGIS Custom Plugin Repository URL
1. Open **QGIS** → **`Plugins`** → **`Manage and Install Plugins...`** → **`Settings`** tab.
2. Under *Plugin Repositories*, click **`Add...`**
3. Enter:
   - **Name:** `AutoGIS Official Repository`
   - **URL:** `https://raw.githubusercontent.com/sutharprin098/AutoGIS/main/plugins.xml`
4. Click **OK**, switch to the **All** tab, search **`AutoGIS`**, and click **Install Plugin**.

---

### Method 3: Manual Plugin Folder Copy (Developer Mode)
Clone or copy the `AutoGIS` folder directly into your QGIS Python plugins directory:
- **Windows:** `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\AutoGIS`
- **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python\plugins/AutoGIS`
- **macOS:** `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/AutoGIS`

---

## ⚡ Quick AI Setup (Under 20 Seconds)

By default, **no AI provider or model is pre-selected** so you stay in full control of your API keys:

1. Click the **`⚙`** (Settings) button in the top-right header of the **AutoGIS** panel.
2. **Step 1 — Select Provider:** Choose your provider:
   - **Google Gemini (Direct API)**
   - **OpenAI ChatGPT (Direct API)**
   - **Anthropic Claude (Direct API)**
   - **DeepSeek (Direct API)**
   - **OpenRouter (All Models Gateway — Free & Pro)**
3. **Step 2 — API Key:** Paste your API key into the single unified input box.
4. **Step 3 — Select Model:** Choose a model from the dropdown or enter any custom model ID.
5. Click **`⚡ Test (<2s)`** to verify your key in under 2 seconds, then click **`Save Settings`**.

---

## 🐍 Complete End-to-End Python Architecture (`100% Pure Python`)

AutoGIS Studio is engineered **100% in Python** using native **PyQGIS (`qgis.core`, `qgis.gui`, `processing`)**, **PyQt5 (`qgis.PyQt`)**, and the Python standard library.

```text
AutoGIS/
├── __init__.py                 # QGIS entry point: exposes classFactory(iface) -> AutoGISPlugin
├── metadata.txt                # Official QGIS plugin manifest (v1.0.0, QGIS 3.22 - 4.99)
├── plugin.py                   # Plugin lifecycle controller (initGui, toolbar, menu, safe unload)
├── plugins.xml                 # QGIS custom plugin repository feed for 1-click installation
├── docs/
│   └── autogis_screenshot.png  # Live QGIS Desktop screenshot (Solar Suitability 37-layer project)
├── core/
│   ├── __init__.py
│   ├── config.py               # QgsSettings manager, 5 provider endpoints & automatic fallback chains
│   ├── agent_engine.py         # Multi-step ReAct engine, phase decomposition, context compaction & QTimer bridge
│   ├── gis_tools.py            # 18 native PyQGIS tools (vector/raster stats, styling, processing, PyQGIS exec)
│   ├── live_data_tools.py      # Live geospatial connectors (OSM Overpass, Nominatim, OSRM, STAC COGs, WMS/WFS)
│   └── document_tools.py       # Universal reader & search engine for large PDFs, GeoPDFs, DOCX, XLSX, CSV & folders
├── ui/
│   ├── __init__.py
│   ├── theme.py                # High-DPI vector logo renderer (512x512) & Light/Dark Qt stylesheet engine
│   ├── widgets.py              # Chat cards, Left-Timer LiveStatusBanner, PlanChecklistCard & ToolExecutionCard
│   ├── settings_dialog.py      # Unified 5-provider settings dialog with thread-safe <2s pyqtSignal test
│   └── dock_panel.py           # Compact resizable QGIS dock panel (min-width 220px), chat composer & attachments
└── icons/
    ├── icon.svg                # Crisp light-palette vector cartographic emblem
    └── icon.png                # High-DPI 512x512 PNG icon
```

| Python Module | Key Engineering Responsibilities |
| :--- | :--- |
| [`__init__.py`](__init__.py) | Exposes `classFactory(iface)` required by QGIS's Python plugin loader. |
| [`plugin.py`](plugin.py) | Manages QGIS toolbar buttons, `Plugins → AutoGIS Studio` menu actions, `Ctrl+Shift+G` shortcut, and clean timer/engine shutdown on `unload()`. |
| [`core/config.py`](core/config.py) | Persists settings in `QgsSettings`, resolves provider endpoints/keys automatically, and manages `FALLBACK_CHAIN` when free or primary models hit rate limits. |
| [`core/agent_engine.py`](core/agent_engine.py) | Powers up to **30 autonomous steps** per turn with automatic **context compaction** (`_compact_messages_for_llm`), step-by-step phase planning, and non-blocking `35ms` main-thread tool pacing so QGIS never freezes on large projects. |
| [`core/gis_tools.py`](core/gis_tools.py) | Implements 18 native PyQGIS tools including full **Raster Band Statistics** (`min`, `max`, `mean`, `std_dev`), invalid-geometry-safe Processing execution (`GeometrySkipInvalid`), symbology (`single`, `categorized`, `graduated`, `heatmap`), and `execute_pyqgis`. |
| [`core/live_data_tools.py`](core/live_data_tools.py) | Connects to **OSM Overpass** (with multi-mirror failover & area guards), **Nominatim/Photon** boundaries, **OSRM** routing, **Microsoft Planetary Computer STAC** (`/vsicurl/` COG streaming), and saved QGIS servers. |
| [`core/document_tools.py`](core/document_tools.py) | Paginates and searches across large **PDFs**, loads **GeoPDFs** onto the canvas, and parses `.docx`, `.xlsx`, `.csv`, `.geojson`, and entire project directories. |
| [`ui/theme.py`](ui/theme.py) | Renders the `512x512` (`devicePixelRatio = 2.0`) cartographic emblem and generates clean Light & Dark QSS themes. |
| [`ui/widgets.py`](ui/widgets.py) | Implements `LiveStatusBanner` (with live elapsed timer `00:05` on the **left** side), `PlanChecklistCard`, `ToolExecutionCard`, and `AttachmentChipBar`. |
| [`ui/settings_dialog.py`](ui/settings_dialog.py) | Single unified settings dialog for all 5 AI providers with a `<2s` thread-safe `pyqtSignal` connection verifier. |
| [`ui/dock_panel.py`](ui/dock_panel.py) | Ultra-compact resizable dock (`minimumWidth = 220px`) with 1-click quick actions and drag-and-drop file/folder attachments. |

---

## 🛠️ Complete Toolset (25 Autonomous GIS Tools)

| Category | Tools Included |
| :--- | :--- |
| **Live Earth & Spatial Data** | `fetch_place_boundary`, `fetch_osm_features`, `compute_road_route`, `fetch_stac_earth_data` (`dem`, `sentinel2`, `lulc`), `list_saved_qgis_connections`, `load_saved_qgis_connection` |
| **Large PDFs, Docs & Folders** | `read_uploaded_file_or_pdf` (PDF page pagination, full-PDF keyword search, GeoPDF canvas loader, DOCX/XLSX/CSV/folder reader) |
| **Project & Layer Inspection** | `update_agent_plan`, `get_project_overview`, `list_layers`, `inspect_layer` (Vector + Raster Band Stats), `query_features`, `compute_field_stats`, `evaluate_expression`, `select_features` |
| **Layer Creation & Management** | `add_basemap`, `load_dataset`, `create_memory_layer`, `add_features`, `calculate_or_add_field`, `delete_features`, `manage_layer_tree`, `export_layer`, `save_project` |
| **Cartography & Symbology** | `style_vector_layer` (`single`, `categorized`, `graduated`, `heatmap`), `configure_labels`, `zoom_map`, `capture_map_canvas` |
| **Geoprocessing & PyQGIS** | `spatial_buffer`, `spatial_overlay` (`clip`, `intersection`, `difference`, `union`, `dissolve`), `search_processing_algorithms`, `get_algorithm_help`, `run_processing_algorithm`, `execute_pyqgis` |

---

## 📄 License

Released under the **[MIT License](LICENSE)** — 100% original, clean-room open-source code.
