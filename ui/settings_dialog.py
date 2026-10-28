from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.config import CURATED_MODELS, DEFAULT_BASE_URL, AutoGISConfig
from .theme import create_autogis_icon, create_autogis_pixmap, get_studio_stylesheet, set_custom_logo_path


class AutoGISSettingsDialog(QDialog):
    """Comprehensive OpenRouter & Agent Behavior configuration dialog for AutoGIS."""

    settings_saved = pyqtSignal()

    def __init__(self, config: AutoGISConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setObjectName("AutoGISRoot")
        self.setWindowTitle("AutoGIS Studio — AI & Agent Settings")
        self.setWindowIcon(create_autogis_icon())
        self.setMinimumSize(620, 560)
        self.setStyleSheet(get_studio_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # Header Banner
        hdr = QHBoxLayout()
        hdr.setSpacing(12)
        logo = QLabel(self)
        logo.setPixmap(create_autogis_pixmap(38))
        logo.setFixedSize(38, 38)
        hdr.addWidget(logo)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("AutoGIS Studio Configuration", self)
        title.setStyleSheet("font-size: 16px; font-weight: 800;")
        title_col.addWidget(title)
        sub = QLabel("Configure AI Provider Keys, Models, Logo & Autonomous Agent Preferences", self)
        sub.setStyleSheet("font-size: 11.5px; color: #64748B;")
        title_col.addWidget(sub)
        hdr.addLayout(title_col, 1)
        root.addLayout(hdr)

        # Form Card
        card = QFrame(self)
        card.setObjectName("AutoGISCard")
        form = QFormLayout(card)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)

        # 1. OpenRouter API Key Row
        key_host = QWidget(card)
        key_row = QHBoxLayout(key_host)
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(6)
        self._key_edit = QLineEdit(key_host)
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("sk-or-v1-... (Connects Free Models + Claude + Gemini + ChatGPT)")
        self._key_edit.setText(self._config.api_key)
        self._key_edit.setMinimumHeight(28)
        key_row.addWidget(self._key_edit, 1)

        self._show_key_btn = QPushButton("Show", key_host)
        self._show_key_btn.setObjectName("AutoGISGhostBtn")
        self._show_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._show_key_btn.clicked.connect(self._toggle_key_echo)
        key_row.addWidget(self._show_key_btn)
        form.addRow(QLabel("<b>OpenRouter Key:</b>"), key_host)

        # 1b. Optional Direct Provider Keys (Gemini / ChatGPT / Claude / DeepSeek)
        direct_host = QWidget(card)
        direct_col = QVBoxLayout(direct_host)
        direct_col.setContentsMargins(0, 0, 0, 0)
        direct_col.setSpacing(5)

        row_a = QHBoxLayout()
        row_a.setSpacing(6)
        self._gemini_edit = QLineEdit(direct_host)
        self._gemini_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._gemini_edit.setPlaceholderText("Gemini Direct Key (AIza...) — Optional")
        self._gemini_edit.setText(self._config.gemini_key)
        row_a.addWidget(self._gemini_edit, 1)

        self._openai_edit = QLineEdit(direct_host)
        self._openai_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._openai_edit.setPlaceholderText("OpenAI ChatGPT Key (sk-...) — Optional")
        self._openai_edit.setText(self._config.openai_key)
        row_a.addWidget(self._openai_edit, 1)
        direct_col.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.setSpacing(6)
        self._anthropic_edit = QLineEdit(direct_host)
        self._anthropic_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._anthropic_edit.setPlaceholderText("Anthropic Claude Key (sk-ant-...) — Optional")
        self._anthropic_edit.setText(self._config.anthropic_key)
        row_b.addWidget(self._anthropic_edit, 1)

        self._deepseek_edit = QLineEdit(direct_host)
        self._deepseek_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._deepseek_edit.setPlaceholderText("DeepSeek Direct Key (sk-...) — Optional")
        self._deepseek_edit.setText(self._config.deepseek_key)
        row_b.addWidget(self._deepseek_edit, 1)
        direct_col.addLayout(row_b)

        form.addRow(QLabel("<b>Direct Keys:</b>"), direct_host)

        # 2. Model Row + Live Free Model Fetcher
        model_host = QWidget(card)
        model_col = QVBoxLayout(model_host)
        model_col.setContentsMargins(0, 0, 0, 0)
        model_col.setSpacing(5)

        model_top = QHBoxLayout()
        model_top.setSpacing(6)
        self._model_combo = QComboBox(model_host)
        self._model_combo.setObjectName("AutoGISCombo")
        self._model_combo.setEditable(True)
        self._model_combo.setMinimumHeight(30)
        self._populate_models(CURATED_MODELS, self._config.model)
        model_top.addWidget(self._model_combo, 1)

        self._fetch_models_btn = QPushButton("🔄 Load Live Free Models", model_host)
        self._fetch_models_btn.setObjectName("AutoGISGhostBtn")
        self._fetch_models_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fetch_models_btn.clicked.connect(self._fetch_live_free_models)
        model_top.addWidget(self._fetch_models_btn)
        model_col.addLayout(model_top)

        model_hint = QLabel("Pick any preset above, click 'Load Live Free Models', or type any OpenRouter model ID.", model_host)
        model_hint.setStyleSheet("font-size: 10.5px; color: #64748B;")
        model_col.addWidget(model_hint)
        form.addRow(QLabel("<b>AI Model:</b>"), model_host)

        # 3. API Base URL
        self._url_edit = QLineEdit(card)
        self._url_edit.setText(self._config.base_url)
        self._url_edit.setPlaceholderText(DEFAULT_BASE_URL)
        self._url_edit.setMinimumHeight(28)
        form.addRow(QLabel("<b>API Endpoint:</b>"), self._url_edit)

        # 4. Execution Mode
        self._mode_combo = QComboBox(card)
        self._mode_combo.setObjectName("AutoGISCombo")
        self._mode_combo.setMinimumHeight(28)
        modes = [
            ("autopilot", "⚡ Autopilot — Execute Read & Write GIS Tools Automatically"),
            ("ask_write", "🛡️ Careful — Auto-Run Read Tools, Ask Approval Before Write Tools"),
            ("chat_only", "💬 Chat Only — Answer Questions & Generate Code Without Running Tools"),
        ]
        curr_mode = self._config.execution_mode
        for mid, mlabel in modes:
            self._mode_combo.addItem(mlabel, mid)
            if mid == curr_mode:
                self._mode_combo.setCurrentIndex(self._mode_combo.count() - 1)
        form.addRow(QLabel("<b>Agent Mode:</b>"), self._mode_combo)

        # 5. Max Tokens & Free Fallback
        opts_host = QWidget(card)
        opts_row = QHBoxLayout(opts_host)
        opts_row.setContentsMargins(0, 0, 0, 0)
        opts_row.setSpacing(14)

        self._fallback_chk = QCheckBox("Auto-switch to Free Model if paid credits run out (HTTP 402)", opts_host)
        self._fallback_chk.setChecked(self._config.auto_fallback_free)
        opts_row.addWidget(self._fallback_chk, 1)

        opts_row.addWidget(QLabel("Max Tokens:"))
        self._tokens_spin = QSpinBox(opts_host)
        self._tokens_spin.setRange(256, 32768)
        self._tokens_spin.setSingleStep(512)
        self._tokens_spin.setValue(self._config.max_tokens)
        opts_row.addWidget(self._tokens_spin)
        form.addRow(QLabel("<b>Safeguards:</b>"), opts_host)

        # 6. Custom Logo Upload Row
        logo_host = QWidget(card)
        logo_row = QHBoxLayout(logo_host)
        logo_row.setContentsMargins(0, 0, 0, 0)
        logo_row.setSpacing(6)
        self._logo_edit = QLineEdit(logo_host)
        self._logo_edit.setPlaceholderText("Default Light Cartographic Emblem (or browse your own PNG/SVG)")
        self._logo_edit.setText(self._config.custom_logo_path)
        logo_row.addWidget(self._logo_edit, 1)

        browse_logo_btn = QPushButton("🖼️ Upload Logo...", logo_host)
        browse_logo_btn.setObjectName("AutoGISGhostBtn")
        browse_logo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_logo_btn.clicked.connect(self._browse_custom_logo)
        logo_row.addWidget(browse_logo_btn)

        reset_logo_btn = QPushButton("Default", logo_host)
        reset_logo_btn.setObjectName("AutoGISGhostBtn")
        reset_logo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_logo_btn.clicked.connect(lambda: self._logo_edit.setText(""))
        logo_row.addWidget(reset_logo_btn)
        form.addRow(QLabel("<b>Studio Logo:</b>"), logo_host)

        # 7. Custom Instructions
        self._custom_edit = QPlainTextEdit(card)
        self._custom_edit.setPlaceholderText(
            "Optional custom instructions (e.g. 'Reply in Hinglish', 'Always use EPSG:32643 for metric calculations', etc.)"
        )
        self._custom_edit.setPlainText(self._config.custom_instructions)
        self._custom_edit.setFixedHeight(65)
        form.addRow(QLabel("<b>Custom Instructions:</b>"), self._custom_edit)

        # 8. Test Connection Row
        test_host = QWidget(card)
        test_row = QHBoxLayout(test_host)
        test_row.setContentsMargins(0, 0, 0, 0)
        test_row.setSpacing(10)

        self._test_btn = QPushButton("⚡ Test Connection", test_host)
        self._test_btn.setObjectName("AutoGISGhostBtn")
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_btn)

        self._status_lbl = QLabel("", test_host)
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("font-size: 11px;")
        test_row.addWidget(self._status_lbl, 1)
        form.addRow(QLabel("<b>Verify:</b>"), test_host)

        root.addWidget(card, 1)

        # Bottom Dialog Buttons
        footer = QHBoxLayout()
        reset_all_btn = QPushButton("🧹 Clear All Keys & Model", self)
        reset_all_btn.setObjectName("AutoGISGhostBtn")
        reset_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_all_btn.clicked.connect(self._reset_all_fields)
        footer.addWidget(reset_all_btn)

        footer.addStretch(1)

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setObjectName("AutoGISGhostBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        save_btn = QPushButton("✓ Save & Apply Settings", self)
        save_btn.setObjectName("AutoGISPrimaryBtn")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_and_close)
        footer.addWidget(save_btn)

        root.addLayout(footer)

    def _populate_models(self, models: list[tuple[str, str]], selected_id: str) -> None:
        self._model_combo.clear()
        found = False
        for mid, mlabel in models:
            display = mlabel if not mid else f"{mlabel}  [{mid}]"
            self._model_combo.addItem(display, mid)
            if mid == selected_id:
                self._model_combo.setCurrentIndex(self._model_combo.count() - 1)
                found = True
        if not found and selected_id:
            self._model_combo.addItem(selected_id, selected_id)
            self._model_combo.setCurrentIndex(self._model_combo.count() - 1)
        elif not selected_id:
            self._model_combo.setCurrentIndex(0)

    def _selected_model_id(self) -> str:
        idx = self._model_combo.currentIndex()
        text = self._model_combo.currentText().strip()
        if text.startswith("— Select"):
            return ""
        if idx >= 0:
            data = self._model_combo.itemData(idx)
            if data is not None and (text.endswith(f"[{data}]") or text == data or data == ""):
                return str(data)
        if "[" in text and text.endswith("]"):
            return text.rsplit("[", 1)[-1][:-1].strip()
        return text

    def _browse_custom_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Custom Logo Icon (PNG / SVG / JPG)",
            "",
            "Images (*.png *.svg *.jpg *.jpeg *.webp);;All Files (*.*)",
        )
        if path:
            self._logo_edit.setText(path)

    def _reset_all_fields(self) -> None:
        self._key_edit.clear()
        self._gemini_edit.clear()
        self._openai_edit.clear()
        self._anthropic_edit.clear()
        self._deepseek_edit.clear()
        self._logo_edit.clear()
        self._custom_edit.clear()
        self._model_combo.setCurrentIndex(0)
        self._status_lbl.setStyleSheet("color: #2563EB; font-weight: 600;")
        self._status_lbl.setText("Cleared all fields. Click 'Save & Apply Settings' to confirm.")

    def _toggle_key_echo(self) -> None:
        new_mode = (
            QLineEdit.EchoMode.Normal
            if self._key_edit.echoMode() == QLineEdit.EchoMode.Password
            else QLineEdit.EchoMode.Password
        )
        for edit in (self._key_edit, self._gemini_edit, self._openai_edit, self._anthropic_edit, self._deepseek_edit):
            edit.setEchoMode(new_mode)
        self._show_key_btn.setText("Hide" if new_mode == QLineEdit.EchoMode.Normal else "Show")

    def _fetch_live_free_models(self) -> None:
        self._fetch_models_btn.setEnabled(False)
        self._fetch_models_btn.setText("Loading...")
        base_url = (self._url_edit.text().strip() or DEFAULT_BASE_URL).rstrip("/")

        def _worker() -> None:
            try:
                req = urllib.request.Request(f"{base_url}/models", headers={"User-Agent": "AutoGIS/2.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                items = data.get("data") or []
                free_list: list[tuple[str, str]] = list(CURATED_MODELS)
                seen = {m[0] for m in free_list}
                for m in items:
                    mid = str(m.get("id") or "")
                    name = str(m.get("name") or mid)
                    if mid.endswith(":free") and mid not in seen:
                        free_list.append((mid, f"🎁 [FREE] {name}"))
                        seen.add(mid)
                QTimer.singleShot(0, lambda: self._on_models_fetched(free_list, f"✓ Loaded {len(free_list)} models"))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._on_models_fetched(None, f"⚠️ Could not fetch models: {exc}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_models_fetched(self, models: list[tuple[str, str]] | None, msg: str) -> None:
        self._fetch_models_btn.setEnabled(True)
        self._fetch_models_btn.setText("🔄 Load Live Free Models")
        if models:
            curr = self._selected_model_id()
            self._populate_models(models, curr)
            self._status_lbl.setStyleSheet("color: #16A34A; font-weight: 600;")
        else:
            self._status_lbl.setStyleSheet("color: #DC2626; font-weight: 600;")
        self._status_lbl.setText(msg)

    def _test_connection(self) -> None:
        key = self._key_edit.text().strip()
        if not key:
            self._status_lbl.setStyleSheet("color: #DC2626; font-weight: 600;")
            self._status_lbl.setText("❌ Please enter an OpenRouter API Key first.")
            return

        base_url = (self._url_edit.text().strip() or DEFAULT_BASE_URL).rstrip("/")
        model = self._selected_model_id()
        self._test_btn.setEnabled(False)
        self._status_lbl.setStyleSheet("color: #0284C7;")
        self._status_lbl.setText(f"Testing {model}...")

        def _worker() -> None:
            t0 = time.monotonic()
            try:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "Say OK"}],
                    "max_tokens": 16,
                }
                req = urllib.request.Request(
                    f"{base_url}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://qgis.org",
                        "X-Title": "AutoGIS Test",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    _ = json.loads(resp.read().decode("utf-8"))
                ms = int((time.monotonic() - t0) * 1000)
                QTimer.singleShot(0, lambda: self._on_test_done(True, f"✅ Connected! ({ms}ms with {model.split('/')[-1]})"))
            except urllib.error.HTTPError as he:
                try:
                    err = json.loads(he.read().decode("utf-8")).get("error", {}).get("message", str(he))
                except Exception:
                    err = f"HTTP {he.code}: {he.reason}"
                QTimer.singleShot(0, lambda: self._on_test_done(False, f"❌ {err}"))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._on_test_done(False, f"❌ {exc}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_test_done(self, ok: bool, msg: str) -> None:
        self._test_btn.setEnabled(True)
        self._status_lbl.setStyleSheet("color: #16A34A; font-weight: 600;" if ok else "color: #DC2626; font-weight: 600;")
        self._status_lbl.setText(msg)

    def _save_and_close(self) -> None:
        self._config.api_key = self._key_edit.text().strip()
        self._config.gemini_key = self._gemini_edit.text().strip()
        self._config.openai_key = self._openai_edit.text().strip()
        self._config.anthropic_key = self._anthropic_edit.text().strip()
        self._config.deepseek_key = self._deepseek_edit.text().strip()
        self._config.model = self._selected_model_id()
        self._config.custom_logo_path = self._logo_edit.text().strip()
        set_custom_logo_path(self._config.custom_logo_path)
        self._config.base_url = self._url_edit.text().strip() or DEFAULT_BASE_URL
        self._config.execution_mode = str(self._mode_combo.currentData() or "autopilot")
        self._config.auto_fallback_free = self._fallback_chk.isChecked()
        self._config.max_tokens = self._tokens_spin.value()
        self._config.custom_instructions = self._custom_edit.toPlainText().strip()
        self.settings_saved.emit()
        self.accept()
