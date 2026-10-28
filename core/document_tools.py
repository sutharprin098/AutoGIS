from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from typing import Any

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024.0:.1f} KB"
    return f"{num_bytes / (1024.0 * 1024.0):.2f} MB"


def _decode_pdf_literal(raw: bytes) -> str:
    """Decode PDF literal strings (...) and hex strings <...>."""
    out: list[str] = []
    # Literal strings (...)
    for m in re.finditer(rb"\(([^()\\]*(?:\\.[^()\\]*)*)\)", raw):
        s = m.group(1)
        s = (
            s.replace(rb"\n", b"\n")
            .replace(rb"\r", b" ")
            .replace(rb"\t", b" ")
            .replace(rb"\(", b"(")
            .replace(rb"\)", b")")
            .replace(rb"\\", b"\\")
        )
        out.append(s.decode("latin-1", errors="ignore"))
    return " ".join(x.strip() for x in out if x.strip())


def _extract_pdf_builtin_stream(path: str, max_chars: int = 18000, search_query: str = "") -> dict[str, Any]:
    """Pure-Python streaming PDF text extractor (handles uncompressed & FlateDecode streams on large PDFs)."""
    file_size = os.path.getsize(path)
    # Read up to 25 MB chunked so even 500 MB PDFs never freeze QGIS
    max_scan_bytes = min(file_size, 25 * 1024 * 1024)
    with open(path, "rb") as fh:
        raw_data = fh.read(max_scan_bytes)

    page_count_est = len(re.findall(rb"/Type\s*/Page\b", raw_data))
    extracted_chunks: list[str] = []
    total_chars = 0
    q_lower = search_query.strip().lower()

    for m in re.finditer(rb"stream[\r\n]+(.*?)[\r\n]+endstream", raw_data, flags=re.DOTALL):
        stream_bytes = m.group(1)
        decomp = None
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                decomp = zlib.decompress(stream_bytes, wbits)
                break
            except Exception:
                continue
        if decomp is None:
            decomp = stream_bytes

        if b"BT" not in decomp and b"(" not in decomp:
            continue

        # Extract text blocks between BT and ET
        bt_blocks = re.findall(rb"BT(.*?)ET", decomp, flags=re.DOTALL)
        if not bt_blocks:
            bt_blocks = [decomp]

        block_texts: list[str] = []
        for blk in bt_blocks:
            txt = _decode_pdf_literal(blk)
            if txt:
                block_texts.append(txt)

        if block_texts:
            combined = "\n".join(block_texts)
            if q_lower and q_lower not in combined.lower():
                continue
            extracted_chunks.append(combined)
            total_chars += len(combined)
            if total_chars >= max_chars:
                break

    full_text = "\n\n".join(extracted_chunks)[:max_chars]
    return {
        "engine": "builtin_stream_pdf",
        "file_size": _format_size(file_size),
        "estimated_pages": max(1, page_count_est),
        "extracted_chars": len(full_text),
        "text_preview": full_text or "(Note: This PDF appears to contain scanned raster/vector graphics or GeoPDF map layers rather than plain text streams. You can load it onto the QGIS canvas with load_geopdf_to_map=True.)",
    }


def extract_pdf_content(
    path: str,
    start_page: int = 1,
    end_page: int = 15,
    search_query: str = "",
    max_chars: int = 18000,
) -> dict[str, Any]:
    """Extract text, page count, and geospatial metadata from any PDF (including large PDFs)."""
    if not os.path.exists(path):
        return {"error": f"PDF file not found: {path}"}

    file_size = os.path.getsize(path)
    q_lower = search_query.strip().lower()

    # 1. Try PyMuPDF (fitz) if available
    try:
        import fitz  # type: ignore
        doc = fitz.open(path)
        total_pages = len(doc)
        s_idx = max(0, start_page - 1)
        e_idx = min(total_pages, max(s_idx + 1, end_page))
        pages_out = []
        chars = 0
        scan_range = range(total_pages) if q_lower else range(s_idx, e_idx)
        for pno in scan_range:
            ptxt = doc[pno].get_text("text") or ""
            if q_lower and q_lower not in ptxt.lower():
                continue
            pages_out.append(f"--- [Page {pno + 1}/{total_pages}] ---\n{ptxt.strip()}")
            chars += len(ptxt)
            if chars >= max_chars:
                break
        doc.close()
        return {
            "engine": "PyMuPDF",
            "file_size": _format_size(file_size),
            "total_pages": total_pages,
            "pages_returned": len(pages_out),
            "text_preview": "\n\n".join(pages_out)[:max_chars],
        }
    except Exception:
        pass

    # 2. Try pypdf / PyPDF2 if available
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            pdf_mod = __import__(mod_name)
            reader = pdf_mod.PdfReader(path)
            total_pages = len(reader.pages)
            s_idx = max(0, start_page - 1)
            e_idx = min(total_pages, max(s_idx + 1, end_page))
            pages_out = []
            chars = 0
            scan_range = range(total_pages) if q_lower else range(s_idx, e_idx)
            for pno in scan_range:
                ptxt = reader.pages[pno].extract_text() or ""
                if q_lower and q_lower not in ptxt.lower():
                    continue
                pages_out.append(f"--- [Page {pno + 1}/{total_pages}] ---\n{ptxt.strip()}")
                chars += len(ptxt)
                if chars >= max_chars:
                    break
            return {
                "engine": mod_name,
                "file_size": _format_size(file_size),
                "total_pages": total_pages,
                "pages_returned": len(pages_out),
                "text_preview": "\n\n".join(pages_out)[:max_chars],
            }
        except Exception:
            continue

    # 3. Pure-Python Streaming Extractor + GDAL PDF Metadata Inspection
    res = _extract_pdf_builtin_stream(path, max_chars=max_chars, search_query=search_query)
    try:
        from osgeo import gdal
        ds = gdal.Open(path)
        if ds is not None:
            res["gdal_geopdf"] = {
                "width": ds.RasterXSize,
                "height": ds.RasterYSize,
                "bands": ds.RasterCount,
                "projection": ds.GetProjection() or None,
                "subdatasets": [s[0] for s in (ds.GetSubDatasets() or [])[:10]],
                "metadata": ds.GetMetadata() or {},
            }
    except Exception:
        pass
    return res


