from __future__ import annotations


def classFactory(iface):
    from .plugin import AutoGISPlugin
    return AutoGISPlugin(iface)
