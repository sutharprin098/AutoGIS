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
    QSizePolicy,
    QVBoxLayout,
)

from .theme import create_autogis_pixmap, markdown_to_html


class UserMessageCard(QFrame):
    """Clean, minimal user prompt bubble."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISUserBubble")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        lbl = QLabel(text, self)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet("font-size: 12.5px; line-height: 1.4; background: transparent; border: none;")
        layout.addWidget(lbl)


class AssistantMessageCard(QFrame):
    """Clean streaming Markdown response card without model-ID clutter."""

    def __init__(self, model_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISAssistantBubble")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._raw_text = ""
        self._reasoning_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(6)

        logo = QLabel(self)
        logo.setPixmap(create_autogis_pixmap(16))
        logo.setFixedSize(16, 16)
        logo.setStyleSheet("background: transparent; border: none;")
        hdr.addWidget(logo)

        title = QLabel("AutoGIS", self)
        title.setStyleSheet("font-size: 11.5px; font-weight: 700; color: #1E293B; background: transparent; border: none;")
        hdr.addWidget(title)
        hdr.addStretch(1)

        self._reason_btn = QPushButton("Thought", self)
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

        self._reason_lbl = QLabel("", self)
        self._reason_lbl.setWordWrap(True)
        self._reason_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._reason_lbl.setStyleSheet(
            "background: #F8FAFC; color: #64748B; border-left: 2px solid #CBD5E1; "
            "border-radius: 4px; padding: 6px 8px; font-size: 11px;"
        )
        self._reason_lbl.hide()
        layout.addWidget(self._reason_lbl)

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
            self._reason_btn.setText("Hide")
        else:
            self._reason_lbl.hide()
            self._reason_btn.setText("Thought")

    def _copy(self) -> None:
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._raw_text)
            self._copy_btn.setText("Copied")
            QTimer.singleShot(1200, lambda: self._copy_btn.setText("Copy"))


class ToolExecutionCard(QFrame):
    """Compact 1-line card showing a GIS tool call and expandable output."""

    def __init__(self, call_id: str, tool_name: str, args: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISToolCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.call_id = call_id
        self._tool_name = tool_name
        self._args = args
        self._result: Any = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._status_icon = QLabel("RUN", self)
        self._status_icon.setStyleSheet(
            "font-size: 9.5px; font-weight: 700; color: #2563EB; background: #EFF6FF; "
            "border-radius: 4px; padding: 1px 5px;"
        )
        row.addWidget(self._status_icon)

        self._title_lbl = QLabel(f"<b>{tool_name}</b>", self)
        self._title_lbl.setStyleSheet("font-size: 11.5px; background: transparent; border: none;")
        row.addWidget(self._title_lbl, 1)

        self._badge_lbl = QLabel("...", self)
        self._badge_lbl.setStyleSheet("font-size: 10.5px; color: #2563EB; font-weight: 600; background: transparent; border: none;")
        row.addWidget(self._badge_lbl)

        self._toggle_btn = QPushButton("+", self)
        self._toggle_btn.setObjectName("AutoGISGhostBtn")
        self._toggle_btn.setFixedWidth(24)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle_details)
        row.addWidget(self._toggle_btn)

        layout.addLayout(row)

        self._details_lbl = QLabel("", self)
        self._details_lbl.setWordWrap(True)
        self._details_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._details_lbl.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 10.5px; color: #64748B; "
            "background: #F8FAFC; border-radius: 5px; padding: 6px;"
        )
        self._details_lbl.hide()
        layout.addWidget(self._details_lbl)
        self._update_details_text()

    def mark_finished(self, result: Any, elapsed_ms: int, is_error: bool) -> None:
        self._result = result
        sec = f"{elapsed_ms / 1000.0:.1f}s"
        if is_error:
            self._status_icon.setText("ERR")
            self._status_icon.setStyleSheet(
                "font-size: 9.5px; font-weight: 700; color: #DC2626; background: #FEF2F2; "
                "border-radius: 4px; padding: 1px 5px;"
            )
            self._badge_lbl.setText(sec)
            self._badge_lbl.setStyleSheet("font-size: 10.5px; color: #DC2626; font-weight: 600; background: transparent; border: none;")
        else:
            self._status_icon.setText("OK")
            self._status_icon.setStyleSheet(
                "font-size: 9.5px; font-weight: 700; color: #16A34A; background: #F0FDF4; "
                "border-radius: 4px; padding: 1px 5px;"
            )
            self._badge_lbl.setText(sec)
            self._badge_lbl.setStyleSheet("font-size: 10.5px; color: #16A34A; font-weight: 600; background: transparent; border: none;")
        self._update_details_text()

    def _update_details_text(self) -> None:
        try:
            args_json = json.dumps(self._args, ensure_ascii=False, indent=2)
        except Exception:
            args_json = str(self._args)
        text = f"Input:\n{args_json}"
        if self._result is not None:
            try:
                res_json = json.dumps(self._result, ensure_ascii=False, indent=2, default=str)
            except Exception:
                res_json = str(self._result)
            if len(res_json) > 1200:
                res_json = res_json[:1200] + "\n..."
            text += f"\n\nResult:\n{res_json}"
        self._details_lbl.setText(text)

    def _toggle_details(self) -> None:
        vis = not self._details_lbl.isVisible()
        self._details_lbl.setVisible(vis)
        self._toggle_btn.setText("-" if vis else "+")


class PermissionPromptCard(QFrame):
    """Approval prompt shown when a write tool is requested in 'ask_write' mode."""

    decided = pyqtSignal(str, bool)

    def __init__(self, call_id: str, tool_name: str, args: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISToolCard")
        self._call_id = call_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        title = QLabel(f"Run <b>{tool_name}</b>?", self)
        title.setStyleSheet("font-size: 12px; background: transparent; border: none;")
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._approve_btn = QPushButton("Approve", self)
        self._approve_btn.setObjectName("AutoGISPrimaryBtn")
        self._approve_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._approve_btn.clicked.connect(lambda: self._finish(True))
        btn_row.addWidget(self._approve_btn)

        self._deny_btn = QPushButton("Skip", self)
        self._deny_btn.setObjectName("AutoGISGhostBtn")
        self._deny_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._deny_btn.clicked.connect(lambda: self._finish(False))
        btn_row.addWidget(self._deny_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _finish(self, approved: bool) -> None:
        self._approve_btn.setEnabled(False)
        self._deny_btn.setEnabled(False)
        self.decided.emit(self._call_id, approved)


class InlineMapCard(QFrame):
    """Displays a captured map canvas snapshot inside the chat stream."""

    def __init__(self, image_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISCard")
        self._path = image_path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        hdr = QHBoxLayout()
        lbl = QLabel("<b>Map Snapshot</b>", self)
        lbl.setStyleSheet("font-size: 11px; background: transparent; border: none;")
        hdr.addWidget(lbl)
        hdr.addStretch(1)

        open_btn = QPushButton("Open", self)
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
                scaled = pix.scaledToWidth(260, Qt.TransformationMode.SmoothTransformation)
                img_lbl.setPixmap(scaled)
        layout.addWidget(img_lbl)


class LiveStatusBanner(QFrame):
    """Compact live status bar with the elapsed timer positioned on the LEFT."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISCard")
        self._t0 = 0.0

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)

        # Timer Badge on the LEFT
        self._time_lbl = QLabel("0.0s", self)
        self._time_lbl.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #2563EB; "
            "background: #EFF6FF; border-radius: 5px; padding: 2px 7px; font-family: Consolas, monospace;"
        )
        row.addWidget(self._time_lbl)

        # Status Text right next to the timer on the LEFT
        self._text_lbl = QLabel("Thinking...", self)
        self._text_lbl.setStyleSheet("font-size: 11.5px; font-weight: 600; color: #475569; background: transparent; border: none;")
        row.addWidget(self._text_lbl)
        row.addStretch(1)

        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._tick)
        self.hide()

    def start_status(self, text: str) -> None:
        if self._t0 <= 0:
            self._t0 = time.monotonic()
        self._text_lbl.setText(text or "Working...")
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
    """Displays a step-by-step Autonomous GIS Plan."""

    def __init__(self, title: str = "Plan", steps: list[dict] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISCard")
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(10, 8, 10, 8)
        self._col.setSpacing(4)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        self._title_lbl = QLabel("", self)
        self._title_lbl.setStyleSheet("font-size: 11.5px; font-weight: 700; color: #2563EB; background: transparent; border: none;")
        hdr.addWidget(self._title_lbl, 1)

        self._prog_lbl = QLabel("", self)
        self._prog_lbl.setStyleSheet("font-size: 10.5px; font-weight: 600; color: #16A34A; background: transparent; border: none;")
        hdr.addWidget(self._prog_lbl)
        self._col.addLayout(hdr)

        self._steps_lbl = QLabel("", self)
        self._steps_lbl.setWordWrap(True)
        self._steps_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._steps_lbl.setStyleSheet("font-size: 11px; background: transparent; border: none;")
        self._col.addWidget(self._steps_lbl)

        self.update_plan(title, steps or [])

    def update_plan(self, title: str, steps: list[dict]) -> None:
        self._title_lbl.setText(title)
        done_count = 0
        lines = []
        for idx, item in enumerate(steps, 1):
            st = str(item.get("status") or "pending").lower()
            txt = str(item.get("step") or f"Step {idx}")
            if st == "completed":
                done_count += 1
                tag, style = "[DONE]", "color: #16A34A;"
            elif st == "in_progress":
                tag, style = "[ACTIVE]", "color: #2563EB; font-weight: 600;"
            else:
                tag, style = "[WAIT]", "color: #64748B;"
            lines.append(f"<div style='margin: 2px 0; {style}'><b>{tag}</b> {txt}</div>")
        self._prog_lbl.setText(f"{done_count}/{len(steps)}" if steps else "")
        self._steps_lbl.setText("".join(lines))


class WelcomeStarterCard(QFrame):
    """Minimal, clean welcome card that fits narrow dock widths."""

    prompt_selected = pyqtSignal(str)

    STARTERS = [
        ("Inspect Project", "Give me an overview of my current QGIS project, CRS, and layers."),
        ("Place Boundary", "Download the administrative polygon boundary for Jaipur, India."),
        ("OSM Vectors", "Download live OpenStreetMap buildings and roads for Connaught Place, New Delhi."),
        ("Style Layer", "Inspect the active vector layer and apply a clean cartographic style."),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AutoGISCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        col = QVBoxLayout(self)
        col.setContentsMargins(12, 14, 12, 14)
        col.setSpacing(8)

        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo = QLabel(self)
        logo.setPixmap(create_autogis_pixmap(42))
        logo.setFixedSize(42, 42)
        logo.setStyleSheet("background: transparent; border: none;")
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        col.addLayout(logo_row)

        title = QLabel("AutoGIS", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 15px; font-weight: 800; background: transparent; border: none;")
        col.addWidget(title)

        sub = QLabel("Autonomous GIS Assistant", self)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("font-size: 11px; color: #64748B; background: transparent; border: none;")
        col.addWidget(sub)

        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (label, prompt) in enumerate(self.STARTERS):
            btn = QPushButton(label, self)
            btn.setObjectName("AutoGISGhostBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(28)
            btn.clicked.connect(lambda _=False, p=prompt: self.prompt_selected.emit(p))
            grid.addWidget(btn, i // 2, i % 2)
        col.addLayout(grid)
