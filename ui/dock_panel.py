from __future__ import annotations

import os
from typing import Any

from qgis.PyQt.QtCore import QEvent, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.agent_engine import AutoGISEngine
from ..core.config import CURATED_MODELS, AutoGISConfig, ThreadHistoryStore
from ..core.gis_tools import _tool_capture_map_canvas
from .settings_dialog import AutoGISSettingsDialog
from .theme import create_autogis_icon, create_autogis_pixmap, get_studio_stylesheet, set_custom_logo_path
from .widgets import (
    AssistantMessageCard,
    InlineMapCard,
    LiveStatusBanner,
    PermissionPromptCard,
    PlanChecklistCard,
    ToolExecutionCard,
    UserMessageCard,
    WelcomeStarterCard,
)


class _PromptEdit(QPlainTextEdit):
    """Multi-line prompt input where Enter sends and Shift+Enter adds a newline."""

    send_triggered = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISInput")
        self.setPlaceholderText("Ask AutoGIS anything — e.g. 'Inspect layers', 'Add satellite basemap', 'Style roads by type'...")
        self.setFixedHeight(64)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                event.accept()
                self.send_triggered.emit()
                return
        super().keyPressEvent(event)


class AutoGISPanel(QWidget):
    """Main studio panel inside the AutoGIS dock widget."""

    def __init__(self, iface, config: AutoGISConfig, parent=None) -> None:
        super().__init__(parent)
        self._iface = iface
        self._config = config
        set_custom_logo_path(self._config.custom_logo_path)
        self._history = ThreadHistoryStore()
        self._engine = AutoGISEngine(iface, config, self)

        self._current_thread_id: str = self._history.create_thread()["id"]
        self._active_assistant_card: AssistantMessageCard | None = None
        self._active_plan_card: PlanChecklistCard | None = None
        self._tool_cards: dict[str, ToolExecutionCard] = {}
        self._attached_files: list[str] = []
        self._pinned_layers: list[str] = []
        self._is_running = False

        self.setObjectName("AutoGISRoot")
        self.setAcceptDrops(True)
        self.setStyleSheet(get_studio_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Top Studio Header
        root.addWidget(self._build_header())

        # 2. Scrollable Conversation Stream
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._stream_host = QWidget(self._scroll)
        self._stream_host.setObjectName("AutoGISRoot")
        self._stream_layout = QVBoxLayout(self._stream_host)
        self._stream_layout.setContentsMargins(12, 12, 12, 12)
        self._stream_layout.setSpacing(10)

        self._welcome_card = WelcomeStarterCard(self._stream_host)
        self._welcome_card.prompt_selected.connect(self._send_quick_prompt)
        self._stream_layout.addWidget(self._welcome_card)

        self._status_banner = LiveStatusBanner(self._stream_host)
        self._stream_layout.addWidget(self._status_banner)
        self._stream_layout.addStretch(1)

        self._scroll.setWidget(self._stream_host)
        root.addWidget(self._scroll, 1)

        # 3. Bottom Composer Area
        root.addWidget(self._build_composer())

        self._wire_engine()
        self._sync_header_status()

    def _build_header(self) -> QFrame:
        hdr = QFrame(self)
        hdr.setObjectName("AutoGISHeader")
        hdr.setFixedHeight(48)

        row = QHBoxLayout(hdr)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(8)

        self._hdr_logo = QLabel(hdr)
        self._hdr_logo.setPixmap(create_autogis_pixmap(28))
        self._hdr_logo.setFixedSize(28, 28)
        row.addWidget(self._hdr_logo)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(0)
        title = QLabel("AutoGIS", hdr)
        title.setStyleSheet("font-size: 14px; font-weight: 800; background: transparent;")
        title_col.addWidget(title)

        self._status_dot = QLabel("○ Select Model & API Key", hdr)
        self._status_dot.setStyleSheet("font-size: 10px; color: #64748B; font-weight: 600; background: transparent;")
        title_col.addWidget(self._status_dot)
        row.addLayout(title_col)

        row.addStretch(1)

        snap_btn = QPushButton("📷 Map", hdr)
        snap_btn.setObjectName("AutoGISGhostBtn")
        snap_btn.setToolTip("Capture current QGIS Map Canvas into chat")
        snap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        snap_btn.clicked.connect(self._capture_canvas_now)
        row.addWidget(snap_btn)

        new_btn = QPushButton("＋ New", hdr)
        new_btn.setObjectName("AutoGISGhostBtn")
        new_btn.setToolTip("Start a new conversation session")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(self.start_new_session)
        row.addWidget(new_btn)

        self._hist_btn = QPushButton("🕒 History", hdr)
        self._hist_btn.setObjectName("AutoGISGhostBtn")
        self._hist_btn.setToolTip("Switch to a previous conversation")
        self._hist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hist_btn.clicked.connect(self._show_history_menu)
        row.addWidget(self._hist_btn)

        cfg_btn = QPushButton("⚙ Settings", hdr)
        cfg_btn.setObjectName("AutoGISGhostBtn")
        cfg_btn.setToolTip("Configure OpenRouter API Key, Models & Preferences")
        cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cfg_btn.clicked.connect(self.open_settings_dialog)
        row.addWidget(cfg_btn)

        return hdr

    def _build_composer(self) -> QWidget:
        host = QWidget(self)
        col = QVBoxLayout(host)
        col.setContentsMargins(12, 4, 12, 12)
        col.setSpacing(6)

        # Context Chips Strip
        self._chips_row = QHBoxLayout()
        self._chips_row.setContentsMargins(0, 0, 0, 0)
        self._chips_row.setSpacing(6)

        pin_lyr_btn = QPushButton("＋ @Active Layer", host)
        pin_lyr_btn.setObjectName("AutoGISGhostBtn")
        pin_lyr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pin_lyr_btn.setToolTip("Pin the currently selected QGIS layer to your prompt")
        pin_lyr_btn.clicked.connect(self._pin_active_layer)
        self._chips_row.addWidget(pin_lyr_btn)

        attach_btn = QPushButton("📎 File / PDF", host)
        attach_btn.setObjectName("AutoGISGhostBtn")
        attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_btn.setToolTip("Upload any file: Large PDFs (.pdf), GeoPDF, Excel (.xlsx), Word (.docx), CSV, Shapefile, GeoJSON, TIF, or Images")
        attach_btn.clicked.connect(self._attach_dataset_file)
        self._chips_row.addWidget(attach_btn)

        folder_btn = QPushButton("📁 Folder", host)
        folder_btn.setObjectName("AutoGISGhostBtn")
        folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_btn.setToolTip("Attach an entire folder of GIS datasets, PDFs, or project files")
        folder_btn.clicked.connect(self._attach_folder)
        self._chips_row.addWidget(folder_btn)

        self._data_btn = QPushButton("🌍 Live Data ▾", host)
        self._data_btn.setObjectName("AutoGISGhostBtn")
        self._data_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._data_btn.setToolTip("Quick-insert Live OSM, Boundary, STAC DEM/Satellite, or OSRM Route prompts")
        self._data_btn.clicked.connect(self._show_live_data_menu)
        self._chips_row.addWidget(self._data_btn)

        self._chips_label = QLabel("", host)
        self._chips_label.setStyleSheet("font-size: 11px; color: #0284C7; font-weight: 600;")
        self._chips_row.addWidget(self._chips_label, 1)

        self._clear_chips_btn = QPushButton("✕", host)
        self._clear_chips_btn.setObjectName("AutoGISGhostBtn")
        self._clear_chips_btn.setFixedWidth(24)
        self._clear_chips_btn.hide()
        self._clear_chips_btn.clicked.connect(self._clear_chips)
        self._chips_row.addWidget(self._clear_chips_btn)

        col.addLayout(self._chips_row)

        # Composer Frame
        box = QFrame(host)
        box.setObjectName("AutoGISComposerFrame")
        box_col = QVBoxLayout(box)
        box_col.setContentsMargins(10, 8, 10, 8)
        box_col.setSpacing(6)

        self._input = _PromptEdit(box)
        self._input.send_triggered.connect(self._on_send_clicked)
        box_col.addWidget(self._input)

        # Bottom Controls Row (Model Switcher + Mode Switcher + Send/Stop)
        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(6)

        self._model_combo = QComboBox(box)
        self._model_combo.setObjectName("AutoGISCombo")
        self._model_combo.setToolTip("Quick-switch OpenRouter AI Model")
        self._model_combo.setMaximumWidth(185)
        self._sync_model_combo()
        self._model_combo.currentIndexChanged.connect(self._on_quick_model_changed)
        ctrl.addWidget(self._model_combo, 1)

        self._mode_combo = QComboBox(box)
        self._mode_combo.setObjectName("AutoGISCombo")
        self._mode_combo.setToolTip("Agent Execution Mode")
        self._mode_combo.addItem("⚡ Autopilot", "autopilot")
        self._mode_combo.addItem("🛡️ Ask Write", "ask_write")
        self._mode_combo.addItem("💬 Chat Only", "chat_only")
        self._sync_mode_combo()
        self._mode_combo.currentIndexChanged.connect(self._on_quick_mode_changed)
        ctrl.addWidget(self._mode_combo)

        self._send_btn = QPushButton("Send ➤", box)
        self._send_btn.setObjectName("AutoGISPrimaryBtn")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send_clicked)
        ctrl.addWidget(self._send_btn)

        self._stop_btn = QPushButton("⏹ Stop", box)
        self._stop_btn.setObjectName("AutoGISStopBtn")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.hide()
        self._stop_btn.clicked.connect(self._engine.cancel_current_run)
        ctrl.addWidget(self._stop_btn)

        box_col.addLayout(ctrl)
        col.addWidget(box)
        return host

    def _wire_engine(self) -> None:
        e = self._engine
        e.run_started.connect(self._on_run_started)
        e.status_updated.connect(self._on_status_updated)
        e.reasoning_chunk.connect(self._on_reasoning_chunk)
        e.token_chunk.connect(self._on_token_chunk)
        e.assistant_step_done.connect(self._on_assistant_step_done)
        e.tool_call_started.connect(self._on_tool_call_started)
        e.tool_call_finished.connect(self._on_tool_call_finished)
        e.plan_updated.connect(self._on_plan_updated)
        e.map_captured.connect(self._on_map_captured)
        e.permission_requested.connect(self._on_permission_requested)
        e.run_finished.connect(self._on_run_finished)

    def _sync_header_status(self) -> None:
        self._hdr_logo.setPixmap(create_autogis_pixmap(28))
        curr_model = self._config.model.strip()
        if not curr_model:
            self._status_dot.setText("○ Select Model & API Key")
            self._status_dot.setStyleSheet("font-size: 10px; color: #64748B; font-weight: 600; background: transparent;")
            return
        provider, api_key, _url, api_mod = self._config.resolve_connection(curr_model)
        if api_key and api_mod:
            short_m = api_mod.split("/")[-1]
            self._status_dot.setText(f"● Ready · {short_m[:20]} ({provider})")
            self._status_dot.setStyleSheet("font-size: 10px; color: #16A34A; font-weight: 600; background: transparent;")
        else:
            self._status_dot.setText("○ Set API Key in Settings")
            self._status_dot.setStyleSheet("font-size: 10px; color: #D97706; font-weight: 600; background: transparent;")

    def _sync_model_combo(self) -> None:
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        curr = self._config.model.strip()
        found = False
        for mid, mlabel in CURATED_MODELS:
            short_lbl = mlabel.split("(")[0].strip() if mid else mlabel
            self._model_combo.addItem(short_lbl, mid)
            if mid == curr:
                self._model_combo.setCurrentIndex(self._model_combo.count() - 1)
                found = True
        if not found and curr:
            self._model_combo.addItem(curr.split("/")[-1], curr)
            self._model_combo.setCurrentIndex(self._model_combo.count() - 1)
        elif not curr:
            self._model_combo.setCurrentIndex(0)
        self._model_combo.blockSignals(False)

    def _sync_mode_combo(self) -> None:
        self._mode_combo.blockSignals(True)
        curr = self._config.execution_mode
        for i in range(self._mode_combo.count()):
            if self._mode_combo.itemData(i) == curr:
                self._mode_combo.setCurrentIndex(i)
                break
        self._mode_combo.blockSignals(False)

    def _on_quick_model_changed(self, idx: int) -> None:
        if idx >= 0:
            mid = self._model_combo.itemData(idx)
            self._config.model = str(mid or "")
            self._sync_header_status()

    def _on_quick_mode_changed(self, idx: int) -> None:
        if idx >= 0:
            mode = self._mode_combo.itemData(idx)
            if mode:
                self._config.execution_mode = str(mode)

    def _insert_stream_widget(self, widget: QWidget) -> None:
        self._welcome_card.hide()
        # Insert right before the status banner and bottom stretch
        idx = self._stream_layout.indexOf(self._status_banner)
        if idx < 0:
            idx = max(0, self._stream_layout.count() - 1)
        self._stream_layout.insertWidget(idx, widget)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        QTimer.singleShot(15, lambda: self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum()))

    def _pin_active_layer(self) -> None:
        lyr = self._iface.activeLayer() if self._iface else None
        if lyr is None:
            return
        name = lyr.name()
        if name not in self._pinned_layers:
            self._pinned_layers.append(name)
        self._refresh_chips_ui()

    def _attach_dataset_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Upload Any File, Large PDF, Document, Spreadsheet, or GIS Dataset",
            "",
            "All Supported Files (*.pdf *.docx *.xlsx *.xls *.csv *.tsv *.txt *.md *.json *.geojson *.gpkg *.shp *.kml *.gml *.tif *.tiff *.dem *.laz *.las *.png *.jpg *.jpeg *.py *.sql);;PDF Documents (*.pdf);;GIS Datasets (*.geojson *.gpkg *.shp *.kml *.tif *.tiff);;Spreadsheets & Docs (*.csv *.xlsx *.docx *.txt);;All Files (*.*)",
        )
        for path in paths:
            if path and path not in self._attached_files:
                self._attached_files.append(path)
        self._refresh_chips_ui()

    def _attach_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Attach Project or Data Folder to AutoGIS",
            "",
        )
        if folder and folder not in self._attached_files:
            self._attached_files.append(folder)
            self._refresh_chips_ui()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        if event.mimeData() and event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if local_path and os.path.exists(local_path) and local_path not in self._attached_files:
                    self._attached_files.append(local_path)
            self._refresh_chips_ui()
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _clear_chips(self) -> None:
        self._pinned_layers.clear()
        self._attached_files.clear()
        self._refresh_chips_ui()

    def _refresh_chips_ui(self) -> None:
        parts = [f"@{ln}" for ln in self._pinned_layers]
        for p in self._attached_files:
            base = os.path.basename(p.rstrip("\\/")) or p
            if os.path.isdir(p):
                parts.append(f"📁 {base}")
            elif p.lower().endswith(".pdf"):
                parts.append(f"📄 {base}")
            else:
                parts.append(f"📎 {base}")
        self._chips_label.setText("  ".join(parts))
        self._clear_chips_btn.setVisible(bool(parts))

    def _capture_canvas_now(self) -> None:
        res = _tool_capture_map_canvas(self._iface, {})
        if res.get("image_path"):
            card = InlineMapCard(res["image_path"], self._stream_host)
            self._insert_stream_widget(card)

    def _show_live_data_menu(self) -> None:
        menu = QMenu(self)
        presets = [
            ("🏛️ Place / City Polygon Boundary (Nominatim)", "Download the exact polygon administrative boundary for "),
            ("🏗️ OSM Buildings (Overpass API)", "Download live OpenStreetMap buildings for the current map view or "),
            ("🛣️ OSM Road Network (Overpass API)", "Download live OpenStreetMap roads for the current map view or "),
            ("💧 OSM Rivers & Waterbodies (Overpass API)", "Download live OpenStreetMap rivers and water bodies for "),
            ("🏥 OSM Hospitals & Schools (Overpass API)", "Download live OpenStreetMap hospitals and schools for "),
            ("🚗 OSRM Shortest Road Route", "Calculate the driving road route from [Origin] to [Destination] and load it."),
            ("🏔️ Copernicus 30m DEM Elevation (STAC COG)", "Stream the Copernicus 30m Elevation DEM from Planetary Computer STAC for the current map area."),
            ("🛰️ Sentinel-2 10m True Color Imagery (STAC COG)", "Stream the latest low-cloud Sentinel-2 10m optical imagery from Planetary Computer STAC for the current map area."),
            ("🌿 Esri 10m Land Cover LULC (STAC COG)", "Stream the Esri 10m Land Cover (LULC) raster from Planetary Computer STAC for the current map area."),
            ("🌐 Saved QGIS WMS / WFS / XYZ Connections", "List all my saved QGIS XYZ, WMS (Bhuvan), and WFS connections."),
        ]
        for label, prompt_tpl in presets:
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, p=prompt_tpl: self._fill_prompt(p))
        menu.exec(self._data_btn.mapToGlobal(self._data_btn.rect().topLeft()))

    def _fill_prompt(self, text: str) -> None:
        self._input.setPlainText(text)
        self._input.setFocus()
        cursor = self._input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._input.setTextCursor(cursor)

    def _send_quick_prompt(self, prompt_text: str) -> None:
        self._input.setPlainText(prompt_text)
        self._on_send_clicked()

    def _on_send_clicked(self) -> None:
        if self._is_running:
            return
        text = self._input.toPlainText().strip()
        if not text and not self._attached_files:
            return
        if not text:
            text = "Please load and inspect the attached dataset."

        display_text = text
        if self._pinned_layers:
            display_text += "\n\nLayers: " + ", ".join(f"@{l}" for l in self._pinned_layers)
        if self._attached_files:
            display_text += "\n\nFiles: " + ", ".join(os.path.basename(f) for f in self._attached_files)

        user_card = UserMessageCard(display_text, self._stream_host)
        self._insert_stream_widget(user_card)

        attachments = list(self._attached_files)
        mentions = list(self._pinned_layers)
        self._input.clear()
        self._clear_chips()

        # Save user message to thread history
        first_line = text.splitlines()[0][:45]
        th = self._history.get_thread(self._current_thread_id)
        new_title = first_line if (th and not th.get("ui_log")) else None
        self._history.update_thread(
            self._current_thread_id,
            title=new_title,
            ui_entry={"role": "user", "text": display_text},
        )

        self._engine.start_user_turn(text, attachments=attachments, layer_mentions=mentions)

    # ========================================================================
    # ENGINE SIGNAL HANDLERS
    # ========================================================================

    def _on_run_started(self, run_id: str, model: str) -> None:
        self._is_running = True
        self._send_btn.hide()
        self._stop_btn.show()
        self._active_assistant_card = None
        self._active_plan_card = None
        self._status_banner.start_status(f"Thinking with {model.split('/')[-1]}...")
        self._scroll_to_bottom()

    def _on_status_updated(self, run_id: str, status_text: str) -> None:
        if status_text:
            self._status_banner.start_status(status_text)
        else:
            self._status_banner.stop_status()
        self._scroll_to_bottom()

    def _ensure_assistant_card(self) -> AssistantMessageCard:
        if self._active_assistant_card is None:
            self._active_assistant_card = AssistantMessageCard(self._config.model, self._stream_host)
            self._insert_stream_widget(self._active_assistant_card)
        return self._active_assistant_card

    def _on_reasoning_chunk(self, run_id: str, chunk: str) -> None:
        card = self._ensure_assistant_card()
        card.append_reasoning(chunk)
        self._scroll_to_bottom()

    def _on_token_chunk(self, run_id: str, chunk: str) -> None:
        card = self._ensure_assistant_card()
        card.append_text(chunk)
        self._scroll_to_bottom()

    def _on_assistant_step_done(self, run_id: str, step_text: str) -> None:
        self._active_assistant_card = None

    def _on_tool_call_started(self, run_id: str, call_id: str, name: str, args: object) -> None:
        self._active_assistant_card = None
        args_dict = args if isinstance(args, dict) else {}
        tcard = ToolExecutionCard(call_id, name, args_dict, self._stream_host)
        self._tool_cards[call_id] = tcard
        self._insert_stream_widget(tcard)

    def _on_tool_call_finished(self, run_id: str, call_id: str, name: str,
                               result: object, elapsed_ms: int, is_err: bool) -> None:
        tcard = self._tool_cards.get(call_id)
        if tcard is not None:
            tcard.mark_finished(result, elapsed_ms, is_err)
        self._scroll_to_bottom()

    def _on_plan_updated(self, run_id: str, title: str, steps: object) -> None:
        steps_list = steps if isinstance(steps, list) else []
        if self._active_plan_card is None:
            self._active_plan_card = PlanChecklistCard(title, steps_list, self._stream_host)
            self._insert_stream_widget(self._active_plan_card)
        else:
            self._active_plan_card.update_plan(title, steps_list)
        self._scroll_to_bottom()

    def _on_map_captured(self, run_id: str, image_path: str) -> None:
        mcard = InlineMapCard(image_path, self._stream_host)
        self._insert_stream_widget(mcard)

    def _on_permission_requested(self, run_id: str, call_id: str, name: str, args: object) -> None:
        self._active_assistant_card = None
        args_dict = args if isinstance(args, dict) else {}
        pcard = PermissionPromptCard(call_id, name, args_dict, self._stream_host)
        pcard.decided.connect(self._engine.resolve_permission)
        self._insert_stream_widget(pcard)

    def _on_run_finished(self, run_id: str, status: str, final_text: str) -> None:
        self._is_running = False
        self._stop_btn.hide()
        self._send_btn.show()
        self._status_banner.stop_status()
        self._active_assistant_card = None

        self._history.update_thread(
            self._current_thread_id,
            messages=self._engine.messages,
            ui_entry={"role": "assistant", "text": final_text, "status": status},
        )
        self._scroll_to_bottom()

    # ========================================================================
    # SESSION & SETTINGS MANAGEMENT
    # ========================================================================

    def start_new_session(self) -> None:
        if self._is_running:
            self._engine.cancel_current_run()
        self._engine.clear_conversation()
        self._tool_cards.clear()
        self._active_assistant_card = None

        # Remove existing chat widgets except welcome card, status banner, and stretch
        for i in reversed(range(self._stream_layout.count())):
            item = self._stream_layout.itemAt(i)
            w = item.widget() if item else None
            if w is not None and w not in (self._welcome_card, self._status_banner):
                self._stream_layout.removeWidget(w)
                w.deleteLater()

        self._welcome_card.show()
        self._current_thread_id = self._history.create_thread()["id"]

    def _show_history_menu(self) -> None:
        menu = QMenu(self)
        threads = self._history.list_threads()
        if not threads:
            act = menu.addAction("No saved sessions yet")
            act.setEnabled(False)
        else:
            for th in threads[:20]:
                tid = th.get("id", "")
                title = th.get("title") or "Untitled Session"
                msg_count = len(th.get("ui_log") or [])
                if msg_count == 0 and tid == self._current_thread_id:
                    continue
                act = menu.addAction(f"💬 {title} ({msg_count} turns)")
                act.triggered.connect(lambda _=False, t=tid: self._load_thread(t))
            menu.addSeparator()
            clear_act = menu.addAction("🗑️ Clear All History")
            clear_act.triggered.connect(self._history.clear_all)
        menu.exec(self._hist_btn.mapToGlobal(self._hist_btn.rect().bottomLeft()))

    def _load_thread(self, thread_id: str) -> None:
        th = self._history.get_thread(thread_id)
        if not th:
            return
        self.start_new_session()
        self._current_thread_id = thread_id
        self._engine.load_messages(th.get("messages") or [])
        ui_log = th.get("ui_log") or []
        if ui_log:
            self._welcome_card.hide()
            for entry in ui_log:
                if entry.get("role") == "user":
                    self._insert_stream_widget(UserMessageCard(entry.get("text", ""), self._stream_host))
                else:
                    acard = AssistantMessageCard(self._config.model, self._stream_host)
                    acard.set_full_text(entry.get("text", ""))
                    self._insert_stream_widget(acard)

    def open_settings_dialog(self) -> None:
        dlg = AutoGISSettingsDialog(self._config, self.window())
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.exec()

    def _on_settings_saved(self) -> None:
        self._sync_header_status()
        self._sync_model_combo()
        self._sync_mode_combo()


class AutoGISDockWidget(QDockWidget):
    """Right-side dockable studio container for AutoGIS inside QGIS."""

    def __init__(self, iface, config: AutoGISConfig, parent=None) -> None:
        super().__init__("AutoGIS Studio", parent)
        self.setObjectName("AutoGISStudioDock")
        self.setWindowIcon(create_autogis_icon())
        self.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.panel = AutoGISPanel(iface, config, self)
        self.setWidget(self.panel)
        self.setMinimumWidth(390)
