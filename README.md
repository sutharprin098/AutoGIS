<div align="center">

<img src="icons/icon.svg" width="108" height="108" alt="AutoGIS Logo" />

# AutoGIS Studio (`v1.1.0`)

**Autonomous Geospatial AI Agent, Live MCP Server & 39 Spatial Analysis Tools for QGIS**

[![Official QGIS Plugin Repo](https://img.shields.io/badge/QGIS_Plugin_Repo-AutoGIS-589632?style=for-the-badge&logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/AutoGIS/)
[![Download ZIP for QGIS](https://img.shields.io/badge/Download_Plugin_ZIP-AutoGIS.zip_(v1.1.0)-0284C7?style=for-the-badge&logo=qgis&logoColor=white)](https://github.com/sutharprin098/AutoGIS/releases/download/v1.1.0/AutoGIS.zip)
[![QGIS 3.22 - 3.40+](https://img.shields.io/badge/QGIS-3.22%20--%203.40%2B-589632?style=for-the-badge&logo=qgis&logoColor=white)](https://qgis.org)
[![Google Earth Engine](https://img.shields.io/badge/Google_Earth_Engine-Integrated-10B981?style=for-the-badge&logo=googleearthengine&logoColor=white)](https://earthengine.google.com)
[![XERJ Corpus Hub](https://hub.xerj.org/contributors/sutharprin098/badge.svg)](https://hub.xerj.org/contributors/sutharprin098)
[![License: MIT](https://img.shields.io/badge/License-MIT-0D9488?style=for-the-badge)](LICENSE)

</div>

---

## AutoGIS Studio Live inside QGIS Desktop

<div align="center">
  <img src="docs/autogis_screenshot.png" alt="AutoGIS Studio v1.1.0 Live in QGIS Desktop" width="100%" />
  <p><em>AutoGIS Studio v1.1.0 running live inside QGIS Desktop — integrating Google Earth Engine satellite imagery, OpenStreetMap vectors, Live MCP Server, Offline Local AI (Ollama), and 39 spatial analysis tools with non-blocking execution.</em></p>
</div>

---

## What's New in `v1.1.0` 🚀

- 🔌 **Built-in Live Loopback MCP Bridge (`127.0.0.1:8765`):**
  - Exposes all 39 QGIS tools via `/status`, `/tools`, and `/call` (`/mcp`) with thread-safe Qt main-thread dispatch so external AI agents (Claude Code, Cursor, Antigravity, XERJ) can inspect and control live QGIS sessions directly.
- 🖥️ **100% Offline Local AI Support (Ollama & LM Studio):**
  - Zero API key required! Run `qwen2.5-coder:14b`, `llama3.3`, `deepseek-r1:14b`, or `gemma3:12b` locally on `http://127.0.0.1:11434/v1` with full tool-calling support.
- 📊 **Advanced Raster Analytics & Scientific Styling:**
  - `inspect_raster_layer`: Instant raster band statistics (`min`, `max`, `mean`, `std_dev`), pixel resolution, CRS, and NoData inspection.
  - `style_raster_layer`: Apply scientific singleband pseudocolor palettes (`viridis`, `rdylgn`, `terrain`, `spectral`, `reds`, `blues`, `greens`, `magma`) with auto or custom min/max stretch.
  - `compute_zonal_statistics`: Calculate polygon-over-raster zonal statistics (`count`, `sum`, `mean`, `stdev`, `min`, `max`) via `native:zonalstatisticsfb`.
- 🗺️ **300 DPI Publication Cartography & 3D Interactive WebGIS:**
  - `export_publication_map`: Automatically builds an A4 landscape `QgsPrintLayout` complete with Map Frame, Title, Subtitle, North Arrow, Dynamic Legend, Metric Scale Bar, and CRS/DPI metadata footer, exporting both **300 DPI PNG** and **PDF**.
  - `export_interactive_webmap`: Exports visible QGIS vector layers (auto-reprojected to `EPSG:4326`) into a standalone 3D **MapLibre GL JS** `.html` web map with click popups and layer switcher.
- 🌋 **Real-Time Global Hazard Feeds & India National GIS Basemaps:**
  - `fetch_live_hazard_feed`: Live USGS Earthquake feeds (`24h`, `7d`, `30d`) and **NASA EONET** active natural events (wildfires, floods, storms, volcanoes) with spatial bounding-box filtering.
  - `load_india_national_gis`: 1-call loader for **ISRO Bhuvan LULC WMS**, **ESA WorldCover 10m**, **Copernicus GLO-30 Hillshade**, and **Esri World Hydro Reference**.
- 🌍 **Deep Google Earth Engine (GEE) & Tiled OSM Integration:**
  - `gee_download_dem`, `gee_compute_index` (`NDVI`, `NDWI`, `NBR`), `gee_export_image`, `gee_image_collection`, `gee_image_preview`, plus auto-tiled polite Overpass OSM downloads (`fetch_osm_layers`).
- 🛡️ **100% Bandit Security Clean:**
  - Zero High/Medium/Low Bandit findings across all 7,500+ lines of plugin code (`plugins.qgis.org` verified).

---

## 1-Click Download & Direct Install in QGIS (`Install from ZIP`)

You can install **AutoGIS Studio (`v1.1.0`)** directly inside QGIS in **under 30 seconds**:

### [Click Here to Download `AutoGIS.zip` (`v1.1.0`) Directly from GitHub Releases](https://github.com/sutharprin098/AutoGIS/releases/download/v1.1.0/AutoGIS.zip)
*(Official Documentation & Web Portal: [https://autogis.princesite.in/](https://autogis.princesite.in/) | Contact: [sutharprince098@gmail.com](mailto:sutharprince098@gmail.com))*

### Method 1: Install from ZIP in QGIS (Recommended)
1. Download **`AutoGIS.zip`** from the link above to your computer.
2. Open **QGIS Desktop** (version `3.22` or newer).
3. In the top menu, navigate to: **`Plugins` -> `Manage and Install Plugins...`**
4. In the left sidebar, click on **`Install from ZIP`**.
5. Click the `...` button next to **ZIP file**, select the downloaded `AutoGIS.zip`, and click **`Install Plugin`**.
6. AutoGIS will appear as a dock panel on your right sidebar, ready for action!

---

## Quick Setup (Under 1 Minute)

1. Open the **AutoGIS** panel on the right sidebar in QGIS.
2. Click **Settings** in the header.
3. Choose your preferred AI provider:
   - **Google Gemini** (Gemini 2.5 Flash / Pro)
   - **OpenAI** (GPT-4o, GPT-4o-mini)
   - **Anthropic** (Claude 3.5 Sonnet)
   - **DeepSeek** (DeepSeek-V3, R1)
   - **OpenRouter** (Any open-weight or frontier model)
4. Paste your API key, click **Test** (<2s connection check), and click **Save**.
5. *(Optional GEE)*: In the Google Earth Engine tab, enter your Cloud Project ID to unlock 5 GEE tools!

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

Developed with ❤️ by **Prince Suthar** ([@sutharprin098](https://github.com/sutharprin098))
