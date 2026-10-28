from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.agent_engine import AutoGISEngine
from ..core.config import AutoGISConfig, ThreadHistoryStore
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
        self.setPlaceholderText("Ask AutoGIS...")
        self.setFixedHeight(54)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                event.accept()
                self.send_triggered.emit()
                return
        super().keyPressEvent(event)


class AutoGISPanel(QWidget):
    """Clean, compact studio panel inside the AutoGIS dock widget."""

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
        self._pending_reasoning: str = ""
        self._tool_cards: dict[str, ToolExecutionCard] = {}
        self._attached_files: list[str] = []
        self._pinned_layers: list[str] = []
        self._is_running = False

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(50)
        self._scroll_timer.timeout.connect(self._do_scroll_to_bottom)

        self.setObjectName("AutoGISRoot")
        self.setAcceptDrops(True)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(get_studio_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._stream_host = QWidget(self._scroll)
        self._stream_host.setObjectName("AutoGISRoot")
        self._stream_layout = QVBoxLayout(self._stream_host)
        self._stream_layout.setContentsMargins(10, 10, 10, 10)
        self._stream_layout.setSpacing(8)

        self._welcome_card = WelcomeStarterCard(self._stream_host)
        self._welcome_card.prompt_selected.connect(self._send_quick_prompt)
        self._stream_layout.addWidget(self._welcome_card)

        self._status_banner = LiveStatusBanner(self._stream_host)
        self._stream_layout.addWidget(self._status_banner)
        self._stream_layout.addStretch(1)

        self._scroll.setWidget(self._stream_host)
        root.addWidget(self._scroll, 1)

        root.addWidget(self._build_composer())

        self._wire_engine()

    def _build_header(self) -> QFrame:
        hdr = QFrame(self)
        hdr.setObjectName("AutoGISHeader")
        hdr.setFixedHeight(42)

        row = QHBoxLayout(hdr)
        row.setContentsMargins(10, 4, 10, 4)
        row.setSpacing(6)

        self._hdr_logo = QLabel(hdr)
        self._hdr_logo.setPixmap(create_autogis_pixmap(24))
        self._hdr_logo.setFixedSize(24, 24)
        row.addWidget(self._hdr_logo)

        title = QLabel("AutoGIS", hdr)
        title.setStyleSheet("font-size: 13.5px; font-weight: 800; background: transparent;")
        row.addWidget(title)

        row.addStretch(1)

        new_btn = QPushButton("New", hdr)
        new_btn.setObjectName("AutoGISGhostBtn")
        new_btn.setToolTip("New Session")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(self.start_new_session)
        row.addWidget(new_btn)

        self._hist_btn = QPushButton("History", hdr)
        self._hist_btn.setObjectName("AutoGISGhostBtn")
        self._hist_btn.setToolTip("Session History")
        self._hist_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hist_btn.clicked.connect(self._show_history_menu)
        row.addWidget(self._hist_btn)

        cfg_btn = QPushButton("Settings", hdr)
        cfg_btn.setObjectName("AutoGISGhostBtn")
        cfg_btn.setToolTip("Settings")
        cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cfg_btn.clicked.connect(self.open_settings_dialog)
        row.addWidget(cfg_btn)

        return hdr

    def _build_composer(self) -> QWidget:
        host = QWidget(self)
        col = QVBoxLayout(host)
        col.setContentsMargins(10, 4, 10, 10)
        col.setSpacing(5)

        # Compact Attachment Bar (Zero emojis, no Data button)
        self._chips_row = QHBoxLayout()
        self._chips_row.setContentsMargins(0, 0, 0, 0)
        self._chips_row.setSpacing(4)

        pin_lyr_btn = QPushButton("+ Layer", host)
        pin_lyr_btn.setObjectName("AutoGISGhostBtn")
        pin_lyr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pin_lyr_btn.setToolTip("Pin active QGIS layer")
        pin_lyr_btn.clicked.connect(self._pin_active_layer)
        self._chips_row.addWidget(pin_lyr_btn)

        attach_btn = QPushButton("File / PDF", host)
        attach_btn.setObjectName("AutoGISGhostBtn")
        attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        attach_btn.setToolTip("Attach PDF, Excel, Word, CSV, Shapefile, GeoJSON, or Image")
        attach_btn.clicked.connect(self._attach_dataset_file)
        self._chips_row.addWidget(attach_btn)

        folder_btn = QPushButton("Folder", host)
        folder_btn.setObjectName("AutoGISGhostBtn")
        folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_btn.setToolTip("Attach Folder")
        folder_btn.clicked.connect(self._attach_folder)
        self._chips_row.addWidget(folder_btn)

        self._chips_row.addStretch(1)
        col.addLayout(self._chips_row)

        # Selected Chips Display Row (hidden when empty)
        self._chips_info_row = QWidget(host)
        ci_layout = QHBoxLayout(self._chips_info_row)
        ci_layout.setContentsMargins(2, 0, 2, 0)
        ci_layout.setSpacing(4)
        self._chips_label = QLabel("", self._chips_info_row)
        self._chips_label.setWordWrap(True)
        self._chips_label.setStyleSheet("font-size: 10.5px; color: #2563EB; font-weight: 600;")
        ci_layout.addWidget(self._chips_label, 1)

        self._clear_chips_btn = QPushButton("Clear", self._chips_info_row)
        self._clear_chips_btn.setObjectName("AutoGISGhostBtn")
        self._clear_chips_btn.clicked.connect(self._clear_chips)
        ci_layout.addWidget(self._clear_chips_btn)
        self._chips_info_row.hide()
        col.addWidget(self._chips_info_row)

        # Composer Frame
        box = QFrame(host)
        box.setObjectName("AutoGISComposerFrame")
        box_col = QVBoxLayout(box)
        box_col.setContentsMargins(8, 6, 8, 6)
        box_col.setSpacing(5)

        self._input = _PromptEdit(box)
        self._input.send_triggered.connect(self._on_send_clicked)
        box_col.addWidget(self._input)

        # Bottom Controls Row
        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(5)

        self._model_combo = QComboBox(box)
        self._model_combo.setObjectName("AutoGISCombo")
        self._model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._model_combo.setMinimumWidth(90)
        self._model_combo.setMaxVisibleItems(14)
        if self._model_combo.view() is not None:
            self._model_combo.view().setMinimumWidth(240)
        self._sync_model_combo()
        self._model_combo.activated.connect(self._on_quick_model_changed)
        ctrl.addWidget(self._model_combo, 1)

        self._mode_combo = QComboBox(box)
        self._mode_combo.setObjectName("AutoGISCombo")
        self._mode_combo.addItem("Auto", "autopilot")
        self._mode_combo.addItem("Ask", "ask_write")
        self._mode_combo.addItem("Chat", "chat_only")
        self._sync_mode_combo()
        self._mode_combo.currentIndexChanged.connect(self._on_quick_mode_changed)
        ctrl.addWidget(self._mode_combo)

        self._send_btn = QPushButton("Send", box)
        self._send_btn.setObjectName("AutoGISPrimaryBtn")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send_clicked)
        ctrl.addWidget(self._send_btn)

        self._stop_btn = QPushButton("Stop", box)
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

    def _sync_model_combo(self) -> None:
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        curr = self._config.model.strip()
        ordered = self._config.get_ordered_models()
        found = False
        for mid, mlabel in ordered:
            self._model_combo.addItem(mlabel, mid)
            if mid == curr:
                self._model_combo.setCurrentIndex(self._model_combo.count() - 1)
                found = True
        if not found and curr:
            short_lbl = curr.split("/")[-1] if "/" in curr else curr
            self._model_combo.insertItem(1, short_lbl, curr)
            self._model_combo.setCurrentIndex(1)
        elif not curr:
            self._model_combo.setCurrentIndex(0)
        self._model_combo.addItem("Custom Model ID...", "__custom__")
        self._model_combo.setToolTip(curr or "Select AI Model")
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
        if idx < 0:
            return
        mid = str(self._model_combo.itemData(idx) or "")
        if mid == "__custom__":
            text, ok = QInputDialog.getText(
                self,
                "Custom Model ID",
                "Enter Model ID (e.g. google/gemini-2.5-flash, gpt-4o-mini, deepseek-chat):",
                text=self._config.model,
            )
            if ok and text.strip():
                self._config.model = text.strip()
            self._sync_model_combo()
            return
        self._config.model = mid
        self._model_combo.setToolTip(mid or "Select AI Model")

    def _on_quick_mode_changed(self, idx: int) -> None:
        if idx >= 0:
            mode = self._mode_combo.itemData(idx)
            if mode:
                self._config.execution_mode = str(mode)

    def _insert_stream_widget(self, widget: QWidget) -> None:
        self._welcome_card.hide()
        idx = self._stream_layout.indexOf(self._status_banner)
        if idx < 0:
            idx = max(0, self._stream_layout.count() - 1)
        self._stream_layout.insertWidget(idx, widget)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        if not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def _do_scroll_to_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        if sb is not None:
            sb.setValue(sb.maximum())

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
            "Select Files or PDFs",
            "",
            "All Supported (*.pdf *.docx *.xlsx *.xls *.csv *.tsv *.txt *.md *.json *.geojson *.gpkg *.shp *.kml *.gml *.tif *.tiff *.dem *.laz *.las *.png *.jpg *.jpeg *.py *.sql);;All Files (*.*)",
        )
        for path in paths:
            if path and path not in self._attached_files:
                self._attached_files.append(path)
        self._refresh_chips_ui()

    def _attach_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", "")
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
                parts.append(f"[Folder] {base}")
            elif p.lower().endswith(".pdf"):
                parts.append(f"[PDF] {base}")
            else:
                parts.append(f"[File] {base}")
        self._chips_label.setText("  ".join(parts))
        self._chips_info_row.setVisible(bool(parts))

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
            text = "Analyze and summarize the attached file(s)."

        display_text = text
        if self._pinned_layers:
            display_text += "\nLayers: " + ", ".join(f"@{l}" for l in self._pinned_layers)
        if self._attached_files:
            display_text += "\nFiles: " + ", ".join(os.path.basename(f.rstrip("\\/")) for f in self._attached_files)

        user_card = UserMessageCard(display_text, self._stream_host)
        self._insert_stream_widget(user_card)

        attachments = list(self._attached_files)
        mentions = list(self._pinned_layers)
        self._input.clear()
        self._clear_chips()

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
        self._pending_reasoning = ""
        self._status_banner.start_status("Thinking...")
        self._scroll_to_bottom()

    def _on_status_updated(self, run_id: str, status_text: str) -> None:
        if status_text:
            self._status_banner.start_status(status_text)
        else:
            self._status_banner.stop_status()
        self._scroll_to_bottom()

    def _ensure_assistant_card(self) -> AssistantMessageCard:
        if self._active_assistant_card is None:
            self._active_assistant_card = AssistantMessageCard("", self._stream_host)
            if self._pending_reasoning:
                self._active_assistant_card.append_reasoning(self._pending_reasoning)
                self._pending_reasoning = ""
            self._insert_stream_widget(self._active_assistant_card)
        return self._active_assistant_card

    def _on_reasoning_chunk(self, run_id: str, chunk: str) -> None:
        if self._active_assistant_card is not None:
            self._active_assistant_card.append_reasoning(chunk)
        else:
            self._pending_reasoning += chunk

    def _on_token_chunk(self, run_id: str, chunk: str) -> None:
        card = self._ensure_assistant_card()
        card.append_text(chunk)
        self._scroll_to_bottom()

    def _on_assistant_step_done(self, run_id: str, step_text: str) -> None:
        if self._active_assistant_card is not None:
            self._active_assistant_card.flush_text()
        self._active_assistant_card = None
        self._pending_reasoning = ""

    def _on_tool_call_started(self, run_id: str, call_id: str, name: str, args: object) -> None:
        if self._active_assistant_card is not None:
            self._active_assistant_card.flush_text()
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
        if self._active_assistant_card is not None:
            self._active_assistant_card.flush_text()
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
        if self._active_assistant_card is not None:
            self._active_assistant_card.flush_text()
        self._active_assistant_card = None
        self._pending_reasoning = ""

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
        self._active_plan_card = None
        self._pending_reasoning = ""

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
            act = menu.addAction("No saved sessions")
            act.setEnabled(False)
        else:
            for th in threads[:20]:
                tid = th.get("id", "")
                title = th.get("title") or "Session"
                msg_count = len(th.get("ui_log") or [])
                if msg_count == 0 and tid == self._current_thread_id:
                    continue
                act = menu.addAction(title)
                act.triggered.connect(lambda _=False, t=tid: self._load_thread(t))
            menu.addSeparator()
            clear_act = menu.addAction("Clear History")
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
                    acard = AssistantMessageCard("", self._stream_host)
                    acard.set_full_text(entry.get("text", ""))
                    self._insert_stream_widget(acard)

    def open_settings_dialog(self) -> None:
        dlg = AutoGISSettingsDialog(self._config, self.window())
        dlg.settings_saved.connect(self._on_settings_saved)
        dlg.exec()

    def _on_settings_saved(self) -> None:
        self._hdr_logo.setPixmap(create_autogis_pixmap(24))
        self._sync_model_combo()
        self._sync_mode_combo()


class AutoGISDockWidget(QDockWidget):
    """Right-side dockable studio container for AutoGIS inside QGIS."""

    def __init__(self, iface, config: AutoGISConfig, parent=None) -> None:
        super().__init__("AutoGIS", parent)
        self.setObjectName("AutoGISStudioDock")
        self.setWindowIcon(create_autogis_icon())
        self.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.panel = AutoGISPanel(iface, config, self)
        self.setWidget(self.panel)
        self.setMinimumWidth(220)
