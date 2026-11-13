# AutoGIS Studio — Autonomous Geospatial AI Agent for QGIS

[![Version](https://img.shields.io/badge/version-1.0.6-blue)](https://github.com/sutharprin098/AutoGIS/releases/tag/v1.0.6)
[![QGIS](https://img.shields.io/badge/QGIS-3.22%2B-green)](https://qgis.org)
[![License](https://img.shields.io/badge/license-GPL--3.0-orange)](LICENSE)
[![Downloads](https://img.shields.io/github/downloads/sutharprin098/AutoGIS/total)](https://github.com/sutharprin098/AutoGIS/releases)

**AutoGIS** is an open-source, fully autonomous Geospatial AI Agent, Live MCP & GAS 1.0.0 Server, and Spatial Analysis Studio built into QGIS. Connect any AI model — cloud or offline — to your GIS data and automate complex workflows with 65 built-in tools.

---

## ✨ What AutoGIS Does

You type a goal in plain language. AutoGIS plans, executes, and verifies the entire geospatial workflow autonomously — no scripting required.

```
"Fetch OSM buildings for Jaipur, clip to city boundary, 
 buffer 500m, run kernel density, style as heatmap, 
 export 300 DPI PDF report"
```

AutoGIS does all of that in one shot.

---

## 🤖 AI Providers Supported

| Provider | Models | Key |
|---|---|---|
| **OpenRouter** | 100+ models (Free & Paid) | `sk-or-...` |
| **Google Gemini** | Gemini 2.5 Flash/Pro, 2.0 Flash | Gemini API Key |
| **OpenAI** | GPT-4o, GPT-4o Mini, o3-mini | OpenAI API Key |
| **Anthropic** | Claude Sonnet/Haiku 4.5 | Anthropic Key |
| **DeepSeek** | DeepSeek V3, R1 | DeepSeek Key |
| **Ollama / LM Studio** | Any local model (offline) | No key needed |

> **Free Tier**: Use OpenRouter with a free key — includes Nemotron 3.5 Lightning, Llama 3.3 70B, and more. [Get free key →](https://openrouter.ai)

---

## 🛠️ 65 Autonomous Tools (v1.0.6)

### 🤝 Geospatial Agentic Services (GAS 1.0.0)
| Tool | Description |
|---|---|
| `gas_discover_agents` | Discover published GAS agents via `GetCapabilities` or the GAS Registry |
| `gas_describe_agent` | Inspect `DescribeAgent` capabilities, skills, schemas, and `GetAgentStatus` |
| `gas_execute_task` | Execute tasks on remote/local GAS agents (`sync`, `stream`, `async`) & auto-load artifacts into QGIS |
| `gas_manage_task` | Poll `GetTaskStatus`, fetch `GetTaskResult`, wait, or `CancelTask` |
| `gas_registry_search` | Query distributed GAS Registry servers and multi-institution agents |

### 🌍 Data Acquisition
| Tool | Description |
|---|---|
| `fetch_place_boundary` | Fetch administrative boundaries from OSM Nominatim |
| `fetch_osm_features` | Download OSM vector features (buildings, roads, parks, water…) |
| `fetch_stac_earth_data` | Download Sentinel-2, Landsat, MODIS imagery from STAC |
| `fetch_live_hazard_feed` | Live flood, earthquake, fire alerts via GDACS/USGS |
| `load_india_national_gis` | India national GIS data (states, districts, coastline) |
| `load_india_rail_and_metro` | Indian Railways + Metro network routes & stations |
| `fetch_imd_weather_data` | IMD live weather: rainfall, temperature grids |
| `load_india_census_data` | Census India district/state demographics choropleth |
| `fetch_air_quality_heatmap` | Live PM2.5/PM10/AQI from CPCB & OpenAQ as heatmaps |
| `classify_crops_sentinel1_sar` | Multi-temporal SAR crop classification (Sentinel-1, MDPI 2025) |

### 🛰️ Google Earth Engine (GEE)
| Tool | Description |
|---|---|
| `gee_download_dem` | Download SRTM/ASTER DEM for any area |
| `gee_export_image` | Export any GEE image collection to Drive/local |
| `gee_compute_index` | Compute NDVI, NDWI, EVI, SAVI, NBR and more |
| `gee_image_collection` | Query and filter GEE image collections |
| `gee_image_preview` | Generate quick-look thumbnail previews |

### 🔬 Spatial Analysis
| Tool | Description |
|---|---|
| `spatial_buffer` | Buffer with auto CRS reprojection |
| `spatial_overlay` | Intersect, union, difference, clip |
| `run_processing_algorithm` | Run any QGIS Processing algorithm by ID |
| `search_processing_algorithms` | Discover algorithms by keyword |
| `get_algorithm_help` | Get parameter schema for any algorithm |
| `execute_pyqgis` | Execute arbitrary PyQGIS code safely |
| `compute_road_route` | Road routing via OSRM (car/bike/foot) |
| `query_xerj_corpus` | Semantic search over geospatial knowledge corpus |
| `classify_crops_sentinel1_sar` | Sentinel-1 SAR crop mapping with ATCN/LSTM |

### 🗺️ Visualization & Cartography
| Tool | Description |
|---|---|
| `apply_layer_style` | Apply QGIS symbology styles |
| `create_print_layout` | Auto-generate print layouts (North arrow, scale, legend) |
| `export_map_image` | Export 72–300 DPI PNG/TIFF/PDF maps |
| `create_map_graticule` | Custom lat-lon grid with degree labels |
| `visualize_3d_terrain` | QGIS 3D View with DEM draping, auto-launch |
| `export_temporal_animation` | Animated GIF + HTML from QGIS Temporal Controller |
| `generate_spatial_report` | HTML + PDF spatial analysis report with AI narration |
| `analyze_map_vision` | Gemini Vision: analyze map screenshots / satellite images |

### 📁 Layer & Project Management
| Tool | Description |
|---|---|
| `create_vector_layer` | Create new vector layers (point/line/polygon) |
| `add_features_to_layer` | Add features with attributes |
| `load_vector_file` | Load any vector file (SHP, GPKG, GeoJSON, KML) |
| `load_raster_file` | Load rasters (GeoTIFF, NetCDF, HDF5) |
| `export_layer` | Export layers to SHP, GeoJSON, GPKG, CSV |
| `get_project_overview` | Get current QGIS project state |
| `get_layer_info` | Detailed layer metadata |
| `set_layer_visibility` | Show/hide layers |
| `remove_layer` | Remove layer from project |
| `zoom_to_layer` | Zoom map to any layer extent |
| `zoom_to_coordinate` | Zoom to lat/lon coordinates |
| `set_project_crs` | Set project CRS |
| `save_project` | Save QGIS project |

### 🧰 Raster Processing
| Tool | Description |
|---|---|
| `run_raster_calculator` | Raster algebra expressions |
| `clip_raster_by_mask` | Clip rasters to vector mask |
| `generate_contours` | Generate contour lines from DEM |
| `hillshade_analysis` | Compute hillshade for visualization |

### 🔧 Workflow & Memory
| Tool | Description |
|---|---|
| `update_agent_plan` | Multi-step plan tracker with status |
| `manage_agent_memory` | Persistent agent memory across sessions |
| `georeference_helper` | Auto-georeference scanned/historical maps |

### 🎙️ Voice Input
- Microphone button in the Studio dock — speak your request in English or Hindi, text auto-fills.

---

## 🚀 Installation

### Method 1: QGIS Plugin Manager (Recommended)
1. Open QGIS → **Plugins → Manage and Install Plugins**
2. Go to **Settings** tab → Add custom plugin repository:
   - URL: `https://autogis.princesite.in/plugins.xml`
3. Search for **AutoGIS** → Click **Install**

### Method 2: Manual ZIP Install
1. Download `AutoGIS.zip` from [Releases](https://github.com/sutharprin098/AutoGIS/releases/tag/v1.0.5)
2. QGIS → **Plugins → Manage and Install Plugins → Install from ZIP**
3. Select the downloaded `AutoGIS.zip` → **Install Plugin**

### Method 3: Direct Copy
```bash
# Clone repo directly into QGIS plugins folder
git clone https://github.com/sutharprin098/AutoGIS \
  "C:/Users/YourName/AppData/Roaming/QGIS/QGIS3/profiles/default/python/plugins/AutoGIS"
```
Then restart QGIS and enable the plugin.

---

## ⚡ Quick Start

1. **Install** the plugin (see above)
2. **Enable** it: Plugins → Manage → Check AutoGIS → OK
3. **Open** the AutoGIS panel: Plugins menu → AutoGIS Studio
4. **Configure** API key: Click **Settings** → Enter your OpenRouter key (free)
5. **Select Model**: Choose **⚡ Nemotron 3.5 Lightning (Free)** from dropdown
6. **Type your request** and press **Enter**!

### Recommended Free Setup
```
Provider:  OpenRouter
API Key:   sk-or-v1-xxxxxxxxxx  (from openrouter.ai — free, no credit card)
Model:     ⚡ Nemotron 3.5 Lightning (Free)
```

---

## 🔧 Configuration

### Settings Panel
| Setting | Description |
|---|---|
| **Provider** | AI backend (OpenRouter, Gemini, OpenAI, etc.) |
| **API Key** | Your API key for the selected provider |
| **Model** | AI model to use |
| **Execution Mode** | Autopilot / Ask before write / Chat only |
| **Max Tokens** | Response length (256–16384) |
| **GEE Project** | Google Earth Engine project ID |
| **Custom Instructions** | Persistent instructions for all queries |

### QGIS.ini Location
```
Windows: %APPDATA%\QGIS\QGIS3\profiles\default\QGIS\QGIS3.ini
Linux:   ~/.local/share/QGIS/QGIS3/profiles/default/QGIS/QGIS3.ini
Mac:     ~/Library/Application Support/QGIS/QGIS3/profiles/default/QGIS/QGIS3.ini
```

---

## 🌐 MCP Server (Live Integration)

AutoGIS exposes a **Model Context Protocol (MCP)** server so you can call AutoGIS tools from any MCP-compatible AI client (Claude Desktop, Cursor, Windsurf, etc.):

```json
{
  "mcpServers": {
    "autogis": {
      "command": "python",
      "args": ["-m", "autogis_mcp"],
      "cwd": "/path/to/AutoGIS"
    }
  }
}
```

---

## 🌾 Sentinel-1 SAR Crop Classification (New in v1.0.5)

AutoGIS implements the multi-temporal SAR crop classification methodology from:

> **Manna et al. (2025)** — *Multi-Temporal Sentinel-1 SAR Data for Crop Type Mapping Using Attention-Based Temporal Convolutional Networks.* Remote Sensing, 17(12), 2095. [doi:10.3390/rs17122095](https://www.mdpi.com/2072-4292/17/12/2095)

**Features:**
- VV + VH polarization time-series stack ingestion via GEE
- Radar Vegetation Index (RVI) phenology trajectory analysis
- Attention-TCN / LSTM classification head
- Confusion matrix & accuracy assessment output
- Styled crop-type map with legend auto-loaded in QGIS

**Usage:**
```
"Classify crops in Punjab for Rabi season 2024 using Sentinel-1 SAR"
```

---

## 📡 Indian Datasets (New in v1.0.5)

| Dataset | Source | Coverage |
|---|---|---|
| Railways & Metro | OpenRailwayMap + GTFS | All India broad/metre/narrow gauge |
| IMD Weather | India Met Department | Rainfall, Tmax, Tmin grids |
| Census India | Census 2011/2021 | District/taluka population, literacy |
| Air Quality | CPCB + OpenAQ | Live PM2.5, PM10, O3, NO2, AQI |

---

## 🗺️ Sample Prompts

```bash
# Data Acquisition
"Download all hospitals in Delhi from OSM and add to map"
"Fetch Sentinel-2 NDVI for Rajasthan from last month"
"Show live air quality stations in Mumbai as color-coded dots"

# Analysis
"Buffer all rivers in my project by 200m and find settlements inside"
"Compute slope, aspect, and hillshade for the loaded DEM"
"Find the shortest road route from Jaipur to Ajmer and add as layer"

# Visualization
"Create a print layout with title, north arrow, scale bar, and legend"
"Generate animated GIF of NDVI change 2020-2024"
"Launch 3D terrain view with elevation draped over satellite imagery"

# India-specific
"Load India district boundaries and join census literacy data"
"Fetch IMD rainfall for Gujarat monsoon season and interpolate heatmap"
"Classify crops in Haryana using Sentinel-1 SAR for Kharif 2024"

# Reports
"Generate a full spatial analysis PDF report for my loaded layers"
```

---

## 🏗️ Architecture

```
AutoGIS Studio
├── core/
│   ├── agent_engine.py      # Autonomous AI agent loop (multi-step, tool-use)
│   ├── config.py            # Provider/model configuration manager
│   ├── gis_tools.py         # Core 46 GIS tool implementations
│   ├── extended_gis_tools.py # 13 extended tools (India data, SAR, 3D, etc.)
│   ├── document_tools.py    # File/PDF/folder context ingestion
│   └── mcp_bridge.py        # MCP server bridge
├── ui/
│   ├── dock_panel.py        # Main Studio dock widget
│   ├── history_panel.py     # Conversation history manager
│   └── settings_dialog.py   # Settings UI
├── icons/                   # Plugin icons
├── metadata.txt             # QGIS plugin metadata
└── AutoGIS.zip              # Distributable package
```

---

## 🔄 Auto-Fallback System

If the selected model fails (HTTP 404/429/500), AutoGIS automatically switches to the next working free model — no interruption, no manual action needed.

**Priority order:**
1. ⚡ Nemotron 3.5 Lightning (Free) — fastest, tool-calls verified
2. Nemotron 3 Ultra 550B (Free)
3. Llama 3.3 70B (Free)
4. Cohere Command R+ (Free)
5. Paid models (Gemini, GPT-4o, Claude — only if key configured)

Dead models are automatically detected and replaced in settings.

---

## 🤝 Contributing

```bash
git clone https://github.com/sutharprin098/AutoGIS
cd AutoGIS
pip install pytest
python -m pytest tests/ -v   # Run 23 tests
```

Pull requests welcome! Please open an issue first for major changes.

---

## 📜 License

GNU GPL v3.0 — Free to use, modify, and distribute with attribution.

---

## 👨‍💻 Author

**Prince Suthar**  
📧 sutharprince098@gmail.com  
🌐 [autogis.princesite.in](https://autogis.princesite.in)  
🐛 [Issues](https://github.com/sutharprin098/AutoGIS/issues)

---

<div align="center">
  <b>⭐ Star this repo if AutoGIS helps your GIS work!</b>
</div>
