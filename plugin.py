from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import QAction

from .core.config import AutoGISConfig, log_info, log_warn
from .ui.dock_panel import AutoGISDockWidget
from .ui.settings_dialog import AutoGISSettingsDialog
from .ui.theme import create_autogis_icon, ensure_logo_png

MENU_TITLE = "&AutoGIS Studio"
SHORTCUT_KEY = "Ctrl+Shift+G"


class AutoGISPlugin:
    """Main QGIS Plugin lifecycle controller for AutoGIS Studio."""

    def __init__(self, iface) -> None:
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.config = AutoGISConfig()
        self.dock: AutoGISDockWidget | None = None
        self.toggle_action: QAction | None = None
        self.settings_action: QAction | None = None

    def initGui(self) -> None:  # noqa: N802
        try:
            ensure_logo_png(self.plugin_dir)
        except Exception as exc:
            log_warn(f"Logo PNG generation warning: {exc}")

        icon = create_autogis_icon()
        main_win = self.iface.mainWindow() if self.iface else None

        self.toggle_action = QAction(icon, "AutoGIS Studio", main_win)
        self.toggle_action.setObjectName("autogisToggleDockAction")
        self.toggle_action.setToolTip(f"AutoGIS Autonomous Geospatial AI Studio ({SHORTCUT_KEY})")
        self.toggle_action.setShortcut(QKeySequence(SHORTCUT_KEY))
        self.toggle_action.triggered.connect(self.toggle_dock)

        self.settings_action = QAction(icon, "AutoGIS OpenRouter Settings...", main_win)
        self.settings_action.setObjectName("autogisOpenSettingsAction")
        self.settings_action.triggered.connect(self.open_settings)

        if self.iface:
            self.iface.addToolBarIcon(self.toggle_action)
            self.iface.addPluginToMenu(MENU_TITLE, self.toggle_action)
            self.iface.addPluginToMenu(MENU_TITLE, self.settings_action)

        QTimer.singleShot(150, self._open_on_startup)
        log_info("AutoGIS Studio v2.0 initialized successfully.")

    def _open_on_startup(self) -> None:
        self._ensure_dock()
        if self.dock is not None and self.config.dock_visible:
            self.dock.show()
            self.dock.raise_()

    def _ensure_dock(self) -> None:
        if self.dock is not None:
            return
        main_win = self.iface.mainWindow() if self.iface else None
        self.dock = AutoGISDockWidget(self.iface, self.config, main_win)
        self.dock.visibilityChanged.connect(self._on_visibility_changed)
        if self.iface:
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    def _on_visibility_changed(self, visible: bool) -> None:
        if self.iface and self.iface.mainWindow() and self.iface.mainWindow().isVisible():
            self.config.dock_visible = bool(visible)

    def toggle_dock(self) -> None:
        if self.dock is None:
            self._ensure_dock()
            if self.dock is not None:
                self.dock.show()
                self.dock.raise_()
            return
        if self.dock.isVisible():
            self.dock.hide()
        else:
            self.dock.show()
            self.dock.raise_()

    def open_settings(self) -> None:
        if self.dock is not None and self.dock.panel is not None:
            self.dock.panel.open_settings_dialog()
            return
        main_win = self.iface.mainWindow() if self.iface else None
        dlg = AutoGISSettingsDialog(self.config, main_win)
        dlg.exec()

    def unload(self) -> None:
        if self.dock is not None:
            try:
                self.dock.visibilityChanged.disconnect(self._on_visibility_changed)
            except Exception:
                pass
            if self.dock.panel is not None:
                self.dock.panel._engine.cancel_current_run()
            if self.iface:
                self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        if self.iface:
            if self.toggle_action is not None:
                self.iface.removeToolBarIcon(self.toggle_action)
                self.iface.removePluginMenu(MENU_TITLE, self.toggle_action)
            if self.settings_action is not None:
                self.iface.removePluginMenu(MENU_TITLE, self.settings_action)

        self.toggle_action = None
        self.settings_action = None
