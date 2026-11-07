from __future__ import annotations

import os
import sys
import types

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _install_qgis_stubs() -> None:
    if "qgis" in sys.modules:
        return
    qgis_mod = types.ModuleType("qgis")
    core_mod = types.ModuleType("qgis.core")
    pyqt_mod = types.ModuleType("qgis.PyQt")
    qtcore_mod = types.ModuleType("qgis.PyQt.QtCore")
    qtgui_mod = types.ModuleType("qgis.PyQt.QtGui")

    for cls_name in (
        "QgsApplication",
        "QgsCategorizedSymbolRenderer",
        "QgsColorRampShader",
        "QgsCoordinateReferenceSystem",
        "QgsCoordinateTransform",
        "QgsExpression",
        "QgsExpressionContext",
        "QgsExpressionContextUtils",
        "QgsFeature",
        "QgsFeatureRequest",
        "QgsField",
        "QgsFillSymbol",
        "QgsFontUtils",
        "QgsGeometry",
        "QgsGraduatedSymbolRenderer",
        "QgsGradientColorRamp",
        "QgsGradientStop",
        "QgsHeatmapRenderer",
        "QgsLayoutExporter",
        "QgsLayoutItemLabel",
        "QgsLayoutItemLegend",
        "QgsLayoutItemMap",
        "QgsLayoutItemScaleBar",
        "QgsLayoutPoint",
        "QgsLayoutSize",
        "QgsLineSymbol",
        "QgsMapLayer",
        "QgsMarkerSymbol",
        "QgsMessageLog",
        "QgsPalLayerSettings",
        "QgsPointXY",
        "QgsPrintLayout",
        "QgsRasterBandStats",
        "QgsRasterLayer",
        "QgsRasterShader",
        "QgsRasterTransparency",
        "QgsRasterTransparencyPixel",
        "QgsRasterTransparencySingleValuePixel",
        "QgsRectangle",
        "QgsRendererCategory",
        "QgsRendererRange",
        "QgsSettings",
        "QgsSingleBandPseudoColorRenderer",
        "QgsSingleSymbolRenderer",
        "QgsSymbol",
        "QgsTextBufferSettings",
        "QgsTextFormat",
        "QgsUnitTypes",
        "QgsVectorFileWriter",
        "QgsVectorLayer",
        "QgsVectorLayerSimpleLabeling",
        "QgsWkbTypes",
    ):
        cls_dict = {
            "__init__": lambda self, *a, **k: None,
            "isValid": lambda self: True,
            "name": lambda self: "MockLayer",
            "id": lambda self: "mock_layer_1",
            "featureCount": lambda self: 10,
            "crs": lambda self: type("CRS", (), {"authid": lambda *a: "EPSG:4326", "isValid": lambda *a: True, "isGeographic": lambda *a: True})(),
        }
        setattr(core_mod, cls_name, type(cls_name, (), cls_dict))

    setattr(core_mod, "QgsColorRampShader", type("QgsColorRampShader", (), {"Type": type("Type", (), {"Interpolated": 0, "Discrete": 1, "Exact": 2}), "ColorRampItem": type("ColorRampItem", (), {"__init__": lambda self, *a: None})}))
    setattr(core_mod, "QgsRasterBandStats", type("QgsRasterBandStats", (), {"Stats": type("Stats", (), {"All": 127})}))
    setattr(core_mod, "QgsUnitTypes", type("QgsUnitTypes", (), {"LayoutUnit": type("LayoutUnit", (), {"LayoutMillimeters": 0})}))

    class _MockProject:
        _instance = None
        def __init__(self):
            self._layers = {}
            self._props = {}
        @classmethod
        def instance(cls):
            if cls._instance is None:
                cls._instance = _MockProject()
            return cls._instance
        def mapLayers(self):
            return self._layers
        def addMapLayer(self, lyr):
            self._layers[getattr(lyr, "id", lambda: "id")()] = lyr
        def title(self):
            return "Test Project"
        def fileName(self):
            return "test.qgs"
        def customProperty(self, k, default=None):
            return self._props.get(k, default)
        def setCustomProperty(self, k, v):
            self._props[k] = v
        def layerTreeRoot(self):
            return None

    setattr(core_mod, "QgsProject", _MockProject)
    setattr(qtcore_mod, "Qt", type("Qt", (), {"AlignmentFlag": type("AlignmentFlag", (), {"AlignHCenter": 4})}))
    setattr(qtcore_mod, "QSize", type("QSize", (), {}))
    setattr(qtcore_mod, "QVariant", type("QVariant", (), {"String": 10, "Int": 2, "Double": 6, "Bool": 1, "Type": type("Type", (), {"String": 10, "Int": 2, "Double": 6, "Bool": 1})}))
    setattr(qtgui_mod, "QColor", type("QColor", (), {"__init__": lambda self, *a: None}))
    setattr(qtgui_mod, "QFont", type("QFont", (), {"__init__": lambda self, *a: None, "Weight": type("Weight", (), {"Bold": 75})}))
    setattr(qtgui_mod, "QImage", type("QImage", (), {"__init__": lambda self, *a: None, "fill": lambda self, *a: None, "save": lambda self, *a: True, "Format": type("Format", (), {"Format_ARGB32_Premultiplied": 6})}))
    setattr(qtgui_mod, "QPainter", type("QPainter", (), {"__init__": lambda self, *a: None, "setPen": lambda self, *a: None, "setFont": lambda self, *a: None, "drawText": lambda self, *a: None, "end": lambda self: None}))

    qgis_mod.core = core_mod
    qgis_mod.PyQt = pyqt_mod
    pyqt_mod.QtCore = qtcore_mod
    pyqt_mod.QtGui = qtgui_mod

    sys.modules["qgis"] = qgis_mod
    sys.modules["qgis.core"] = core_mod
    sys.modules["qgis.PyQt"] = pyqt_mod
    sys.modules["qgis.PyQt.QtCore"] = qtcore_mod
    sys.modules["qgis.PyQt.QtGui"] = qtgui_mod


_install_qgis_stubs()
