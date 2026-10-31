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
        "QgsPrintLayout",
        "QgsProject",
        "QgsRasterBandStats",
        "QgsRasterLayer",
        "QgsRasterShader",
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
        setattr(core_mod, cls_name, type(cls_name, (), {}))

    setattr(qtcore_mod, "Qt", type("Qt", (), {"AlignmentFlag": type("AlignmentFlag", (), {"AlignHCenter": 4})}))
    setattr(qtcore_mod, "QSize", type("QSize", (), {}))
    setattr(qtcore_mod, "QVariant", type("QVariant", (), {"String": 10, "Int": 2, "Double": 6, "Bool": 1}))
    setattr(qtgui_mod, "QColor", type("QColor", (), {"__init__": lambda self, *a: None}))
    setattr(qtgui_mod, "QFont", type("QFont", (), {"__init__": lambda self, *a: None, "Weight": type("Weight", (), {"Bold": 75})}))
    setattr(qtgui_mod, "QImage", type("QImage", (), {"Format": type("Format", (), {"Format_ARGB32_Premultiplied": 6})}))

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
