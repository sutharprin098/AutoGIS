<div align="center">

<img src="icons/icon.svg" width="108" height="108" alt="AutoGIS Logo" />

# AutoGIS Studio (`v1.0.4`)

**Autonomous Geospatial AI Agent with Google Earth Engine & 39 Spatial Analysis Tools for QGIS**

[![Official QGIS Plugin Repo](https://img.shields.io/badge/QGIS_Plugin_Repo-AutoGIS-589632?style=for-the-badge&logo=qgis&logoColor=white)](https://plugins.qgis.org/plugins/AutoGIS/)
[![Download ZIP for QGIS](https://img.shields.io/badge/Download_Plugin_ZIP-AutoGIS.zip_(v1.0.4)-0284C7?style=for-the-badge&logo=qgis&logoColor=white)](https://github.com/sutharprin098/AutoGIS/releases/download/v1.0.4/AutoGIS.zip)
[![QGIS 3.22 - 3.40+](https://img.shields.io/badge/QGIS-3.22%20--%203.40%2B-589632?style=for-the-badge&logo=qgis&logoColor=white)](https://qgis.org)
[![Google Earth Engine](https://img.shields.io/badge/Google_Earth_Engine-Integrated-10B981?style=for-the-badge&logo=googleearthengine&logoColor=white)](https://earthengine.google.com)
[![XERJ Corpus Hub](https://img.shields.io/badge/XERJ_Corpus_Hub-Contributor-6366F1?style=for-the-badge)](https://hub.xerj.org/contributors/sutharprin098)
[![License: MIT](https://img.shields.io/badge/License-MIT-0D9488?style=for-the-badge)](LICENSE)

</div>

---

## AutoGIS Studio Live inside QGIS Desktop

<div align="center">
  <img src="docs/autogis_screenshot.png" alt="AutoGIS Studio v1.0.3 Live in QGIS Desktop" width="100%" />
  <p><em>AutoGIS Studio v1.0.3 running live inside QGIS Desktop — integrating Google Earth Engine satellite imagery, OpenStreetMap vectors, and 39 spatial analysis tools with non-blocking execution.</em></p>
</div>

---

## What's New in `v1.0.3` 🚀

- 🌍 **Deep Google Earth Engine (GEE) Integration:**
  - `gee_download_dem`: Download Digital Elevation Models (SRTM or Copernicus 30m) directly into QGIS as GeoTIFFs.
  - `gee_compute_index`: Autonomously calculate cloud-free **NDVI**, **NDWI**, or **NBR** rasters on GEE servers and stream them to your map canvas.
  - `gee_export_image`: Export multispectral Sentinel-2 (B4/B3/B2, NIR) and Landsat scenes with automated cloud masking.
  - `gee_image_collection`: Query GEE image collections with date/region/cloud filters.
  - `gee_image_preview`: Generate instant 1024px web thumbnail preview URLs.
- ⚡ **Expanded Tool Catalog (39 Autonomous Tools):**
  - Expanded from 25 to **39 tools** covering Earth Engine, vector editing (`calculate_or_add_field`, `delete_features`), layer tree management, scratch memory layers, raster styling, and project persistence.
- 🧠 **Universal AI Geospatial Agent:**
  - Generalized agent engine with zero hardcoded workflow constraints — handles any custom spatial workflow (NDVI, DEM, solar suitability, flood modeling, GLOF, landslide analysis, OSM networks).
- 🛡️ **Bandit & Security Hardened:**
  - Strict URL scheme validation (`http://` / `https://` only), AST-safe exception handling, and full QGIS official repository security compliance.

---

## 1-Click Download & Direct Install in QGIS (`Install from ZIP`)

You can install **AutoGIS Studio (`v1.0.3`)** directly inside QGIS in **under 30 seconds**:

### [Click Here to Download `AutoGIS.zip` (`v1.0.3`) Directly from GitHub Releases](https://github.com/sutharprin098/AutoGIS/releases/download/v1.0.3/AutoGIS.zip)
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
