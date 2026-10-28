# AutoGIS Studio for QGIS

**AutoGIS Studio** is a 100% open-source, standalone Autonomous Geospatial AI Agent and Spatial Analysis Studio for **QGIS 3.22+**.

---

## ✨ Key Features

- **Multi-Provider AI Connectivity**:
  - Connect via **OpenRouter** (300+ models including Free NVIDIA Nemotron, Gemma, Qwen, Llama) or direct API keys for **Google Gemini**, **OpenAI ChatGPT**, **Anthropic Claude**, and **DeepSeek**.
  - Nothing is pre-selected or hardcoded — choose your own provider, model, and API key.
- **34 Built-In PyQGIS, Live Earth Data & Document Tools**:
  - **Live Place Boundaries**: Geocode and download administrative polygon boundaries worldwide via OpenStreetMap Nominatim & Photon (`fetch_place_boundary`).
  - **Live OpenStreetMap Vectors**: Download buildings, roads, rivers, water bodies, railways, parks, hospitals, schools, and land use via Overpass API (`fetch_osm_features`).
  - **OSRM Road Network Routing**: Compute shortest driving, walking, or cycling routes (`compute_road_route`).
  - **Microsoft Planetary Computer STAC**: Stream Cloud-Optimized GeoTIFFs (`/vsicurl/`) for **Copernicus 30m DEM**, **Sentinel-2 10m Optical Imagery**, and **Esri 10m Land Cover (LULC)** (`fetch_stac_earth_data`).
  - **Universal File, Large PDF & Folder Reader**: Attach or drag-and-drop large PDFs (`.pdf`, GeoPDFs), Word documents (`.docx`), Excel spreadsheets (`.xlsx`), CSVs, scripts, spatial datasets, or entire folders (`read_uploaded_file_or_pdf`).
  - **Full PyQGIS Automation**: Inspect layers, filter/query features, compute field statistics, apply single/categorized/graduated/heatmap symbology, configure labels, run any QGIS Processing algorithm, or execute custom PyQGIS scripts.
- **High-DPI Smooth Light Studio UI**:
  - Vector SVG / 4x supersampled High-DPI icons with zero pixelation.
  - Custom logo support — upload your own studio or organization logo in Settings.

---

## 🚀 Installation

1. Copy the `AutoGIS` folder into your QGIS Python plugins directory:
   - **Windows**: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\AutoGIS`
   - **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/AutoGIS`
   - **macOS**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/AutoGIS`
2. Open QGIS → **Plugins** → **Manage and Install Plugins** → enable **AutoGIS**.
3. Click **⚙ Settings** in the AutoGIS dock panel, enter your API key, and select your preferred model.

---

## 📄 License

Licensed under the **GNU General Public License v2.0 or later (GPL-2.0-or-later)**. See [LICENSE](LICENSE) for full details.
