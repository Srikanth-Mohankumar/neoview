"""Read annotations embedded in a PDF and write sidecar annotations back into a copy.

Pure document work (PyMuPDF + data records); no widgets. MainWindow calls these from the
open/reload path and from "Export PDF with Annotations".
"""

from __future__ import annotations

import fitz
from PySide6.QtGui import QColor

from neoview.models.view_state import AnnotationRecord

# PyMuPDF annotation type -> NeoView annotation type.
_FITZ_TYPE_MAP = {
    fitz.PDF_ANNOT_HIGHLIGHT: "highlight",
    fitz.PDF_ANNOT_UNDERLINE: "underline",
    fitz.PDF_ANNOT_SQUIGGLY: "underline",
    fitz.PDF_ANNOT_STRIKE_OUT: "strikethrough",
    fitz.PDF_ANNOT_TEXT: "note",
    fitz.PDF_ANNOT_FREE_TEXT: "text-box",
    fitz.PDF_ANNOT_SQUARE: "rectangle",
    fitz.PDF_ANNOT_CIRCLE: "ellipse",
    fitz.PDF_ANNOT_LINE: "line",
    fitz.PDF_ANNOT_INK: "freehand",
    fitz.PDF_ANNOT_POLYGON: "rectangle",
    fitz.PDF_ANNOT_POLY_LINE: "line",
    fitz.PDF_ANNOT_STAMP: "rectangle",
}


def page_may_have_annots(doc: fitz.Document, page_idx: int) -> bool:
    """Cheap check of a page's /Annots entry without loading the page.

    Returns True when the page might carry annotations (or when the check itself
    fails, e.g. a non-PDF document), so callers fall back to loading the page.
    """
    try:
        kind, _value = doc.xref_get_key(doc.page_xref(page_idx), "Annots")
    except Exception:
        return True
    return kind != "null"


def load_native_annotations(doc: fitz.Document | None) -> list[AnnotationRecord]:
    """Return the annotations embedded in ``doc`` (e.g. made in Acrobat) as read-only records."""
    native: list[AnnotationRecord] = []
    if not doc:
        return native

    try:
        for page_idx in range(doc.page_count):
            # Loading every page just to ask for its annotations cost ~0.1 ms
            # per page (0.55 s on a 4963-page PDF, on the GUI thread, during
            # open). The page dictionary's /Annots key answers "has none"
            # without building a Page, so only annotated pages get loaded.
            if not page_may_have_annots(doc, page_idx):
                continue
            page = doc[page_idx]
            for ann in page.annots():
                ann_type = ann.type[0]
                mapped = _FITZ_TYPE_MAP.get(ann_type)
                if mapped is None:
                    continue
                r = ann.rect
                color_tuple = ann.colors.get("stroke") or ann.colors.get("fill") or (1.0, 0.8, 0.0)
                hex_color = "#{:02x}{:02x}{:02x}".format(
                    int(color_tuple[0] * 255),
                    int(color_tuple[1] * 255),
                    int(color_tuple[2] * 255),
                )
                info = ann.info
                contents = info.get("content", "") or ""
                native.append(
                    AnnotationRecord(
                        id=f"native-{page_idx}-{len(native)}",
                        type=mapped,
                        page=page_idx,
                        rect=(r.x0, r.y0, r.width, r.height),
                        color=hex_color,
                        opacity=ann.opacity if ann.opacity is not None else 0.4,
                        contents=contents,
                    )
                )
    except Exception:
        pass
    return native


def export_annotated_pdf(src: str, annotations: list[AnnotationRecord], out_path: str) -> None:
    """Write a copy of ``src`` to ``out_path`` with ``annotations`` embedded as PDF annotations.

    Raises on I/O or parse errors; per-annotation styling failures are ignored so one odd
    record does not abort the export.
    """
    doc = fitz.open(src)
    try:
        for ann_rec in annotations:
            if not (0 <= ann_rec.page < doc.page_count):
                continue
            page = doc[ann_rec.page]
            x, y, w, h = ann_rec.rect
            rect = fitz.Rect(x, y, x + w, y + h)
            color_obj = QColor(ann_rec.color or "#f7c948")
            rgb = (color_obj.redF(), color_obj.greenF(), color_obj.blueF())

            # Resolve border/stroke color
            if ann_rec.border_color:
                bc_obj = QColor(ann_rec.border_color)
                stroke_rgb = (bc_obj.redF(), bc_obj.greenF(), bc_obj.blueF())
            else:
                stroke_rgb = rgb

            t = ann_rec.type
            if t == "highlight":
                a = page.add_highlight_annot(rect)
            elif t == "underline":
                a = page.add_underline_annot(rect)
            elif t == "strikethrough":
                a = page.add_strikeout_annot(rect)
            elif t in ("note",):
                a = page.add_text_annot(fitz.Point(x, y), ann_rec.contents or "")
            elif t == "text-box":
                a = page.add_freetext_annot(rect, ann_rec.contents or "", fontsize=ann_rec.font_size, text_color=rgb)
            elif t == "rectangle":
                a = page.add_rect_annot(rect)
            elif t == "ellipse":
                a = page.add_circle_annot(rect)
            elif t == "line":
                a = page.add_line_annot(fitz.Point(x, y), fitz.Point(x + w, y + h))
            elif t == "arrow":
                a = page.add_line_annot(fitz.Point(x, y), fitz.Point(x + w, y + h))
            elif t == "freehand" and ann_rec.points:
                pts = [(p[0], p[1]) for p in ann_rec.points]
                a = page.add_ink_annot([pts])
            else:
                continue

            try:
                # Apply colors per annotation type
                if t in ("highlight", "underline", "strikethrough"):
                    # Text markup: only color matters (no stroke/fill distinction)
                    a.set_colors(stroke=rgb)
                elif t in ("rectangle", "ellipse"):
                    # Shapes: stroke = border_color, fill = color
                    a.set_colors(stroke=stroke_rgb, fill=rgb)
                elif t in ("line", "arrow", "freehand"):
                    # Lines/paths: stroke only
                    a.set_colors(stroke=stroke_rgb)
                elif t == "note":
                    a.set_colors(fill=rgb)
                elif t == "text-box":
                    pass  # colors set via add_freetext_annot params
                else:
                    a.set_colors(stroke=rgb, fill=rgb)

                a.set_opacity(ann_rec.opacity)

                # Apply border width for shapes, lines, and freehand
                if t in ("rectangle", "ellipse", "line", "arrow", "freehand"):
                    a.set_border(width=ann_rec.border_width)

                # Arrow line ending
                if t == "arrow":
                    a.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)

                if ann_rec.contents and t not in ("note", "text-box", "freehand"):
                    a.set_info(content=ann_rec.contents)
                a.update()
            except Exception:
                pass

        doc.save(out_path, garbage=4, deflate=True)
    finally:
        doc.close()
