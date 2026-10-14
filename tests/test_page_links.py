"""Page links are read lazily, on first hover, not for every page at open."""

from __future__ import annotations

import fitz
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from neoview.ui.pdf_view import PdfView


def test_links_are_read_on_demand(tmp_path, monkeypatch):
    pdf = tmp_path / "links.pdf"
    doc = fitz.open()
    for _ in range(5):
        doc.new_page(width=400, height=600)
    link_rect = fitz.Rect(50, 50, 150, 80)
    doc[3].insert_link({"kind": fitz.LINK_URI, "from": link_rect, "uri": "https://example.com"})
    doc.save(str(pdf))
    doc.close()

    calls: list[int] = []
    real_get_links = fitz.Page.get_links

    def counting_get_links(page, *args, **kwargs):
        calls.append(page.number)
        return real_get_links(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_links", counting_get_links)

    view = PdfView()
    view.resize(800, 600)
    view.show()
    QApplication.processEvents()
    try:
        assert view.open_document(str(pdf))
        QApplication.processEvents()
        assert calls == []  # opening reads no page's links

        page = view._pages[3]
        centre = link_rect.tl + (link_rect.br - link_rect.tl) * 0.5
        scene_pos = page.pos() + QPointF(centre.x, centre.y) * view.zoom
        hit = view._link_at_scene_pos(scene_pos)
        assert hit is not None and hit["page_idx"] == 3
        assert hit["link"]["uri"] == "https://example.com"
        view._link_at_scene_pos(scene_pos)
        assert calls == [3]  # read once, then cached
    finally:
        view.close_document()
        view.close()
