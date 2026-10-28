from __future__ import annotations

import json
import os
import time
from typing import Any

from qgis.PyQt.QtCore import Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import create_autogis_pixmap, is_dark_theme, markdown_to_html


class UserMessageCard(QFrame):
    """Displays a user prompt bubble in the chat stream."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISUserBubble")
        self._raw_text = text

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 10, 13, 10)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        badge = QLabel("YOU", self)
        badge.setStyleSheet("color: #2563EB; font-size: 10px; font-weight: 800; letter-spacing: 0.6px; background: transparent; border: none;")
        top.addWidget(badge)
        top.addStretch(1)

        copy_btn = QPushButton("Copy", self)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(
            "QPushButton { background: rgba(37,99,235,0.10); color: #1E40AF; border: none; border-radius: 5px; padding: 2px 7px; font-size: 10px; font-weight: 600; }"
            "QPushButton:hover { background: rgba(37,99,235,0.20); }"
        )
        copy_btn.clicked.connect(self._copy)
        top.addWidget(copy_btn)
        layout.addLayout(top)

        lbl = QLabel(text, self)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet("font-size: 12.5px; line-height: 1.45; background: transparent; border: none;")
        layout.addWidget(lbl)

    def _copy(self) -> None:
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._raw_text)


class AssistantMessageCard(QFrame):
    """Streaming Markdown response card with expandable AI reasoning trace."""

    def __init__(self, model_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISAssistantBubble")
        self._raw_text = ""
        self._reasoning_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header Row
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(6)

        logo = QLabel(self)
        logo.setPixmap(create_autogis_pixmap(16))
        logo.setFixedSize(16, 16)
        logo.setStyleSheet("background: transparent; border: none;")
        hdr.addWidget(logo)

        short_mod = model_name.split("/")[-1] if "/" in model_name else (model_name or "AutoGIS AI")
        title = QLabel(f"AutoGIS  ·  {short_mod}", self)
        title.setStyleSheet("font-size: 11px; font-weight: 700; color: #0284C7; background: transparent; border: none;")
        hdr.addWidget(title)
        hdr.addStretch(1)

        self._reason_btn = QPushButton("🧠 Show Reasoning", self)
        self._reason_btn.setObjectName("AutoGISGhostBtn")
        self._reason_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reason_btn.hide()
        self._reason_btn.clicked.connect(self._toggle_reasoning)
        hdr.addWidget(self._reason_btn)

        self._copy_btn = QPushButton("Copy", self)
        self._copy_btn.setObjectName("AutoGISGhostBtn")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(self._copy)
        hdr.addWidget(self._copy_btn)
        layout.addLayout(hdr)

        # Reasoning Drawer
        self._reason_lbl = QLabel("", self)
        self._reason_lbl.setWordWrap(True)
        self._reason_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._reason_lbl.setStyleSheet(
            "background: rgba(148, 163, 184, 0.12); color: #64748B; border-left: 2px solid #94A3B8; "
            "border-radius: 4px; padding: 6px 8px; font-size: 11px; font-style: italic;"
        )
        self._reason_lbl.hide()
        layout.addWidget(self._reason_lbl)

        # Main Markdown Content
        self._content_lbl = QLabel("", self)
        self._content_lbl.setWordWrap(True)
        self._content_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._content_lbl.setOpenExternalLinks(True)
        self._content_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._content_lbl.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._content_lbl)

    def append_reasoning(self, chunk: str) -> None:
        self._reasoning_text += chunk
        if self._reasoning_text.strip() and self._reason_btn.isHidden():
            self._reason_btn.show()
        if not self._reason_lbl.isHidden():
            self._reason_lbl.setText(self._reasoning_text.strip())

    def append_text(self, chunk: str) -> None:
        self._raw_text += chunk
        self._content_lbl.setText(markdown_to_html(self._raw_text))

    def set_full_text(self, text: str) -> None:
        self._raw_text = text
        self._content_lbl.setText(markdown_to_html(self._raw_text))

    @property
    def text(self) -> str:
        return self._raw_text

    def _toggle_reasoning(self) -> None:
        vis = not self._reason_lbl.isVisible()
        if vis:
            self._reason_lbl.setText(self._reasoning_text.strip())
            self._reason_lbl.show()
            self._reason_btn.setText("🧠 Hide Reasoning")
        else:
            self._reason_lbl.hide()
            self._reason_btn.setText("🧠 Show Reasoning")

    def _copy(self) -> None:
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._raw_text)
            self._copy_btn.setText("✓ Copied")
            QTimer.singleShot(1400, lambda: self._copy_btn.setText("Copy"))


class ToolExecutionCard(QFrame):
    """Interactive card showing a PyQGIS tool call and its expandable result."""

    def __init__(self, call_id: str, tool_name: str, args: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISToolCard")
        self.call_id = call_id
        self._tool_name = tool_name
        self._args = args
        self._result: Any = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._status_icon = QLabel("⏳", self)
        self._status_icon.setStyleSheet("font-size: 13px; background: transparent; border: none;")
        row.addWidget(self._status_icon)

        arg_preview = self._summarize_args(args)
        self._title_lbl = QLabel(f"<b>{tool_name}</b> <span style='color:#64748B;'>{arg_preview}</span>", self)
        self._title_lbl.setStyleSheet("font-size: 11.5px; background: transparent; border: none;")
        row.addWidget(self._title_lbl, 1)

        self._badge_lbl = QLabel("Running...", self)
        self._badge_lbl.setStyleSheet("font-size: 10.5px; color: #0284C7; font-weight: 600; background: transparent; border: none;")
        row.addWidget(self._badge_lbl)

        self._toggle_btn = QPushButton("Details ▾", self)
        self._toggle_btn.setObjectName("AutoGISGhostBtn")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle_details)
        row.addWidget(self._toggle_btn)

        layout.addLayout(row)

        self._details_lbl = QLabel("", self)
        self._details_lbl.setWordWrap(True)
        self._details_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._details_lbl.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; color: #64748B; "
            "background: rgba(15, 23, 42, 0.06); border-radius: 5px; padding: 6px;"
        )
        self._details_lbl.hide()
        layout.addWidget(self._details_lbl)
        self._update_details_text()

    @staticmethod
    def _summarize_args(args: dict) -> str:
        if not isinstance(args, dict) or not args:
            return ""
        parts = []
        for k, v in list(args.items())[:3]:
            s = str(v)
            if len(s) > 28:
                s = s[:25] + "..."
            parts.append(f"{k}={s}")
        return "(" + ", ".join(parts) + ")"

    def mark_finished(self, result: Any, elapsed_ms: int, is_error: bool) -> None:
        self._result = result
        if is_error:
            self._status_icon.setText("⚠️")
            self._badge_lbl.setText(f"Error ({elapsed_ms}ms)")
            self._badge_lbl.setStyleSheet("font-size: 10.5px; color: #DC2626; font-weight: 600; background: transparent; border: none;")
        else:
            self._status_icon.setText("✅")
            self._badge_lbl.setText(f"Done ({elapsed_ms}ms)")
            self._badge_lbl.setStyleSheet("font-size: 10.5px; color: #16A34A; font-weight: 600; background: transparent; border: none;")
        self._update_details_text()

    def _update_details_text(self) -> None:
        try:
            args_json = json.dumps(self._args, ensure_ascii=False, indent=2)
        except Exception:
            args_json = str(self._args)
        text = f"Arguments:\n{args_json}"
        if self._result is not None:
            try:
                res_json = json.dumps(self._result, ensure_ascii=False, indent=2, default=str)
            except Exception:
                res_json = str(self._result)
            if len(res_json) > 1500:
                res_json = res_json[:1500] + "\n...[truncated]"
            text += f"\n\nOutput:\n{res_json}"
        self._details_lbl.setText(text)

    def _toggle_details(self) -> None:
        vis = not self._details_lbl.isVisible()
        self._details_lbl.setVisible(vis)
        self._toggle_btn.setText("Hide ▴" if vis else "Details ▾")


class PermissionPromptCard(QFrame):
    """Approval prompt shown when a write tool is requested in 'ask_write' mode."""

    decided = pyqtSignal(str, bool)  # (call_id, approved)

    def __init__(self, call_id: str, tool_name: str, args: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISToolCard")
        self._call_id = call_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title = QLabel(f"🛡️ <b>Permission Required:</b> Run <code>{tool_name}</code>?", self)
        title.setStyleSheet("font-size: 12px; background: transparent; border: none;")
        layout.addWidget(title)

        try:
            args_str = json.dumps(args, ensure_ascii=False, indent=2)
        except Exception:
            args_str = str(args)
        params_lbl = QLabel(args_str[:400], self)
        params_lbl.setWordWrap(True)
        params_lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; color: #64748B; background: transparent; border: none;")
        layout.addWidget(params_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._approve_btn = QPushButton("✓ Approve & Execute", self)
        self._approve_btn.setObjectName("AutoGISPrimaryBtn")
        self._approve_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._approve_btn.clicked.connect(lambda: self._finish(True))
        btn_row.addWidget(self._approve_btn)

        self._deny_btn = QPushButton("✕ Deny", self)
        self._deny_btn.setObjectName("AutoGISGhostBtn")
        self._deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._deny_btn.clicked.connect(lambda: self._finish(False))
        btn_row.addWidget(self._deny_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _finish(self, approved: bool) -> None:
        self._approve_btn.setEnabled(False)
        self._deny_btn.setEnabled(False)
        self._approve_btn.setText("✓ Approved" if approved else "Approved")
        self._deny_btn.setText("✕ Denied" if not approved else "Deny")
        self.decided.emit(self._call_id, approved)


class InlineMapCard(QFrame):
    """Displays a rendered map canvas snapshot directly inside the chat stream."""

    def __init__(self, image_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISCard")
        self._path = image_path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        lbl = QLabel("🗺️ <b>Captured QGIS Map Canvas</b>", self)
        lbl.setStyleSheet("font-size: 11.5px; background: transparent; border: none;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)

        open_btn = QPushButton("Open Image ↗", self)
        open_btn.setObjectName("AutoGISGhostBtn")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._path)))
        hdr.addWidget(open_btn)
        layout.addLayout(hdr)

        img_lbl = QLabel(self)
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if os.path.exists(image_path):
            pix = QPixmap(image_path)
            if not pix.isNull():
                scaled = pix.scaledToWidth(340, Qt.TransformationMode.SmoothTransformation)
                img_lbl.setPixmap(scaled)
        layout.addWidget(img_lbl)


class LiveStatusBanner(QFrame):
    """Animated live status bar with elapsed timer shown while the AI is working."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISCard")
        self._t0 = 0.0
        self._base_text = "Thinking..."

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 7, 12, 7)
        row.setSpacing(8)

        self._dot = QLabel("⚡", self)
        self._dot.setStyleSheet("font-size: 13px; background: transparent; border: none;")
        row.addWidget(self._dot)

        self._text_lbl = QLabel("Thinking...", self)
        self._text_lbl.setStyleSheet("font-size: 11.5px; font-weight: 600; color: #0284C7; background: transparent; border: none;")
        row.addWidget(self._text_lbl, 1)

        self._time_lbl = QLabel("0.0s", self)
        self._time_lbl.setStyleSheet("font-size: 11px; color: #64748B; font-family: Consolas, monospace; background: transparent; border: none;")
        row.addWidget(self._time_lbl)

        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._tick)
        self.hide()

    def start_status(self, text: str) -> None:
        if self._t0 <= 0:
            self._t0 = time.monotonic()
        self._base_text = text or "Processing..."
        self._text_lbl.setText(self._base_text)
        self._tick()
        self.show()
        if not self._clock.isActive():
            self._clock.start()

    def stop_status(self) -> None:
        self._clock.stop()
        self._t0 = 0.0
        self.hide()

    def _tick(self) -> None:
        if self._t0 <= 0:
            return
        elapsed = time.monotonic() - self._t0
        self._time_lbl.setText(f"{elapsed:.1f}s")