def extract_docx_content(path: str, max_chars: int = 16000) -> dict[str, Any]:
    """Extract text from .docx Word documents using built-in zipfile + XML."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        paragraphs: list[str] = []
        for elem in root.iter():
            if elem.tag.endswith("}p"):
                texts = [t.text for t in elem.iter() if t.tag.endswith("}t") and t.text]
                if texts:
                    paragraphs.append("".join(texts))
        joined = "\n".join(paragraphs)[:max_chars]
        return {
            "type": "docx",
            "file_size": _format_size(os.path.getsize(path)),
            "paragraphs": len(paragraphs),
            "text_preview": joined,
        }
    except Exception as exc:
        return {"error": f"Could not read DOCX file: {exc}"}


def extract_xlsx_content(path: str, max_rows: int = 50) -> dict[str, Any]:
    """Extract sheets and sample rows from .xlsx Excel files using built-in zipfile + XML."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in ss_root.iter():
                    if si.tag.endswith("}si"):
                        parts = [t.text for t in si.iter() if t.tag.endswith("}t") and t.text]
                        shared_strings.append("".join(parts))

            sheets = [n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
            sheets.sort()
            rows_preview: list[list[str]] = []
            if sheets:
                sh_root = ET.fromstring(zf.read(sheets[0]))
                for row_el in sh_root.iter():
                    if row_el.tag.endswith("}row"):
                        row_vals: list[str] = []
                        for c_el in row_el:
                            if not c_el.tag.endswith("}c"):
                                continue
                            c_type = c_el.attrib.get("t", "")
                            v_text = ""
                            for ch in c_el:
                                if ch.tag.endswith("}v") and ch.text:
                                    v_text = ch.text
                                elif ch.tag.endswith("}is"):
                                    v_text = "".join(t.text for t in ch.iter() if t.tag.endswith("}t") and t.text)
                            if c_type == "s" and v_text.isdigit():
                                idx = int(v_text)
                                if 0 <= idx < len(shared_strings):
                                    v_text = shared_strings[idx]
                            row_vals.append(v_text)
                        if any(row_vals):
                            rows_preview.append(row_vals)
                        if len(rows_preview) >= max_rows:
                            break
        return {
            "type": "xlsx",
            "file_size": _format_size(os.path.getsize(path)),
            "sheet_count": len(sheets),
            "sample_rows": rows_preview,
        }
    except Exception as exc:
        return {"error": f"Could not parse XLSX file: {exc}"}


def summarize_attached_path(path: str, max_chars: int = 6000) -> str:
    """Create a rich, safe summary of ANY attached file or folder for the AI prompt."""
    if not os.path.exists(path):
        return f"- `{path}` (File not found)"

    if os.path.isdir(path):
        gis_files, pdf_files, tabular_files, other_files = [], [], [], []
        for root, _, files in os.walk(path):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), path)
                ext = os.path.splitext(f)[1].lower()
                if ext in (".shp", ".gpkg", ".geojson", ".kml", ".gml", ".tif", ".tiff", ".dem", ".laz", ".las"):
                    gis_files.append(rel)
                elif ext == ".pdf":
                    pdf_files.append(rel)
                elif ext in (".csv", ".tsv", ".xlsx", ".xls", ".json"):
                    tabular_files.append(rel)
                else:
                    other_files.append(rel)
        return (
            f"📁 **Attached Folder**: `{path}`\n"
            f"  - GIS Layers ({len(gis_files)}): {gis_files[:20]}\n"
            f"  - PDFs ({len(pdf_files)}): {pdf_files[:15]}\n"
            f"  - Tabular/Spreadsheets ({len(tabular_files)}): {tabular_files[:15]}\n"
            f"  - Other Files ({len(other_files)}): {other_files[:15]}"
        )

    size_str = _format_size(os.path.getsize(path))
    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        info = extract_pdf_content(path, start_page=1, end_page=8, max_chars=max_chars)
        preview = info.get("text_preview", "")
        pages = info.get("total_pages") or info.get("estimated_pages") or "?"
        return (
            f"📄 **Attached PDF Document**: `{path}` ({size_str}, ~{pages} pages)\n"
            f"  *(Use `read_uploaded_file_or_pdf` tool to read more pages, search keywords, or load as GeoPDF layer)*\n"
            f"  **Extracted Preview**:\n```text\n{preview[:max_chars]}\n```"
        )

    if ext == ".docx":
        info = extract_docx_content(path, max_chars=max_chars)
        return f"📝 **Attached Word Document**: `{path}` ({size_str})\n```text\n{info.get('text_preview', '')}\n```"

    if ext in (".xlsx", ".xls"):
        info = extract_xlsx_content(path, max_rows=25)
        return f"📊 **Attached Excel Spreadsheet**: `{path}` ({size_str})\n```json\n{json.dumps(info.get('sample_rows', [])[:15], ensure_ascii=False)}\n```"

    if ext in (".csv", ".tsv"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = [fh.readline().strip() for _ in range(15)]
            preview = "\n".join(x for x in lines if x)
            return f"📊 **Attached CSV/TSV**: `{path}` ({size_str})\n```csv\n{preview[:max_chars]}\n```"
        except Exception:
            pass

    if ext in (".txt", ".md", ".py", ".sql", ".json", ".geojson", ".kml", ".xml", ".yaml", ".yml", ".ini", ".log"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                snippet = fh.read(max_chars)
            return f"📄 **Attached File**: `{path}` ({size_str})\n```text\n{snippet}\n```"
        except Exception:
            pass

    return f"🗺️ **Attached Spatial/Media File**: `{path}` ({size_str}, type `{ext}` — can be loaded via `load_dataset` or `read_uploaded_file_or_pdf`)"


def tool_read_uploaded_file_or_pdf(iface, args: dict) -> dict:
    """Universal tool for the AI Agent to read/search large PDFs, Word docs, Excel sheets, CSVs, folders, or load GeoPDFs."""
    path = str(args.get("path") or "").strip()
    if not path or not os.path.exists(path):
        return {"error": f"File or folder not found: '{path}'"}

    if os.path.isdir(path):
        return {"path": path, "summary": summarize_attached_path(path, max_chars=12000)}

    ext = os.path.splitext(path)[1].lower()
    start_page = max(1, int(args.get("start_page") or 1))
    end_page = max(start_page, int(args.get("end_page") or (start_page + 14)))
    search_query = str(args.get("search_query") or "").strip()
    load_to_map = bool(args.get("load_geopdf_to_map", False))

    if ext == ".pdf":
        res = extract_pdf_content(
            path,
            start_page=start_page,
            end_page=end_page,
            search_query=search_query,
            max_chars=18000,
        )
        if load_to_map:
            lname = os.path.splitext(os.path.basename(path))[0]
            rlyr = QgsRasterLayer(path, lname)
            if rlyr.isValid():
                QgsProject.instance().addMapLayer(rlyr)
                res["loaded_map_layer"] = {"id": rlyr.id(), "name": rlyr.name(), "type": "raster_geopdf"}
            else:
                vlyr = QgsVectorLayer(path, lname, "ogr")
                if vlyr.isValid():
                    QgsProject.instance().addMapLayer(vlyr)
                    res["loaded_map_layer"] = {"id": vlyr.id(), "name": vlyr.name(), "type": "vector_geopdf"}
        return res

    if ext == ".docx":
        return extract_docx_content(path, max_chars=18000)

    if ext in (".xlsx", ".xls"):
        return extract_xlsx_content(path, max_rows=80)

    # Generic text / CSV / JSON / script reader with optional search filter
    file_size = os.path.getsize(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if search_query:
                q_low = search_query.lower()
                matches = []
                for idx, line in enumerate(fh, 1):
                    if q_low in line.lower():
                        matches.append(f"L{idx}: {line.rstrip()[:300]}")
                        if len(matches) >= 80:
                            break
                return {
                    "path": path,
                    "file_size": _format_size(file_size),
                    "search_query": search_query,
                    "matches_count": len(matches),
                    "matches": "\n".join(matches),
                }
            else:
                offset = max(0, (start_page - 1) * 8000)
                fh.seek(offset)
                content = fh.read(16000)
                return {
                    "path": path,
                    "file_size": _format_size(file_size),
                    "offset": offset,
                    "content": content,
                }
    except Exception as exc:
        return {"error": f"Could not read file '{path}': {exc}"}
