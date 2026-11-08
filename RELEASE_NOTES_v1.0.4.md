# AutoGIS Studio v1.0.4 — Release Notes

**Release Date:** November 2026  
**Minimum QGIS Version:** 3.22  
**Supports Qt6:** Yes  

---

## 🆕 What's New in v1.0.4

### ⚡ Speed & Reliability Fix
- **Dead model auto-detection**: If the configured model returns HTTP 404 (e.g., deprecated DeepSeek V3 Free), AutoGIS now instantly switches to the first working free model and **saves it permanently** — so you never see the 49-second hang again
- **Faster retry**: Reduced empty-stream retry delay from 1.2s → 0.3s
- **Reordered FALLBACK_CHAIN**: Free working models first (Nemotron 3.5 Lightning → Nemotron 3 Ultra → Llama 3.3), so fallback resolves in <3s
- **Removed dead model** `deepseek/deepseek-chat-v3-0324:free` (HTTP 404) from all dropdowns and defaults
- **New recommended default**: ⚡ Nemotron 3.5 Lightning (Free) — verified tool-calling, ~2s response

### 🛰️ Sentinel-1 SAR Crop Classifier (New Tool)
- `classify_crops_sentinel1_sar` — Multi-temporal SAR crop mapping based on MDPI Remote Sensing 17(12), 2095
- VV+VH polarization time-series stack via Google Earth Engine
- Radar Vegetation Index (RVI) phenology trajectories
- Attention-TCN / LSTM classification head for crop type discrimination
- Outputs: styled crop-type raster + accuracy metrics loaded in QGIS

### 🗺️ Animated Time Series Maps
- `export_temporal_animation` — Export GIF/MP4/HTML from QGIS Temporal Controller
- Auto-frame generation, configurable FPS, bbox control

### 🏔️ 3D Terrain Visualization
- `visualize_3d_terrain` — Auto-launch QGIS 3D View with DEM draping
- Vertical exaggeration, camera angle, WebGIS export

### 📐 Custom Graticule Grid
- `create_map_graticule` — Generate lat/lon grids at any interval with formatted labels (28°30′N, 77°15′E)

### 🗺️ Georeferencer Helper
- `georeference_helper` — Auto-georeference historical/scanned maps using GCPs or bounding box

### 🧠 Persistent Agent Memory
- `manage_agent_memory` — Multi-step agent memory synced across QGIS sessions via QgsProject custom properties

### 🎙️ Voice Input
- Microphone button in Studio dock for speech-to-text (English + Hindi)

### 📊 Spatial Report Generator
- `generate_spatial_report` — AI-narrated HTML + print-ready PDF with layer stats, maps, analysis summary

### 👁️ Gemini Vision
- `analyze_map_vision` — Send a map screenshot/satellite image to Gemini Vision; get AI description

### 🇮🇳 Indian Datasets (3 New Tools)
- `load_india_rail_and_metro` — All India Railways + Metro network routes, styled line layers
- `fetch_imd_weather_data` — IMD rainfall/temperature grids, live & forecast
- `load_india_census_data` — Census India district/taluka demographics with auto choropleth
- `fetch_air_quality_heatmap` — Live CPCB/OpenAQ PM2.5/PM10/AQI as station heatmaps

---

## 📦 Full Tool Count: 59 Autonomous Tools

| Category | Count |
|---|---|
| Data Acquisition & India Datasets | 10 |
| Google Earth Engine | 5 |
| Spatial Analysis & Processing | 8 |
| Visualization & Cartography | 8 |
| Raster Processing | 4 |
| Layer & Project Management | 13 |
| Workflow, Memory & Voice | 4 |
| SAR / Remote Sensing AI | 1 |
| **Total** | **59** |

---

## 🐛 Bug Fixes
- Fixed `gemini_key()` TypeError in vision tool (called as function instead of property)
- Fixed `QgsVectorLayer()` mock signature in test suite
- Fixed CRS authid lambda in conftest
- Fixed model selector showing dead `DeepSeek V3 (Free)` option
- Removed `deepseek/deepseek-chat-v3-0324:free` (HTTP 404 — model deleted by provider)

---

## ⬆️ Upgrade Instructions

### From v1.0.3 or earlier:
1. QGIS → Plugins → Manage → Installed → AutoGIS → **Uninstall**
2. Restart QGIS
3. Plugins → Install from ZIP → Select `AutoGIS.zip`
4. Enable plugin, open Settings, re-enter your API key
5. Select **⚡ Nemotron 3.5 Lightning (Free)** as default model

---

## 🔗 Links
- **GitHub**: https://github.com/sutharprin098/AutoGIS
- **Homepage**: https://autogis.princesite.in
- **Issues**: https://github.com/sutharprin098/AutoGIS/issues
- **MDPI SAR Paper**: https://www.mdpi.com/2072-4292/17/12/2095
