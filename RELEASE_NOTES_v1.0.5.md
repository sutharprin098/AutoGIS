# AutoGIS Studio v1.0.5 — Release Notes

**Release Date:** November 2026  
**Minimum QGIS Version:** 3.22  
**Supports Qt6:** Yes  
**Autonomous Tools:** 60  

---

## 🆕 What's New in v1.0.5

### 🏢 Raster Building Footprint Extraction (New Tool #60)
- `detect_buildings_from_raster` — Extracts vector polygon building footprints directly from an active raster layer (drone orthophoto, high-resolution satellite imagery, Google Satellite basemap).
- **Computer vision & edge morphology**: Uses adaptive contrast gradient, roof boundary segmentation, and geometric compactness filtering (25 m² to 5,000 m²).
- **Ground-truth Overpass integration**: Automatically fetches ground-truth building polygons when raster extent is geographic.
- **Auto-styling**: Automatically applies styled amber polygons (`#F59E0B` fill with `#B45309` stroke) with area ($m^2$), perimeter, and confidence metrics in the attribute table.

### 🛡️ Bulletproof PyQGIS Execution Engine
- **Pre-flight AST syntax check**: Code is parsed and validated before execution — syntax errors return exact line number and message without crashing QGIS.
- **Pre-injected safe helpers**:
  - `get_layer("name")` — Case-insensitive safe layer lookup preventing `IndexError: list index out of range`.
  - `all_layers()` — Instant layer dictionary.
  - Pre-injected 20+ QGIS core classes (`QgsRectangle`, `QgsCoordinateReferenceSystem`, `QgsWkbTypes`, `QgsSingleSymbolRenderer`, `QgsMarkerSymbol`, etc.).
  - `qgis_version_int` — Enables API version checks in user scripts.
- **Rich typed error diagnostics**: Returns structured error objects with specific actionable hints for `NameError`, `AttributeError`, and `ImportError`.

### ⚡ Speed & Zero-Freeze Latency
- Fast 2–5s response times on OpenRouter free tier (60s reasoning freeze eliminated).
- Self-healing dead model fallback to `nvidia/nemotron-3.5-lightning:free`.

### 📦 60 Autonomous Spatial Tools
Full suite of 60 tools across Google Earth Engine, Sentinel-1 SAR Crop Classification, India Datasets (Railways, IMD Weather, Census, Air Quality), 3D Terrain, Animated Time Series, and Raster Building Extraction.

---

## ⬆️ Upgrade Instructions

### In QGIS Desktop:
1. QGIS → Plugins → Manage and Install Plugins → Install from ZIP
2. Select `AutoGIS.zip` (v1.0.5)
3. Click **Install Plugin**
4. All 60 tools are immediately ready to use.

---

## 🔗 Links
- **Website**: https://autogis.princesite.in/
- **GitHub**: https://github.com/sutharprin098/AutoGIS
- **Download**: https://github.com/sutharprin098/AutoGIS/releases/download/v1.0.5/AutoGIS.zip
