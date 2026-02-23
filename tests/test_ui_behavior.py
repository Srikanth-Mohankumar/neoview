from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from neoview.ui.main_window import MainWindow
from neoview.ui.page_item import PageItem


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
