<div align="center">

<img src="icons/icon.svg" width="110" height="110" alt="AutoGIS Logo" />

# AutoGIS Studio (`v2.0.0`)

**Autonomous Geospatial AI Agent & Spatial Analysis Studio for QGIS (100% Pure Python / PyQGIS)**

[![Download ZIP for QGIS](https://img.shields.io/badge/⬇_Download_Plugin_ZIP-AutoGIS.zip-0284C7?style=for-the-badge&logo=qgis&logoColor=white)](https://github.com/sutharprin098/AutoGIS/releases/latest/download/AutoGIS.zip)
[![QGIS 3.22 - 3.40+](https://img.shields.io/badge/QGIS-3.22%20--%203.40%2B-589632?style=for-the-badge&logo=qgis&logoColor=white)](https://qgis.org)
[![100% Python](https://img.shields.io/badge/100%25_Python-PyQGIS_%2B_PyQt5-2563EB?style=for-the-badge&logo=python&logoColor=white)](https://github.com/sutharprin098/AutoGIS)
[![License: MIT](https://img.shields.io/badge/License-MIT-0D9488?style=for-the-badge)](LICENSE)

</div>

---

**AutoGIS Studio** is an open-source, clean-room **Autonomous Geospatial AI Agent** built 100% in **Python (PyQGIS + PyQt5)** for **QGIS Desktop**. It connects your choice of AI model (**Google Gemini, OpenAI ChatGPT, Anthropic Claude, DeepSeek, or OpenRouter**) directly to the live QGIS map canvas, Processing toolbox, real-time satellite/OSM spatial APIs, and local documents/PDFs.

---

## 📥 1-Click Download & Direct Install in QGIS (`Install from ZIP`)

You can install **AutoGIS** directly inside QGIS in **under 30 seconds** using the official **`AutoGIS.zip`** package:

### 👉 [**Click Here to Download `AutoGIS.zip` Directly**](https://github.com/sutharprin098/AutoGIS/releases/latest/download/AutoGIS.zip)
*(Or download from the [`releases/AutoGIS.zip`](releases/AutoGIS.zip) folder in this repository)*

### Step-by-Step: Add ZIP Directly in QGIS
1. Download **`AutoGIS.zip`** from the link above to your computer (e.g., `Downloads/AutoGIS.zip`).
2. Open **QGIS Desktop**.
3. In the top menu bar, click **`Plugins`** → **`Manage and Install Plugins...`**
4. In the left sidebar of the Plugin Manager window, click **`Install from ZIP`**.
5. Click the **`...`** (Browse) button, select **`AutoGIS.zip`**, and click **`Install Plugin`**.
6. Once installed, click **`AutoGIS Studio`** in the QGIS toolbar (or press **`Ctrl+Shift+G`**) to open the AI panel!

---

### Alternative Method: Add via QGIS Custom Plugin Repository URL
You can also add AutoGIS as a live repository inside QGIS:
1. Open **QGIS** → **`Plugins`** → **`Manage and Install Plugins...`** → **`Settings`** tab.
2. Under *Plugin Repositories*, click **`Add...`**
3. Enter:
   - **Name:** `AutoGIS Official Repository`
   - **URL:** `https://raw.githubusercontent.com/sutharprin098/AutoGIS/main/plugins.xml`
4. Click **OK**, go to the **All** tab, search **`AutoGIS`**, and click **Install Plugin**.

---

### Alternative Method: Manual Plugin Folder Copy (Developer Mode)
Copy or clone the `AutoGIS` folder into your active QGIS Python plugins directory:
- **Windows:**
  ```text
  %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\AutoGIS
  ```
- **Linux:**
  ```text
  ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/AutoGIS
  ```
- **macOS:**
  ```text
  ~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/AutoGIS
  ```

---

## ⚡ Quick AI Setup (Under 20 Seconds)

By default, **no AI provider or model is pre-selected** so you have 100% control over your keys and privacy:

1. Click the **`⚙ Settings`** button in the top-right header of the **AutoGIS** panel.
2. **Step 1 — Select Provider:** Choose any of the 5 built-in gateways:
   - **Google Gemini (Direct API)**
   - **OpenAI ChatGPT (Direct API)**
   - **Anthropic Claude (Direct API)**
   - **DeepSeek (Direct API)**
   - **OpenRouter (All Models Gateway — Free & Pro)**
3. **Step 2 — API Key:** Paste your API key into the single unified input field.
4. **Step 3 — Select Model:** Pick a preset model from the dropdown or type any custom model ID.
5. Click **`⚡ Test (<2s)`** to verify your connection in under 2 seconds, then click **`Save Settings`**.

---

## 🐍 Complete End-to-End Python Architecture (`100% Pure Python`)

AutoGIS is written **100% in Python** using native **PyQGIS (`qgis.core`, `qgis.gui`, `processing`)**, **PyQt5 (`qgis.PyQt`)**, and Python's standard library (`urllib.request`, `threading`, `zipfile`, `xml.etree`). Zero external compiled binaries are required for the plugin to run!

```text
AutoGIS/
├── __init__.py                 # QGIS entry point: exposes classFactory(iface) -> AutoGISPlugin
├── metadata.txt                # Official QGIS plugin manifest (version, icon, compatibility)
├── plugin.py                   # Plugin lifecycle controller (initGui, toolbar, menu, safe unload)
├── plugins.xml                 # QGIS custom plugin repository descriptor for 1-click updates
├── core/
│   ├── __init__.py
│   ├── config.py               # QSettings persistence, provider presets, fallback chains & logging
│   ├── agent_engine.py         # Autonomous multi-step ReAct loop, background HTTP worker & QTimer bridge
│   ├── gis_tools.py            # 25+ native PyQGIS tools (layers, styling, expressions, processing, PyQGIS exec)
│   ├── live_data_tools.py      # Live geospatial connectors (OSM Overpass, Nominatim, OSRM, STAC COGs, WMS/WFS)
│   └── document_tools.py       # Universal reader & search engine for large PDFs, GeoPDFs, DOCX, XLSX, CSV & folders
├── ui/
│   ├── __init__.py
│   ├── theme.py                # High-DPI vector logo renderer (512x512) & Light/Dark Qt stylesheet engine
│   ├── widgets.py              # Chat cards, Left-Timer LiveStatusBanner, PlanChecklistCard & ToolExecutionCard
│   ├── settings_dialog.py      # Unified 5-provider settings dialog with thread-safe <2s pyqtSignal test
│   └── dock_panel.py           # Compact resizable QGIS dock panel (min-width 220px), chat composer & attachment manager
└── icons/
    ├── icon.svg                # Crisp light-palette vector cartographic emblem
    └── icon.png                # High-DPI 512x512 PNG icon generated from vector renderer
```

### What Each Python Module Does:
| Python File | Role & Responsibilities |
| :--- | :--- |
| [`__init__.py`](__init__.py) | Registers `classFactory(iface)` for QGIS's Python Plugin Loader. |
| [`plugin.py`](plugin.py) | Manages QGIS toolbar buttons, `Plugins → AutoGIS Studio` menu actions, `Ctrl+Shift+G` shortcut, and clean timer/widget shutdown on `unload()`. |
| [`core/config.py`](core/config.py) | Stores user settings safely in `QgsSettings` (`AutoGIS/v2/*`), manages 5 AI provider endpoints, and defines automatic fallback models on HTTP `429`/`503`. |
| [`core/agent_engine.py`](core/agent_engine.py) | Runs LLM network calls on a background Python daemon thread while dispatching every PyQGIS tool call safely on the **QGIS Main GUI Thread** via a `25ms` `QTimer` queue (preventing crashes). |
| [`core/gis_tools.py`](core/gis_tools.py) | Implements 18 native PyQGIS tools: layer inspection, attribute queries, field calculator, single/categorized/graduated/heatmap styling, labeling, Processing toolbox execution, spatial buffers/overlays, and custom `execute_pyqgis`. |
| [`core/live_data_tools.py`](core/live_data_tools.py) | Fetches live spatial data with built-in area-span and timeout guards: **OSM Overpass** (with automatic mirror failover), **Nominatim/Photon** boundaries, **OSRM** road routing, **Microsoft Planetary Computer STAC** (30m DEM, 10m Sentinel-2, 10m LULC via `/vsicurl/`), and saved QGIS XYZ/WMS/WFS/PostGIS connections. |
| [`core/document_tools.py`](core/document_tools.py) | Reads and searches across large **PDFs** (page-range pagination + full-document keyword search), **GeoPDFs**, `.docx`, `.xlsx`, `.csv`, `.geojson`, `.shp`, `.gpkg`, and entire project folders. |
| [`ui/theme.py`](ui/theme.py) | Renders the crisp 512×512 anti-aliased cartographic emblem (`devicePixelRatio = 2.0`) and generates clean Light & Dark Qt Stylesheets (QSS). |
| [`ui/widgets.py`](ui/widgets.py) | Provides `LiveStatusBanner` (with live elapsed timer `00:05` on the **left** side), `PlanChecklistCard`, `ToolExecutionCard`, `AttachmentChipBar`, and auto-resizing `PromptTextEdit`. |
| [`ui/settings_dialog.py`](ui/settings_dialog.py) | Unified 1-page AI configuration dialog for all 5 providers with a fast `<2s` connection test powered by thread-safe `pyqtSignal(bool, str)`. |
| [`ui/dock_panel.py`](ui/dock_panel.py) | Main dockable studio panel (`minimumWidth = 220px`) supporting drag-and-drop file/folder uploads, 1-click quick actions, and live map canvas capture. |

---

## 🛠️ Complete Toolset (25 Autonomous GIS Tools)

### 1. Live Geospatial Data & Satellite Connectors (`core/live_data_tools.py`)
- **`fetch_place_boundary`** — Download exact administrative polygon boundaries for any city, district, state, or country via OpenStreetMap Nominatim / Photon.
- **`fetch_osm_features`** — Download live OpenStreetMap vectors (`buildings`, `roads`, `rivers`, `water`, `railways`, `landuse`, `parks`, `hospitals`, `schools`, `power`, `boundary`, or custom Overpass tags) and style them automatically.
- **`compute_road_route`** — Calculate real driving, walking, or cycling road routes (distance in km & duration in minutes) via OSRM and add the route layer to QGIS.
- **`fetch_stac_earth_data`** — Stream Cloud-Optimized GeoTIFFs (COGs) from Microsoft Planetary Computer STAC API directly into QGIS (`dem` Copernicus 30m DEM, `sentinel2` 10m True-Color imagery, `lulc` 10m Land Cover).
- **`list_saved_qgis_connections`** & **`load_saved_qgis_connection`** — Inspect and load saved QGIS XYZ, WMS/WMTS (e.g., ISRO Bhuvan), WFS, and PostGIS connections.

### 2. Universal Document, Large PDF & Folder Reader (`core/document_tools.py`)
- **`read_uploaded_file_or_pdf`** — Paginate through large PDFs (`start_page` / `end_page`), run instant keyword searches across hundreds of PDF pages (`search_query`), load GeoPDFs directly onto the map canvas, or inspect `.docx`, `.xlsx`, `.csv`, `.geojson`, and entire project directories.

### 3. Native PyQGIS Cartography, Processing & Automation (`core/gis_tools.py`)
- **Project & Layer Inspection:** `get_project_overview`, `list_layers`, `inspect_layer`, `query_features`, `compute_field_stats`, `evaluate_expression`, `select_features`
- **Layer Creation & Editing:** `add_basemap`, `load_dataset`, `create_memory_layer`, `add_features`, `calculate_or_add_field`, `delete_features`, `manage_layer_tree`, `export_layer`, `save_project`
- **Cartography & Symbology:** `style_vector_layer` (`single`, `categorized`, `graduated`, `heatmap`), `configure_labels`, `zoom_map`, `capture_map_canvas`
- **Spatial Processing & Custom Python:** `spatial_buffer`, `spatial_overlay` (`clip`, `intersection`, `difference`, `union`, `dissolve`), `search_processing_algorithms`, `get_algorithm_help`, `run_processing_algorithm`, `execute_pyqgis`

---

## 💬 Example Prompts to Try

- *"Download the administrative boundary of Jaipur, fetch major roads and hospitals inside it, and style hospitals with red markers."*
- *"Calculate the driving road route from India Gate, New Delhi to Qutub Minar, New Delhi and zoom to the route."*
- *"Stream the 30m Copernicus Elevation DEM for Dehradun from STAC and add a topographic basemap."*
- *"Read my attached 200-page Master Plan PDF, search for 'industrial zone' or coordinate tables, and plot those locations as a Point layer in QGIS."*
- *"Create a 500m buffer around all rivers in the project, clip the buildings layer with that buffer to find flood-prone buildings, and style them in red."*

---

## 📄 License

Released under the **[MIT License](LICENSE)** — 100% original, clean-room open-source code with zero third-party plugin copyright restrictions.
