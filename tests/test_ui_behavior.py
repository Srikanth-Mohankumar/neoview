import fitz
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from neoview.ui.main_window import MainWindow
from neoview.ui.page_item import PageItem
from neoview.ui.pdf_view import PdfView


def test_find_panel_toggle():
    win = MainWindow()
    win.show()
    QApplication.processEvents()

    assert win._search_dock.isHidden()
    win._show_find()
    QApplication.processEvents()
    assert not win._search_dock.isHidden()
    win._show_find()
    QApplication.processEvents()
    assert win._search_dock.isHidden()

    win.close()


def test_font_pick_prefers_tighter_span():
    class DummyPage:
        def get_text(self, *_args, **_kwargs):
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "bbox": (0, 0, 500, 500),
                                        "font": "NotoSans",
                                        "size": 52.0,
                                        "text": "WATERMARK",
                                    },
                                    {
                                        "bbox": (45, 45, 95, 60),
                                        "font": "BodyFont-BoldItalic",
                                        "size": 11.0,
                                        "text": "Paragraph text",
                                    },
                                ]
                            }
                        ],
                    }
                ]
            }

    item = PageItem.__new__(PageItem)
    item._fitz_page = DummyPage()

    info = item.get_text_info_at(QPointF(50, 50))
    assert info is not None
    assert info["font"] == "BodyFont-BoldItalic"
    assert info["size"] == 11.0
    assert info["style"] == "Bold + Italic"


def test_link_activation_external_uri(monkeypatch):
    view = PdfView()
    opened = []

    monkeypatch.setattr(
        "neoview.ui.pdf_view.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    view._activate_link({"link": {"kind": fitz.LINK_URI, "uri": "https://example.com"}})
    assert opened == ["https://example.com"]


def test_link_activation_internal_uri_resolve(monkeypatch):
    class DummyDoc:
        page_count = 4

        def resolve_link(self, _uri):
            return (2, 0.0, 55.0)

    class DummyPage:
        def __init__(self, y):
            self._y = y

        def pos(self):
            return QPointF(0.0, self._y)

    view = PdfView()
    view._doc = DummyDoc()
    view._pages = [DummyPage(0.0), DummyPage(120.0), DummyPage(200.0), DummyPage(300.0)]
    view._zoom = 1.0
    view.verticalScrollBar().setRange(0, 10000)

    jumps = []
    monkeypatch.setattr(view, "go_to_page", lambda idx: jumps.append(idx))

    view._activate_link({"link": {"kind": fitz.LINK_GOTO, "uri": "#dest"}})

    assert jumps == [2]
    assert view.verticalScrollBar().value() == 225


def test_link_activation_internal_page_with_tuple_target(monkeypatch):
    class DummyDoc:
        page_count = 3

    class DummyPage:
        def __init__(self, y):
            self._y = y

        def pos(self):
            return QPointF(0.0, self._y)

    view = PdfView()
    view._doc = DummyDoc()
    view._pages = [DummyPage(0.0), DummyPage(300.0), DummyPage(600.0)]
    view._zoom = 1.0
    view.verticalScrollBar().setRange(0, 10000)

    jumps = []
    monkeypatch.setattr(view, "go_to_page", lambda idx: jumps.append(idx))

    view._activate_link({"link": {"page": 1, "to": (0.0, 40.0)}})

    assert jumps == [1]
    assert view.verticalScrollBar().value() == 310


def test_link_activation_internal_page_with_y_method_target(monkeypatch):
    class DummyDoc:
        page_count = 2

    class DummyPage:
        def __init__(self, y):
            self._y = y

        def pos(self):
            return QPointF(0.0, self._y)

    class TargetPoint:
        def y(self):
            return 48.0

    view = PdfView()
    view._doc = DummyDoc()
    view._pages = [DummyPage(0.0), DummyPage(220.0)]
    view._zoom = 1.0
    view.verticalScrollBar().setRange(0, 10000)

    jumps = []
    monkeypatch.setattr(view, "go_to_page", lambda idx: jumps.append(idx))

    view._activate_link({"link": {"page": 1, "to": TargetPoint()}})

    assert jumps == [1]
    assert view.verticalScrollBar().value() == 238
