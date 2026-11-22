from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.config import PROVIDER_ENDPOINTS, PROVIDER_MODELS, PROVIDERS, AutoGISConfig
from ..core.gee_credentials import initialize_earth_engine, save_gee_config

from .theme import create_autogis_icon, create_autogis_pixmap, get_studio_stylesheet, set_custom_logo_path


class AutoGISSettingsDialog(QDialog):
    """Clean, unified Settings Dialog for AutoGIS with <2s thread-safe connection testing."""

    settings_saved = pyqtSignal()
    _test_result_signal = pyqtSignal(bool, str)
    _daemon_test_signal = pyqtSignal(bool, str)

    def __init__(self, config: AutoGISConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._test_result_signal.connect(self._on_test_done)
        self._daemon_test_signal.connect(self._on_daemon_test_done)

        # Local working copy of provider keys
        self._keys: dict[str, str] = {
            pid: self._config.get_provider_key(pid) for pid, _, _ in PROVIDERS
        }
        self._current_pid: str = self._config.active_provider

        self.setObjectName("AutoGISRoot")
        self.setWindowTitle("AutoGIS — Settings")
        self.setWindowIcon(create_autogis_icon())
        self.setMinimumSize(540, 560)
        self.resize(600, 680)
        self.setStyleSheet(get_studio_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # Clean Header
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        logo = QLabel(self)
        logo.setPixmap(create_autogis_pixmap(28))
        logo.setFixedSize(28, 28)
        hdr.addWidget(logo)

        title = QLabel("AutoGIS Settings", self)
        title.setStyleSheet("font-size: 14px; font-weight: 800;")
        hdr.addWidget(title)
        hdr.addStretch(1)
        root.addLayout(hdr)

        # Scroll area for clean responsive layout on all screen sizes
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("AutoGISScroll")

        card = QFrame(scroll)
        card.setObjectName("AutoGISCard")
        form = QFormLayout(card)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        # 1. Unified Provider Selector
        self._prov_combo = QComboBox(card)
        self._prov_combo.setObjectName("AutoGISCombo")
        self._prov_combo.setMinimumHeight(30)
        for pid, plabel, _ in PROVIDERS:
            self._prov_combo.addItem(plabel, pid)
            if pid == self._current_pid:
                self._prov_combo.setCurrentIndex(self._prov_combo.count() - 1)
        self._prov_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow(QLabel("<b>Primary AI:</b>"), self._prov_combo)

        # 2. Single Unified API Key Row + Show + Fast Test
        key_host = QWidget(card)
        key_row = QHBoxLayout(key_host)
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(6)

        self._key_edit = QLineEdit(key_host)
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setMinimumHeight(30)
        self._key_edit.setPlaceholderText("Paste API Key...")
        self._key_edit.setText(self._keys.get(self._current_pid, ""))
        self._key_edit.textEdited.connect(self._on_key_edited)
        key_row.addWidget(self._key_edit, 1)

        self._show_btn = QPushButton("Show", key_host)
        self._show_btn.setObjectName("AutoGISGhostBtn")
        self._show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._show_btn.clicked.connect(self._toggle_echo)
        key_row.addWidget(self._show_btn)

        self._test_btn = QPushButton("Test", key_host)
        self._test_btn.setObjectName("AutoGISGhostBtn")
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.clicked.connect(self._test_connection_fast)
        key_row.addWidget(self._test_btn)

        form.addRow(QLabel("<b>API Key:</b>"), key_host)

        # Status Feedback Label
        self._status_lbl = QLabel("", card)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("font-size: 11px; color: #64748B;")
        form.addRow(QLabel(""), self._status_lbl)

        # 3. Default Model Selector (Synced with Provider & Editable)
        self._model_combo = QComboBox(card)
        self._model_combo.setObjectName("AutoGISCombo")
        self._model_combo.setEditable(True)
        self._model_combo.setMinimumHeight(30)
        if self._model_combo.lineEdit():
            self._model_combo.lineEdit().setPlaceholderText("Select or type Model ID...")
        self._populate_provider_models(self._current_pid, self._config.model)
        form.addRow(QLabel("<b>AI Model:</b>"), self._model_combo)

        # 4. Xerj AI — Dedicated Document Intelligence & Local Corpus Engine
        xerj_hdr = QLabel("<b>Xerj AI — Spatial & Document Intelligence</b>", card)
        form.addRow(xerj_hdr)

        # Xerj Dedicated Key (can be used even if primary AI is Claude/Gemini/OpenAI)
        xerj_key_host = QWidget(card)
        xerj_key_row = QHBoxLayout(xerj_key_host)
        xerj_key_row.setContentsMargins(0, 0, 0, 0)
        xerj_key_row.setSpacing(6)
        self._xerj_cloud_key_edit = QLineEdit(self._keys.get("xerj", "") or self._config.xerj_key, xerj_key_host)
        self._xerj_cloud_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._xerj_cloud_key_edit.setPlaceholderText("Xerj AI Key (for xerj-reader-1 & Spatial Document Router)")
        self._xerj_cloud_key_edit.textEdited.connect(self._on_xerj_cloud_key_edited)
        xerj_key_row.addWidget(self._xerj_cloud_key_edit, 1)

        self._xerj_cloud_show_btn = QPushButton("Show", xerj_key_host)
        self._xerj_cloud_show_btn.setObjectName("AutoGISGhostBtn")
        self._xerj_cloud_show_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._xerj_cloud_show_btn.clicked.connect(self._toggle_xerj_cloud_echo)
        xerj_key_row.addWidget(self._xerj_cloud_show_btn)
        form.addRow(QLabel("Xerj Cloud Key:"), xerj_key_host)

        # Xerj Local Daemon (Elasticsearch / REST compatible at 127.0.0.1:9200)
        xerj_daemon_host = QWidget(card)
        xerj_daemon_row = QHBoxLayout(xerj_daemon_host)
        xerj_daemon_row.setContentsMargins(0, 0, 0, 0)
        xerj_daemon_row.setSpacing(6)
        self._xerj_edit = QLineEdit(self._config.xerj_url or "http://127.0.0.1:9200", xerj_daemon_host)
        self._xerj_edit.setPlaceholderText("http://127.0.0.1:9200")
        xerj_daemon_row.addWidget(self._xerj_edit, 1)

        self._xerj_test_btn = QPushButton("Test Daemon", xerj_daemon_host)
        self._xerj_test_btn.setObjectName("AutoGISGhostBtn")
        self._xerj_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._xerj_test_btn.clicked.connect(self._test_xerj_daemon)
        xerj_daemon_row.addWidget(self._xerj_test_btn)
        form.addRow(QLabel("Xerj Daemon URL:"), xerj_daemon_host)

        self._xerj_daemon_status_lbl = QLabel(
            "Local Daemon or Built-in hybrid corpus for GIS codebase & specs", card
        )
        self._xerj_daemon_status_lbl.setWordWrap(True)
        self._xerj_daemon_status_lbl.setStyleSheet("font-size: 10px; color: #64748B;")
        form.addRow(QLabel(""), self._xerj_daemon_status_lbl)

        # 5. Earth Engine configuration (local QGIS profile only)
        gee_title = QLabel("<b>Google Earth Engine</b>", card)
        form.addRow(gee_title)

        self._gee_project_edit = QLineEdit(self._config.gee_project_id, card)
        self._gee_project_edit.setPlaceholderText("Google Cloud Project ID")
        form.addRow(QLabel("Cloud Project ID:"), self._gee_project_edit)

        self._gee_account_edit = QLineEdit(self._config.gee_service_account, card)
        self._gee_account_edit.setPlaceholderText("service-account@project.iam.gserviceaccount.com (optional)")
        form.addRow(QLabel("Service account:"), self._gee_account_edit)

        gee_key_host = QWidget(card)
        gee_key_row = QHBoxLayout(gee_key_host)
        gee_key_row.setContentsMargins(0, 0, 0, 0)
        self._gee_key_edit = QLineEdit(self._config.gee_key_file, gee_key_host)
        self._gee_key_edit.setPlaceholderText("Optional service-account JSON key file path")
        gee_key_row.addWidget(self._gee_key_edit, 1)
        gee_browse = QPushButton("Browse", gee_key_host)
        gee_browse.setObjectName("AutoGISGhostBtn")
        gee_browse.clicked.connect(self._browse_gee_key)
        gee_key_row.addWidget(gee_browse)
        gee_test = QPushButton("Test / Initialize", gee_key_host)
        gee_test.setObjectName("AutoGISGhostBtn")
        gee_test.clicked.connect(self._test_gee)
        gee_key_row.addWidget(gee_test)
        form.addRow(QLabel("Service-account key:"), gee_key_host)

        gee_note = QLabel("Credentials stay in your local QGIS profile. Never upload the JSON key to GitHub.", card)
        gee_note.setWordWrap(True)
        gee_note.setStyleSheet("font-size: 10px; color: #64748B;")
        form.addRow(QLabel(""), gee_note)

        # 6. Geospatial Agentic Services (GAS 1.0.0)
        gas_hdr = QLabel("<b>Geospatial Agentic Services (GAS)</b>", card)
        form.addRow(gas_hdr)

        gas_host = QWidget(card)
        gas_row = QHBoxLayout(gas_host)
        gas_row.setContentsMargins(0, 0, 0, 0)
        gas_row.setSpacing(6)
        self._gas_server_edit = QLineEdit(self._config.gas_server_url, gas_host)
        self._gas_server_edit.setPlaceholderText("https://www.geospatial-agentic-services.online")
        gas_row.addWidget(self._gas_server_edit, 1)
        form.addRow(QLabel("GAS Server:"), gas_host)

        self._gas_key_edit = QLineEdit(self._config.gibd_api_key or self._config.gas_api_key, card)
        self._gas_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._gas_key_edit.setPlaceholderText("Optional GIBD / GAS API Key (defaults to active AI key)")
        form.addRow(QLabel("GAS / GIBD Key:"), self._gas_key_edit)

        # 7. Custom Logo (Optional)
        logo_host = QWidget(card)
        logo_row = QHBoxLayout(logo_host)
        logo_row.setContentsMargins(0, 0, 0, 0)
        logo_row.setSpacing(6)
        self._logo_edit = QLineEdit(logo_host)
        self._logo_edit.setPlaceholderText("Default Icon (or upload custom PNG/SVG)")
        self._logo_edit.setText(self._config.custom_logo_path)
        logo_row.addWidget(self._logo_edit, 1)

        up_btn = QPushButton("Upload", logo_host)
        up_btn.setObjectName("AutoGISGhostBtn")
        up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        up_btn.clicked.connect(self._browse_logo)
        logo_row.addWidget(up_btn)
        form.addRow(QLabel("<b>Custom Logo:</b>"), logo_host)

        # 8. Custom Instructions (Optional)
        self._custom_edit = QPlainTextEdit(card)
        self._custom_edit.setPlaceholderText("Optional instructions (e.g. 'Reply in Hinglish')...")
        self._custom_edit.setPlainText(self._config.custom_instructions)
        self._custom_edit.setFixedHeight(54)
        form.addRow(QLabel("<b>Instructions:</b>"), self._custom_edit)

        scroll.setWidget(card)
        root.addWidget(scroll, 1)

        # Footer Buttons
        footer = QHBoxLayout()
        reset_btn = QPushButton("Clear All", self)
        reset_btn.setObjectName("AutoGISGhostBtn")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._clear_all)
        footer.addWidget(reset_btn)

        footer.addStretch(1)

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setObjectName("AutoGISGhostBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        save_btn = QPushButton("Save", self)
        save_btn.setObjectName("AutoGISPrimaryBtn")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_and_close)
        footer.addWidget(save_btn)

        root.addLayout(footer)

    def _populate_provider_models(self, pid: str, selected_model: str = "") -> None:
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItem("Select Model", "")
        models = PROVIDER_MODELS.get(pid, PROVIDER_MODELS["openrouter"])
        matched_idx = 0
        for mid, mlabel in models:
            self._model_combo.addItem(f"{mlabel} ({mid})", mid)
            if selected_model and (mid == selected_model or mid.split("/")[-1] == selected_model):
                matched_idx = self._model_combo.count() - 1
        if selected_model and matched_idx == 0:
            self._model_combo.addItem(selected_model, selected_model)
            matched_idx = self._model_combo.count() - 1
        self._model_combo.setCurrentIndex(matched_idx)
        if matched_idx == 0 and not selected_model and self._model_combo.lineEdit():
            self._model_combo.lineEdit().clear()
        self._model_combo.blockSignals(False)

    def _on_provider_changed(self, idx: int) -> None:
        if idx < 0:
            return
        self._keys[self._current_pid] = self._key_edit.text().strip()
        new_pid = str(self._prov_combo.itemData(idx) or "gemini")
        self._current_pid = new_pid

        # Sync key into main edit
        key_val = self._keys.get(new_pid, "")
        if new_pid == "xerj" and not key_val:
            key_val = self._xerj_cloud_key_edit.text().strip()
        self._key_edit.setText(key_val)
        self._populate_provider_models(new_pid, "")
        self._status_lbl.setText("")

    def _on_key_edited(self, text: str) -> None:
        self._keys[self._current_pid] = text.strip()
        if self._current_pid == "xerj":
            self._xerj_cloud_key_edit.setText(text.strip())

    def _on_xerj_cloud_key_edited(self, text: str) -> None:
        self._keys["xerj"] = text.strip()
        if self._current_pid == "xerj":
            self._key_edit.setText(text.strip())

    def _toggle_echo(self) -> None:
        is_pw = self._key_edit.echoMode() == QLineEdit.EchoMode.Password
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Normal if is_pw else QLineEdit.EchoMode.Password)
        self._show_btn.setText("Hide" if is_pw else "Show")

    def _toggle_xerj_cloud_echo(self) -> None:
        is_pw = self._xerj_cloud_key_edit.echoMode() == QLineEdit.EchoMode.Password
        self._xerj_cloud_key_edit.setEchoMode(QLineEdit.EchoMode.Normal if is_pw else QLineEdit.EchoMode.Password)
        self._xerj_cloud_show_btn.setText("Hide" if is_pw else "Show")

    def _test_gee(self) -> None:
        try:
            save_gee_config(
                self._gee_project_edit.text().strip(),
                self._gee_account_edit.text().strip(),
                self._gee_key_edit.text().strip(),
            )
            ok, message = initialize_earth_engine()
            self._status_lbl.setStyleSheet(
                "color: #16A34A; font-weight: 600;" if ok
                else "color: #DC2626; font-weight: 600;"
            )
            self._status_lbl.setText(message)
        except Exception as exc:
            self._status_lbl.setStyleSheet("color: #DC2626; font-weight: 600;")
            self._status_lbl.setText(f"Earth Engine configuration error: {exc}")

    def _browse_gee_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Earth Engine Service-account JSON", "",
            "JSON files (*.json);;All Files (*.*)",
        )
        if path:
            self._gee_key_edit.setText(path)

    def _browse_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Logo Icon",
            "",
            "Images (*.png *.svg *.jpg *.jpeg *.webp);;All Files (*.*)",
        )
        if path:
            self._logo_edit.setText(path)

    def _clear_all(self) -> None:
        for pid in list(self._keys.keys()):
            self._keys[pid] = ""
        self._key_edit.clear()
        self._xerj_cloud_key_edit.clear()
        self._logo_edit.clear()
        self._custom_edit.clear()
        self._config.reset_all()
        self._populate_provider_models(self._current_pid, "")
        self._status_lbl.setStyleSheet("color: #2563EB; font-weight: 600;")
        self._status_lbl.setText("Cleared all saved keys and model selection.")

    def _test_xerj_daemon(self) -> None:
        """Fast non-blocking test of local Xerj daemon on 127.0.0.1:9200."""
        url = (self._xerj_edit.text().strip() or "http://127.0.0.1:9200").rstrip("/")
        self._xerj_daemon_status_lbl.setStyleSheet("color: #2563EB;")
        self._xerj_daemon_status_lbl.setText("Testing local daemon...")
        self._xerj_test_btn.setEnabled(False)

        def _worker() -> None:
            t0 = time.monotonic()
            try:
                test_url = f"{url}/"
                req = urllib.request.Request(test_url, headers={"User-Agent": "AutoGIS/1.0"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:  # nosec B310
                    _ = resp.read(256)
                ms = int((time.monotonic() - t0) * 1000)
                self._daemon_test_signal.emit(True, f"Daemon Online ({ms}ms) — Local AST index active")
            except Exception:
                self._daemon_test_signal.emit(False, "Daemon Offline — Built-in hybrid spatial corpus active")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_daemon_test_done(self, ok: bool, msg: str) -> None:
        self._xerj_test_btn.setEnabled(True)
        self._xerj_daemon_status_lbl.setStyleSheet(
            "color: #16A34A; font-weight: 600;" if ok else "color: #64748B; font-weight: 500;"
        )
        self._xerj_daemon_status_lbl.setText(msg)

    def _test_connection_fast(self) -> None:
        """Ultra-fast (<2.5s) thread-safe connection check that never blocks or crashes QGIS."""
        key = self._key_edit.text().strip()
        pid = self._current_pid

        # Auto-detect if user pasted a specific key format
        if key.startswith("sk-or-"):
            pid = "openrouter"
        elif key.startswith("sk-ant-"):
            pid = "anthropic"
        elif key.startswith("AQ.") or key.startswith("AIza"):
            pid = "gemini"
        elif key.startswith("sk-") and not (key.startswith("sk-or-") or key.startswith("sk-ant-")):
            if pid not in ("openai", "deepseek"):
                pid = "openai"

        if not key and pid != "ollama":
            self._status_lbl.setStyleSheet("color: #DC2626; font-weight: 600;")
            self._status_lbl.setText("Please paste an API Key first.")
            return

        base_url = PROVIDER_ENDPOINTS.get(pid, "https://openrouter.ai/api/v1")

        self._test_btn.setEnabled(False)
        self._status_lbl.setStyleSheet("color: #2563EB;")
        self._status_lbl.setText("Testing connection...")

        def _worker() -> None:
            t0 = time.monotonic()
            try:
                if pid == "openrouter" or key.startswith("sk-or-"):
                    req = urllib.request.Request(
                        "https://openrouter.ai/api/v1/auth/key",
                        headers={"Authorization": f"Bearer {key}", "User-Agent": "AutoGIS/1.0"},
                    )
                elif pid == "anthropic" or key.startswith("sk-ant-"):
                    req = urllib.request.Request(
                        "https://api.anthropic.com/v1/models",
                        headers={
                            "x-api-key": key,
                            "anthropic-version": "2023-06-01",
                            "User-Agent": "AutoGIS/1.0",
                        },
                    )
                elif pid == "gemini" or key.startswith("AQ.") or key.startswith("AIza"):
                    req = urllib.request.Request(
                        "https://generativelanguage.googleapis.com/v1beta/openai/models",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "User-Agent": "AutoGIS/1.0",
                        },
                    )
                elif pid == "ollama":
                    req = urllib.request.Request(
                        "http://127.0.0.1:11434/api/tags",
                        headers={"User-Agent": "AutoGIS/1.0"},
                    )
                elif pid == "xerj":
                    req = urllib.request.Request(
                        f"{base_url}/models",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "x-api-key": key,
                            "User-Agent": "AutoGIS/1.0",
                        },
                    )
                else:
                    req = urllib.request.Request(
                        f"{base_url}/models",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "User-Agent": "AutoGIS/1.0",
                        },
                    )

                with urllib.request.urlopen(req, timeout=3.5) as resp:  # nosec B310
                    _ = resp.read(512)
                ms = int((time.monotonic() - t0) * 1000)
                self._test_result_signal.emit(True, f"Connected ({ms}ms) [{pid.upper()}]")
            except urllib.error.HTTPError as he:
                if he.code in (401, 403):
                    self._test_result_signal.emit(False, f"Invalid API Key (HTTP {he.code})")
                elif he.code == 404 and pid == "xerj":
                    ms = int((time.monotonic() - t0) * 1000)
                    self._test_result_signal.emit(True, f"Connected ({ms}ms) [Xerj AI Endpoint Live]")
                else:
                    self._test_result_signal.emit(False, f"HTTP Error {he.code}")
            except Exception as exc:
                self._test_result_signal.emit(False, f"Connection Error: {str(exc)[:60]}")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_test_done(self, ok: bool, msg: str) -> None:
        self._test_btn.setEnabled(True)
        self._status_lbl.setStyleSheet("color: #16A34A; font-weight: 600;" if ok else "color: #DC2626; font-weight: 600;")
        self._status_lbl.setText(msg)

    def _save_and_close(self) -> None:
        self._keys[self._current_pid] = self._key_edit.text().strip()
        self._config.active_provider = self._current_pid

        # Sync Xerj cloud key
        x_key = self._xerj_cloud_key_edit.text().strip()
        if x_key:
            self._keys["xerj"] = x_key
            self._config.xerj_key = x_key

        for pid, k_val in self._keys.items():
            self._config.set_provider_key(pid, k_val)

        idx = self._model_combo.currentIndex()
        chosen_model = ""
        if idx >= 0:
            data_val = self._model_combo.itemData(idx)
            if data_val is not None and self._model_combo.currentText() == self._model_combo.itemText(idx):
                chosen_model = str(data_val).strip()
            else:
                raw_txt = self._model_combo.currentText().strip()
                if "(" in raw_txt and raw_txt.endswith(")"):
                    chosen_model = raw_txt.rsplit("(", 1)[-1][:-1].strip()
                elif raw_txt != "Select Model":
                    chosen_model = raw_txt
        if chosen_model:
            self._config.model = chosen_model

        try:
            save_gee_config(
                self._gee_project_edit.text().strip(),
                self._gee_account_edit.text().strip(),
                self._gee_key_edit.text().strip(),
            )
        except Exception as exc:
            self._status_lbl.setStyleSheet("color: #DC2626; font-weight: 600;")
            self._status_lbl.setText(f"Earth Engine configuration error: {exc}")
            return

        self._config.xerj_url = self._xerj_edit.text().strip() or "http://127.0.0.1:9200"
        self._config.gas_server_url = (
            self._gas_server_edit.text().strip() or "https://www.geospatial-agentic-services.online"
        )
        gas_key_val = self._gas_key_edit.text().strip()
        self._config.gibd_api_key = gas_key_val
        self._config.gas_api_key = gas_key_val
        self._config.custom_logo_path = self._logo_edit.text().strip()
        set_custom_logo_path(self._config.custom_logo_path)
        self._config.custom_instructions = self._custom_edit.toPlainText().strip()
        self.settings_saved.emit()
        self.accept()
