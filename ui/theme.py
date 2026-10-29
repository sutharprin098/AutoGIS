from __future__ import annotations

import html
import os
import re

from qgis.PyQt.QtCore import QPointF, QRectF, QSize, Qt
from qgis.PyQt.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from qgis.PyQt.QtWidgets import QApplication

try:
    from qgis.PyQt.QtSvg import QSvgRenderer
except Exception:
    QSvgRenderer = None

_MASTER_LOGO_CACHE: QImage | None = None
_CUSTOM_LOGO_PATH: str = ""


def set_custom_logo_path(path: str) -> None:
    global _CUSTOM_LOGO_PATH, _MASTER_LOGO_CACHE
    _CUSTOM_LOGO_PATH = str(path or "").strip()
    _MASTER_LOGO_CACHE = None


def is_dark_theme() -> bool:
    try:
        app = QApplication.instance()
        if app is not None:
            bg = app.palette().window().color()
            return bg.lightness() < 110
    except Exception as _err:  # nosec B110
        _ = _err
    return False


def _render_master_cartographic_logo(canvas_size: int = 512) -> QImage:
    """Render a clean, light-colored professional Cartographic Map & Survey Emblem at 512x512.
    Zero neon or AI-spark clichés — designed like a Swiss/desktop GIS studio emblem.
    """
    if _CUSTOM_LOGO_PATH and os.path.exists(_CUSTOM_LOGO_PATH):
        custom_img = QImage(_CUSTOM_LOGO_PATH)
        if not custom_img.isNull():
            return custom_img.scaled(
                canvas_size,
                canvas_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

    svg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons", "icon.svg")
    if QSvgRenderer is not None and os.path.exists(svg_path):
        renderer = QSvgRenderer(svg_path)
        if renderer.isValid():
            img = QImage(canvas_size, canvas_size, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            renderer.render(painter, QRectF(0, 0, canvas_size, canvas_size))
            painter.end()
            return img

    s = float(canvas_size)
    img = QImage(canvas_size, canvas_size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # 1. Soft Light Porcelain Squircle Container
    bg_grad = QLinearGradient(0, 0, s, s)
    bg_grad.setColorAt(0.0, QColor("#FFFFFF"))
    bg_grad.setColorAt(1.0, QColor("#F0F7FF"))

    pad = s * 0.045
    rect = QRectF(pad, pad, s - 2 * pad, s - 2 * pad)
    radius = s * 0.21
    p.setPen(QPen(QColor("#CBD5E1"), s * 0.02))
    p.setBrush(QBrush(bg_grad))
    p.drawRoundedRect(rect, radius, radius)

    # 2. Three Folded Map Panels (Light Sky & Pearl)
    map_pen = QPen(QColor("#38BDF8"), s * 0.016, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(map_pen)

    left_panel = QPolygonF([
        QPointF(s * 0.19, s * 0.30),
        QPointF(s * 0.38, s * 0.23),
        QPointF(s * 0.38, s * 0.73),
        QPointF(s * 0.19, s * 0.80),
    ])
    p.setBrush(QColor("#E0F2FE"))
    p.drawPolygon(left_panel)

    mid_panel = QPolygonF([
        QPointF(s * 0.38, s * 0.23),
        QPointF(s * 0.62, s * 0.30),
        QPointF(s * 0.62, s * 0.80),
        QPointF(s * 0.38, s * 0.73),
    ])
    p.setBrush(QColor("#F0F9FF"))
    p.drawPolygon(mid_panel)

    right_panel = QPolygonF([
        QPointF(s * 0.62, s * 0.30),
        QPointF(s * 0.81, s * 0.23),
        QPointF(s * 0.81, s * 0.73),
        QPointF(s * 0.62, s * 0.80),
    ])
    p.setBrush(QColor("#BAE6FD"))
    p.drawPolygon(right_panel)

    # 3. Smooth Topographic Contour Line
    contour = QPainterPath()
    contour.moveTo(s * 0.22, s * 0.57)
    contour.quadTo(s * 0.39, s * 0.45, s * 0.55, s * 0.54)
    contour.quadTo(s * 0.68, s * 0.61, s * 0.78, s * 0.45)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor("#0D9488"), s * 0.024, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(contour)

    # 4. Central Precision Survey Compass Ring
    cx, cy = s * 0.50, s * 0.46
    r = s * 0.135
    p.setBrush(QColor("#FFFFFF"))
    p.setPen(QPen(QColor("#2563EB"), s * 0.03))
    p.drawEllipse(QPointF(cx, cy), r, r)

    north = QPolygonF([
        QPointF(cx, cy - r * 0.78),
        QPointF(cx + r * 0.34, cy),
        QPointF(cx, cy - r * 0.18),
        QPointF(cx - r * 0.34, cy),
    ])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2563EB"))
    p.drawPolygon(north)

    south = QPolygonF([
        QPointF(cx, cy + r * 0.78),
        QPointF(cx + r * 0.34, cy),
        QPointF(cx, cy + r * 0.18),
        QPointF(cx - r * 0.34, cy),
    ])
    p.setBrush(QColor("#0D9488"))
    p.drawPolygon(south)

    p.setBrush(QColor("#1E293B"))
    p.drawEllipse(QPointF(cx, cy), s * 0.02, s * 0.02)

    p.end()
    return img


def create_autogis_logo_image(size: int = 128) -> QImage:
    """Return a supersampled, razor-sharp QImage at the requested size."""
    global _MASTER_LOGO_CACHE
    if _MASTER_LOGO_CACHE is None:
        _MASTER_LOGO_CACHE = _render_master_cartographic_logo(512)
    if size == 512:
        return _MASTER_LOGO_CACHE
    return _MASTER_LOGO_CACHE.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def ensure_logo_png(plugin_dir: str) -> str:
    icons_dir = os.path.join(plugin_dir, "icons")
    os.makedirs(icons_dir, exist_ok=True)
    png_path = os.path.join(icons_dir, "icon.png")
    img = create_autogis_logo_image(256)
    img.save(png_path, "PNG")
    return png_path


def create_autogis_pixmap(size: int = 28) -> QPixmap:
    """Create a High-DPI (2x–3x) anti-aliased QPixmap so icons never look pixelated."""
    dpr = 2.0
    try:
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            dpr = max(2.0, float(scr.devicePixelRatio()))
    except Exception:
        dpr = 2.0

    px_size = int(round(size * dpr))
    img = create_autogis_logo_image(px_size)
    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    return pix


def create_autogis_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(create_autogis_pixmap(sz))
    return icon


def get_studio_stylesheet(dark: bool | None = None) -> str:
    """Smooth, light-first desktop GIS stylesheet with refined surfaces and scrollbars."""
    if dark is None:
        dark = is_dark_theme()

    if dark:
        bg_main = "#0F172A"
        bg_card = "#1E293B"
        bg_subtle = "#162032"
        bg_input = "#0F172A"
        border = "#334155"
        border_soft = "#263349"
        text_main = "#F8FAFC"
        text_muted = "#94A3B8"
        accent = "#3B82F6"
        accent_btn = "#2563EB"
        accent_btn_hover = "#1D4ED8"
        user_bubble_bg = "#1E3A8A"
        user_bubble_fg = "#F8FAFC"
        scroll_thumb = "#475569"
    else:
        bg_main = "#F8FAFC"
        bg_card = "#FFFFFF"
        bg_subtle = "#F1F5F9"
        bg_input = "#FFFFFF"
        border = "#E2E8F0"
        border_soft = "#EDF2F7"
        text_main = "#1E293B"
        text_muted = "#64748B"
        accent = "#2563EB"
        accent_btn = "#2563EB"
        accent_btn_hover = "#1D4ED8"
        user_bubble_bg = "#EFF6FF"
        user_bubble_fg = "#1E293B"
        scroll_thumb = "#CBD5E1"

    return f"""
    QWidget#AutoGISRoot {{
        background-color: {bg_main};
        color: {text_main};
        font-family: 'Segoe UI Variable Text', 'Segoe UI', -apple-system, sans-serif;
        font-size: 12.5px;
    }}
    QFrame#AutoGISHeader {{
        background-color: {bg_card};
        border-bottom: 1px solid {border};
    }}
    QFrame#AutoGISCard {{
        background-color: {bg_card};
        border: 1px solid {border};
        border-radius: 12px;
    }}
    QFrame#AutoGISUserBubble {{
        background-color: {user_bubble_bg};
        color: {user_bubble_fg};
        border: 1px solid #BFDBFE;
        border-radius: 12px;
    }}
    QFrame#AutoGISAssistantBubble {{
        background-color: {bg_card};
        border: 1px solid {border};
        border-radius: 12px;
    }}
    QFrame#AutoGISToolCard {{
        background-color: {bg_card};
        border: 1px solid {border};
        border-left: 3px solid {accent};
        border-radius: 9px;
    }}
    QFrame#AutoGISComposerFrame {{
        background-color: {bg_input};
        border: 1.5px solid {border};
        border-radius: 14px;
    }}
    QFrame#AutoGISComposerFrame:focus-within {{
        border: 1.5px solid {accent};
    }}
    QPlainTextEdit#AutoGISInput {{
        background: transparent;
        color: {text_main};
        border: none;
        font-size: 13px;
        selection-background-color: {accent_btn};
        selection-color: #FFFFFF;
    }}
    QPushButton#AutoGISPrimaryBtn {{
        background-color: {accent_btn};
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        padding: 6px 15px;
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton#AutoGISPrimaryBtn:hover {{
        background-color: {accent_btn_hover};
    }}
    QPushButton#AutoGISStopBtn {{
        background-color: #EF4444;
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        padding: 6px 15px;
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton#AutoGISGhostBtn {{
        background-color: {bg_card};
        color: {text_main};
        border: 1px solid {border};
        border-radius: 7px;
        padding: 4px 10px;
        font-size: 11.5px;
        font-weight: 500;
    }}
    QPushButton#AutoGISGhostBtn:hover {{
        border-color: {accent};
        background-color: {bg_subtle};
        color: {accent};
    }}
    QComboBox#AutoGISCombo {{
        background-color: {bg_subtle};
        color: {text_main};
        border: 1px solid {border};
        border-radius: 7px;
        padding: 4px 9px;
        font-size: 11.5px;
        font-weight: 500;
    }}
    QComboBox#AutoGISCombo:hover {{
        border-color: {accent};
    }}
    QComboBox#AutoGISCombo::drop-down {{
        border: none;
        width: 18px;
    }}
    QLineEdit, QPlainTextEdit, QSpinBox {{
        background-color: {bg_input};
        color: {text_main};
        border: 1px solid {border};
        border-radius: 7px;
        padding: 4px 8px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
        border: 1.5px solid {accent};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 7px;
        margin: 2px 1px 2px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: {scroll_thumb};
        min-height: 28px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {text_muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    """


def markdown_to_html(md_text: str, dark: bool | None = None) -> str:
    """Convert Markdown (including code blocks, tables, headers, lists, bold/italic) into styled HTML."""
    if dark is None:
        dark = is_dark_theme()

    code_bg = "#0B1120" if dark else "#F8FAFC"
    code_fg = "#38BDF8" if dark else "#0F172A"
    border_col = "#334155" if dark else "#E2E8F0"
    th_bg = "#1E293B" if dark else "#F1F5F9"
    text_col = "#F8FAFC" if dark else "#1E293B"

    text = str(md_text or "")
    code_blocks: list[str] = []

    def _save_code_block(match: re.Match) -> str:
        lang = (match.group(1) or "").strip()
        code = html.escape(match.group(2) or "")
        lang_badge = (
            f'<div style="font-size:10px; color:#64748B; margin-bottom:3px; font-family:Consolas,monospace; font-weight:600;">{html.escape(lang)}</div>'
            if lang else ""
        )
        block_html = (
            f'<div style="background:{code_bg}; border:1px solid {border_col}; border-radius:8px; '
            f'padding:9px 11px; margin:6px 0; font-family:Consolas,monospace; font-size:12px; color:{code_fg}; '
            f'white-space:pre-wrap;">{lang_badge}{code}</div>'
        )
        idx = len(code_blocks)
        code_blocks.append(block_html)
        return f"@@CODEBLOCK_{idx}@@"

    text = re.sub(r"```([a-zA-Z0-9_-]*)\n(.*?)```", _save_code_block, text, flags=re.DOTALL)

    lines = text.splitlines()
    out_lines: list[str] = []
    in_table = False
    in_ul = False

    def _format_inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(
            r"`([^`]+)`",
            rf'<code style="background:{code_bg}; color:{code_fg}; border:1px solid {border_col}; padding:1px 5px; border-radius:4px; font-family:Consolas,monospace;">\1</code>',
            s,
        )
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", s)
        return s

    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if stripped.startswith("@@CODEBLOCK_") and stripped.endswith("@@"):
            if in_ul:
                out_lines.append("</ul>")
                in_ul = False
            if in_table:
                out_lines.append("</table>")
                in_table = False
            out_lines.append(stripped)
            i += 1
            continue

        if "|" in stripped and stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                i += 1
                continue
            if not in_table:
                if in_ul:
                    out_lines.append("</ul>")
                    in_ul = False
                out_lines.append(
                    f'<table cellspacing="0" cellpadding="6" style="border-collapse:collapse; border:1px solid {border_col}; margin:6px 0; width:100%; border-radius:6px;">'
                )
                out_lines.append(
                    "<tr>" + "".join(
                        f'<th style="background:{th_bg}; border:1px solid {border_col}; text-align:left; font-weight:600;">{_format_inline(c)}</th>'
                        for c in cells
                    ) + "</tr>"
                )
                in_table = True
            else:
                out_lines.append(
                    "<tr>" + "".join(
                        f'<td style="border:1px solid {border_col};">{_format_inline(c)}</td>'
                        for c in cells
                    ) + "</tr>"
                )
            i += 1
            continue
        elif in_table:
            out_lines.append("</table>")
            in_table = False

        if stripped.startswith(("- ", "* ", "• ")):
            if not in_ul:
                out_lines.append('<ul style="margin:4px 0 4px 18px; padding:0;">')
                in_ul = True
            out_lines.append(f'<li style="margin:3px 0; line-height:1.45;">{_format_inline(stripped[2:])}</li>')
            i += 1
            continue
        elif in_ul:
            out_lines.append("</ul>")
            in_ul = False

        if stripped.startswith("### "):
            out_lines.append(f'<div style="font-size:13px; font-weight:700; margin:8px 0 3px 0; color:#0F172A;">{_format_inline(stripped[4:])}</div>')
        elif stripped.startswith("## "):
            out_lines.append(f'<div style="font-size:14px; font-weight:700; margin:9px 0 4px 0; color:#0F172A;">{_format_inline(stripped[3:])}</div>')
        elif stripped.startswith("# "):
            out_lines.append(f'<div style="font-size:15px; font-weight:700; margin:10px 0 4px 0; color:#0F172A;">{_format_inline(stripped[2:])}</div>')
        elif not stripped:
            out_lines.append('<div style="height:6px;"></div>')
        else:
            out_lines.append(f'<div style="margin:2px 0; line-height:1.5;">{_format_inline(raw)}</div>')
        i += 1

    if in_ul:
        out_lines.append("</ul>")
    if in_table:
        out_lines.append("</table>")

    final_html = "\n".join(out_lines)
    for idx, block_html in enumerate(code_blocks):
        final_html = final_html.replace(f"@@CODEBLOCK_{idx}@@", block_html)

    return f'<div style="color:{text_col}; font-size:12.5px;">{final_html}</div>'
