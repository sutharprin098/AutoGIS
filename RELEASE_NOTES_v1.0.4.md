# AutoGIS Studio v1.0.4 🚀

**Autonomous Geospatial AI Agent, Live MCP Server & 58 Spatial Analysis Tools for QGIS Desktop**

Official Documentation & Web Portal: https://autogis.princesite.in/
QGIS Official Plugin Repository: https://plugins.qgis.org/plugins/AutoGIS/

---

### What's New in v1.0.4:
- ⏱️ **Animated Time Series Maps (`export_temporal_animation`):**
  - Renders multi-step temporal map frames across timestamps or vector attributes into an animated **GIF** and a standalone interactive **HTML Time-Slider Player**.
- 🏔️ **3D Terrain Visualization (`visualize_3d_terrain`):**
  - Auto-launches native QGIS 3D Map View and generates an interactive standalone **3D WebGIS terrain viewer** (Three.js) with DEM elevation draping and orbit controls.
- 📐 **Custom Grid / Graticule Generator (`create_map_graticule`):**
  - Automatically calculates and generates high-precision geographic lat/long parallels & meridians with degree formatted labels (`28°30' N`, `77°15' E`).
- 🗺️ **Georeferencer Helper (`georeference_helper`):**
  - Georeferences historical scanned maps and unreferenced raster imagery using Ground Control Points (GCPs) or bounding coordinates into GeoTIFF format.
- 🧠 **Persistent Multi-Step Agent Memory (`manage_agent_memory`):**
  - Saves long-term project memory, user preferences, and spatial findings to `QgsProject` custom properties and local persistent storage across sessions.
- 🎙️ **Voice Input (Speech-to-Text) in Studio Composer:**
  - One-click `Voice` button in the composer toolbar for English and Hindi voice dictation directly into the prompt box.
- 📊 **Executive Spatial Analysis Report Generator (`generate_spatial_report`):**
  - Generates comprehensive, print-ready executive PDF and HTML reports with embedded high-resolution map canvas snapshots, layer inventories, and findings.
- 👁️ **Gemini Vision / Multimodal Map Analyzer (`analyze_map_vision`):**
  - Deep visual inspection of the live QGIS map canvas snapshot using Gemini 2.5 Flash / GPT-4o vision to detect spatial patterns, land cover, and cartographic clarity.
- 🚆 **Indian Railways & Metro Networks (`load_india_rail_and_metro`):**
  - Curated loader for Indian Railways (Broad Gauge 1676mm, major junctions, stations) and Indian Metro networks (Delhi, Mumbai, Bengaluru, Kolkata, Chennai, Hyderabad, etc.).
- 🌦️ **IMD Weather Data (`fetch_imd_weather_data`):**
  - Fetches live & forecast precipitation, temperature, humidity, and wind speed grids and interpolates rainfall/temperature heatmaps across India.
- 👥 **Census India Demographic Data (`load_india_census_data`):**
  - Authoritative State & District demographic layers with choropleth graduated styling for Population, Density, Sex Ratio, and Literacy Rate.
- 🍃 **Air Quality Live Heatmap (`fetch_air_quality_heatmap`):**
  - Live CPCB & OpenAQ monitoring stations with official National Air Quality Index (NAQI) color classification and IDW heatmap surfaces.

---

### Direct Download & Installation:
1. Download **`AutoGIS.zip`** attached to this release.
2. Open **QGIS Desktop** (3.22 - 3.40+).
3. Navigate to **Plugins -> Manage and Install Plugins -> Install from ZIP**.
4. Select `AutoGIS.zip` and click **Install Plugin**.