class PlanChecklistCard(QFrame):
    """Displays a live TerraLab-style step-by-step Autonomous GIS Agent Execution Plan."""

    def __init__(self, title: str = "Autonomous GIS Plan", steps: list[dict] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISCard")
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(12, 10, 12, 10)
        self._col.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        self._title_lbl = QLabel("", self)
        self._title_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #0284C7; background: transparent; border: none;")
        hdr.addWidget(self._title_lbl, 1)

        self._prog_lbl = QLabel("", self)
        self._prog_lbl.setStyleSheet("font-size: 10.5px; font-weight: 600; color: #16A34A; background: transparent; border: none;")
        hdr.addWidget(self._prog_lbl)
        self._col.addLayout(hdr)

        self._steps_lbl = QLabel("", self)
        self._steps_lbl.setWordWrap(True)
        self._steps_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._steps_lbl.setStyleSheet("font-size: 11.5px; background: transparent; border: none;")
        self._col.addWidget(self._steps_lbl)

        self.update_plan(title, steps or [])

    def update_plan(self, title: str, steps: list[dict]) -> None:
        self._title_lbl.setText(f"🧭 {title}")
        done_count = 0
        lines = []
        for idx, item in enumerate(steps, 1):
            st = str(item.get("status") or "pending").lower()
            txt = str(item.get("step") or f"Step {idx}")
            if st == "completed":
                done_count += 1
                icon = "✅"
                style = "color: #16A34A; font-weight: 600;"
            elif st == "in_progress":
                icon = "🔄"
                style = "color: #0284C7; font-weight: 700;"
            elif st == "skipped":
                icon = "⏭️"
                style = "color: #94A3B8;"
            else:
                icon = "⏳"
                style = "color: #64748B;"
            lines.append(f"<div style='margin: 2px 0; {style}'>{icon} <b>Step {idx}:</b> {txt}</div>")
        total = max(1, len(steps))
        self._prog_lbl.setText(f"{done_count}/{len(steps)} Done" if steps else "")
        self._steps_lbl.setText("".join(lines))


class WelcomeStarterCard(QFrame):
    """Studio welcome card with 8 one-click A-to-Z GIS & Live Data starters."""

    prompt_selected = pyqtSignal(str)

    STARTERS = [
        ("🏛️ Fetch City Boundary", "Download the exact polygon administrative boundary for Jaipur, India and add a satellite basemap."),
        ("🏗️ Live OSM Buildings & Roads", "Download live OpenStreetMap roads and buildings for Connaught Place, New Delhi and style them."),
        ("🏔️ 30m Elevation DEM (STAC)", "Stream the Copernicus 30m Elevation DEM from Microsoft Planetary Computer STAC for Dehradun, India."),
        ("🛰️ Sentinel-2 & Land Cover", "Load the Esri 10m Land Cover (LULC) raster from Planetary Computer STAC for the current map area."),
        ("🚗 OSRM Road Routing", "Calculate the fastest driving road route from India Gate, Delhi to Qutub Minar, Delhi and map it."),
        ("🎨 Smart Cartographic Styling", "Inspect my active vector layer and apply a clean categorized or graduated style with labels."),
        ("⚙️ Spatial Buffer & Overlay", "Create a 500m buffer around my active vector layer and compute summary statistics."),
        ("🌐 Saved WMS / WFS / XYZ", "List all my saved QGIS XYZ, WMS (Bhuvan), and WFS connections and show me what's available."),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISCard")

        col = QVBoxLayout(self)
        col.setContentsMargins(16, 18, 16, 18)
        col.setSpacing(10)

        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo = QLabel(self)
        logo.setPixmap(create_autogis_pixmap(48))
        logo.setFixedSize(48, 48)
        logo.setStyleSheet("background: transparent; border: none;")
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        col.addLayout(logo_row)

        title = QLabel("AutoGIS Studio", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 800; background: transparent; border: none;")
        col.addWidget(title)

        sub = QLabel(
            "Autonomous Geospatial Studio · Multi-Model AI Agent\n"
            "Live OSM · Admin Boundaries · STAC Earth Data · OSRM Routing · PDF & PyQGIS:",
            self,
        )
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("font-size: 11px; color: #64748B; background: transparent; border: none;")
        col.addWidget(sub)

        grid = QGridLayout()
        grid.setSpacing(7)
        for i, (label, prompt) in enumerate(self.STARTERS):
            btn = QPushButton(label, self)
            btn.setObjectName("AutoGISGhostBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(30)
            btn.clicked.connect(lambda _=False, p=prompt: self.prompt_selected.emit(p))
            grid.addWidget(btn, i // 2, i % 2)
        col.addLayout(grid)
