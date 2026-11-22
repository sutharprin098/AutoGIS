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
        "QgsFields",
        "QgsFillSymbol",
        "QgsFontUtils",
        "QgsGeometry",
        "QgsGraduatedSymbolRenderer",
        "QgsGradientColorRamp",
        "QgsGradientStop",
        "QgsHeatmapRenderer",
        "QgsJsonExporter",
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

    setattr(core_mod, "QgsFields", type("QgsFields", (), {
        "__init__": lambda self, *a: None,
        "append": lambda self, *a: None,
        "toList": lambda self: [],
    }))
    setattr(core_mod, "QgsJsonExporter", type("QgsJsonExporter", (), {
        "__init__": lambda self, *a: None,
        "setSourceCrs": lambda self, *a: None,
        "setDestinationCrs": lambda self, *a: None,
        "exportFeatures": lambda self, *a: '{"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [75.8, 26.9]}, "properties": {"name": "Test"}}]}',
    }))
    class MockPointXY:
        def __init__(self, x=0.0, y=0.0):
            self._x = float(x)
            self._y = float(y)
        def x(self):
            return self._x
        def y(self):
            return self._y
        def __repr__(self):
            return f"PointXY({self._x}, {self._y})"
        def __eq__(self, other):
            if not hasattr(other, "x") or not hasattr(other, "y"):
                return False
            return abs(self._x - other.x()) < 1e-6 and abs(self._y - other.y()) < 1e-6
    setattr(core_mod, "QgsPointXY", MockPointXY)

    class MockGeometry:
        def __init__(self, *a, **k):
            self._wkt = "POLYGON(...)"
        def area(self):
            return 1500.0
        def length(self):
            return 160.0
        def asWkt(self):
            return self._wkt
        def isGeosValid(self):
            return True
        def makeValid(self):
            return self
        def simplify(self, tol):
            return self
        def intersects(self, other):
            return True
        def intersection(self, other):
            return self
        def combine(self, other):
            return self
        @staticmethod
        def fromRect(r):
            return MockGeometry()
        @staticmethod
        def fromPolygonXY(rings):
            return MockGeometry()
    setattr(core_mod, "QgsGeometry", MockGeometry)

    mock_rect = type("MockRect", (), {
        "__init__": lambda self, *a: None,
        "width": lambda self: 0.1,
        "height": lambda self: 0.1,
        "xMinimum": lambda self: 75.7,
        "yMinimum": lambda self: 26.8,
        "xMaximum": lambda self: 75.8,
        "yMaximum": lambda self: 26.9,
        "isValid": lambda self: True,
        "intersects": lambda self, *a: True,
    })
    setattr(core_mod, "QgsRectangle", mock_rect)

    mock_dp = type("MockDP", (), {
        "addAttributes": lambda self, *a: True,
        "addFeatures": lambda self, *a: True,
    })
    mock_feat = type("MockFeature", (), {
        "__init__": lambda self, *a: None,
        "setGeometry": lambda self, *a: None,
        "setAttribute": lambda self, *a: None,
        "id": lambda self: 1,
    })
    setattr(core_mod, "QgsFeature", mock_feat)

    orig_vl = getattr(core_mod, "QgsVectorLayer")
    class _MockVectorLayer(orig_vl):
        def __init__(self, uri="", name="MockLayer", *a, **k):
            self._name = name or "MockLayer"
            self._uri = uri
        def name(self):
            return self._name
        def id(self):
            return self._name + "_id"
        def dataProvider(self):
            return mock_dp()
        def updateFields(self):
            pass
        def updateExtents(self):
            pass
        def fields(self):
            return type("Fields", (), {"toList": lambda *a: [], "__iter__": lambda *a: iter([])})()
        def getFeatures(self, *a):
            return [mock_feat()]
        def geometryType(self):
            return 2
        def extent(self):
            return mock_rect()
        def setCustomProperty(self, *a):
            pass
        def selectByIds(self, *a):
            pass
    setattr(core_mod, "QgsVectorLayer", _MockVectorLayer)

    orig_rl = getattr(core_mod, "QgsRasterLayer")
    class _MockRasterLayer(orig_rl):
        def __init__(self, path="", name="MockLayer", *a, **k):
            self._name = name or "MockLayer"
            self._path = path
        def name(self):
            return self._name
        def id(self):
            return self._name + "_id"
        def extent(self):
            return mock_rect()
        def bandCount(self):
            return 3
    setattr(core_mod, "QgsRasterLayer", _MockRasterLayer)

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
        def crs(self):
            return type("CRS", (), {"authid": lambda *a: "EPSG:4326", "isValid": lambda *a: True, "isGeographic": lambda *a: True})()
        def setCrs(self, c):
            pass
        def removeMapLayer(self, lid):
            self._layers.pop(lid, None)
        def mapLayer(self, lid):
            return self._layers.get(lid)
        def layerTreeRoot(self):
            return None

    setattr(core_mod, "QgsProject", _MockProject)
    setattr(qtcore_mod, "Qt", type("Qt", (), {"AlignmentFlag": type("AlignmentFlag", (), {"AlignHCenter": 4})}))
    setattr(qtcore_mod, "QSize", type("QSize", (), {}))
    setattr(qtcore_mod, "QVariant", type("QVariant", (), {"String": 10, "Int": 2, "Double": 6, "Bool": 1, "Type": type("Type", (), {"String": 10, "Int": 2, "Double": 6, "Bool": 1})}))
    setattr(qtcore_mod, "QObject", type("QObject", (), {"__init__": lambda self, *a, **k: None}))
    setattr(qtcore_mod, "QCoreApplication", type("QCoreApplication", (), {"processEvents": staticmethod(lambda *a: None)}))
    setattr(qtcore_mod, "QTimer", type("QTimer", (), {"__init__": lambda self, *a, **k: None, "setInterval": lambda *a: None, "start": lambda *a: None, "isActive": lambda *a: False, "timeout": type("Signal", (), {"connect": lambda *a: None})()}))
    setattr(qtcore_mod, "pyqtSignal", lambda *a, **k: type("Signal", (), {"connect": lambda *a: None, "emit": lambda *a: None})())
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
