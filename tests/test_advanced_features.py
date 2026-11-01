from __future__ import annotations

import json
import sys
import types
import urllib.request


def _ensure_qgis_stubs() -> None:
    if "qgis" in sys.modules:
        return
    qgis_mod = types.ModuleType("qgis")
    core_mod = types.ModuleType("qgis.core")
    pyqt_mod = types.ModuleType("qgis.PyQt")
    qtcore_mod = types.ModuleType("qgis.PyQt.QtCore")
    qtgui_mod = types.ModuleType("qgis.PyQt.QtGui")

    for cls_name in (
        "QgsApplication",
        "QgsColorRampShader",
        "QgsCoordinateReferenceSystem",
        "QgsCoordinateTransform",
        "QgsFillSymbol",
        "QgsFontUtils",
        "QgsGradientColorRamp",
        "QgsGradientStop",
        "QgsLayoutExporter",
        "QgsLayoutItemLabel",
        "QgsLayoutItemLegend",
        "QgsLayoutItemMap",
        "QgsLayoutItemScaleBar",
        "QgsLayoutPoint",
        "QgsLayoutSize",
        "QgsMapLayer",
        "QgsMessageLog",
        "QgsPrintLayout",
        "QgsProject",
        "QgsRasterBandStats",
        "QgsRasterLayer",
        "QgsRasterShader",
        "QgsRectangle",
        "QgsSettings",
        "QgsSingleBandPseudoColorRenderer",
        "QgsUnitTypes",
        "QgsVectorLayer",
    ):
        setattr(core_mod, cls_name, type(cls_name, (), {}))

    setattr(core_mod, "QgsColorRampShader", type("QgsColorRampShader", (), {"Type": type("Type", (), {"Interpolated": 0, "Discrete": 1, "Exact": 2}), "ColorRampItem": type("ColorRampItem", (), {"__init__": lambda self, *a: None})}))
    setattr(core_mod, "QgsRasterBandStats", type("QgsRasterBandStats", (), {"Stats": type("Stats", (), {"All": 127})}))
    setattr(core_mod, "QgsUnitTypes", type("QgsUnitTypes", (), {"LayoutUnit": type("LayoutUnit", (), {"LayoutMillimeters": 0})}))
    setattr(qtcore_mod, "Qt", type("Qt", (), {"AlignmentFlag": type("AlignmentFlag", (), {"AlignHCenter": 4})}))
    setattr(qtgui_mod, "QColor", type("QColor", (), {"__init__": lambda self, *a: None}))
    setattr(qtgui_mod, "QFont", type("QFont", (), {"__init__": lambda self, *a: None, "Weight": type("Weight", (), {"Bold": 75})}))

    qgis_mod.core = core_mod
    qgis_mod.PyQt = pyqt_mod
    pyqt_mod.QtCore = qtcore_mod
    pyqt_mod.QtGui = qtgui_mod

    sys.modules["qgis"] = qgis_mod
    sys.modules["qgis.core"] = core_mod
    sys.modules["qgis.PyQt"] = pyqt_mod
    sys.modules["qgis.PyQt.QtCore"] = qtcore_mod
    sys.modules["qgis.PyQt.QtGui"] = qtgui_mod


def test_mcp_bridge_serves_status_tools_and_call():
    _ensure_qgis_stubs()
    from core.mcp_bridge import AutoGISMCPBridge

    class _DummySpec:
        def __init__(self, name: str):
            self.name = name
            self.description = f"Desc for {name}"
            self.risk = "read"
            self.parameters = {"type": "object", "properties": {}}
            self.handler = lambda iface, args, **kw: {"echo": args.get("msg", "ok")}

    class _DummyEngine:
        ASYNC_NETWORK_TOOLS = frozenset()

        def __init__(self):
            self._iface = None
            self.tools = {"ping_tool": _DummySpec("ping_tool")}

        def run_on_main_thread(self, fn, timeout=10.0):
            return fn()

    engine = _DummyEngine()
    bridge = AutoGISMCPBridge(engine, port=0)
    assert bridge.start() is True
    try:
        with urllib.request.urlopen(f"{bridge.url}/status", timeout=5) as resp:
            status = json.loads(resp.read().decode("utf-8"))
        assert status["ok"] is True
        assert status["tool_count"] == 1

        with urllib.request.urlopen(f"{bridge.url}/tools", timeout=5) as resp:
            tools_data = json.loads(resp.read().decode("utf-8"))
        assert tools_data["ok"] is True
        assert tools_data["tools"][0]["name"] == "ping_tool"

        req = urllib.request.Request(
            f"{bridge.url}/call",
            data=json.dumps({"tool": "ping_tool", "arguments": {"msg": "hello_qgis"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            call_res = json.loads(resp.read().decode("utf-8"))
        assert call_res["ok"] is True
        assert call_res["result"] == {"echo": "hello_qgis"}
    finally:
        bridge.stop()


def test_advanced_gis_catalogs_and_ollama_config():
    _ensure_qgis_stubs()
    from core.advanced_gis_tools import INDIA_AND_GLOBAL_SERVICES, RASTER_PALETTES
    from core.config import PROVIDER_ENDPOINTS, PROVIDER_MODELS
    from core.gis_tools import build_autogis_tools

    assert "isro_bhuvan_lulc" in INDIA_AND_GLOBAL_SERVICES
    assert "esa_worldcover_10m" in INDIA_AND_GLOBAL_SERVICES
    assert "terrain" in RASTER_PALETTES
    assert "ollama" in PROVIDER_ENDPOINTS
    assert any(m[0].startswith("ollama/") for m in PROVIDER_MODELS["ollama"])

    tools = build_autogis_tools()
    for expected in (
        "inspect_raster_layer",
        "style_raster_layer",
        "compute_zonal_statistics",
        "export_publication_map",
        "export_interactive_webmap",
        "fetch_live_hazard_feed",
        "load_india_national_gis",
        "query_xerj_corpus",
    ):
        assert expected in tools, f"Missing tool {expected}"
        assert callable(tools[expected].handler)


def test_query_xerj_corpus_end_to_end(tmp_path, monkeypatch):
    _ensure_qgis_stubs()
    import http.server
    import threading
    from core.advanced_gis_tools import tool_query_xerj_corpus
    from core.config import AutoGISConfig

    # 1. Test Built-in Corpus + Local Workspace Indexing (when local XERJ daemon is offline)
    sample_py = tmp_path / "glof_pipeline.py"
    sample_py.write_text(
        "# Custom Himachal GLOF Sentinel-1 SAR threshold\nsar_water = s1_vv.lt(-16.5)\n",
        encoding="utf-8",
    )
    res_offline = tool_query_xerj_corpus(
        None,
        {
            "query": "Sentinel-1 SAR water mask glof",
            "domain": "gee",
            "workspace_path": str(tmp_path),
            "limit": 5,
        },
    )
    assert res_offline["status"] == "ok"
    assert len(res_offline["corpus_hits"]) >= 1
    assert res_offline["corpus_hits"][0]["id"] == "gee-sentinel1-sar-glof-water-mask"
    assert len(res_offline["workspace_hits"]) == 1
    assert res_offline["workspace_hits"][0]["file"] == "glof_pipeline.py"

    # 2. Test Live Local XERJ Daemon HTTP REST Search (`/_search`)
    class _MockXERJHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({
                "hits": {
                    "hits": [
                        {
                            "_id": "xerj-rust-ast-01",
                            "_score": 9.8,
                            "_source": {
                                "title": "PyQGIS Float32 NDVI Raster Calculator",
                                "domain": "gdal",
                                "snippet": "processing.run('gdal:rastercalculator', {'RTYPE': 5})",
                            },
                        }
                    ]
                }
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), _MockXERJHandler)
    port = server.server_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        monkeypatch.setattr(AutoGISConfig, "xerj_url", property(lambda self: f"http://127.0.0.1:{port}"))
        res_online = tool_query_xerj_corpus(None, {"query": "Float32 NDVI rastercalculator", "limit": 3})
        assert res_online["status"] == "ok"
        assert res_online["xerj_daemon_online"] is True
        assert len(res_online["local_daemon_hits"]) == 1
        assert res_online["local_daemon_hits"][0]["id"] == "xerj-rust-ast-01"
    finally:
        server.shutdown()
        server.server_close()


