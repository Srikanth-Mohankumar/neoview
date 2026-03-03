import fitz
import time
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QWindowStateChangeEvent
from PySide6.QtWidgets import QApplication

from neoview.ui.main_window import MainWindow
from neoview.ui.page_item import PageItem
from neoview.ui.pdf_view import PdfView


def test_find_panel_toggle():
    win = MainWindow()
    win.show()
    QApplication.processEvents()

    win._search_dock.hide()
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


def test_link_activation_named_destination_uses_pdf_y_coordinates(monkeypatch):
    class DummyDoc:
        page_count = 3

        def resolve_names(self):
            return {"destA": {"page": 1, "to": (0.0, 740.0), "zoom": 0.0}}

    class DummyPage:
        def __init__(self, y):
            self._y = y
            self.page_rect = QRectF(0.0, 0.0, 595.0, 842.0)

        def pos(self):
            return QPointF(0.0, self._y)

    view = PdfView()
    view._doc = DummyDoc()
    view._pages = [DummyPage(0.0), DummyPage(900.0), DummyPage(1800.0)]
    view._zoom = 1.0
    view.verticalScrollBar().setRange(0, 10000)

    jumps = []
    monkeypatch.setattr(view, "go_to_page", lambda idx: jumps.append(idx))

    view._activate_link({"link": {"kind": fitz.LINK_NAMED, "name": "destA"}})

    # PDF y=740 on an 842pt page maps to top-origin y=102.
    assert jumps == [1]
    assert view.verticalScrollBar().value() == 972


def test_link_activation_hash_uri_uses_resolve_link_coordinates(monkeypatch):
    class DummyDoc:
        page_count = 2

        def resolve_link(self, _uri):
            return (1, 0.0, 700.0)

    class DummyPage:
        def __init__(self, y):
            self._y = y
            self.page_rect = QRectF(0.0, 0.0, 595.0, 842.0)

        def pos(self):
            return QPointF(0.0, self._y)

    view = PdfView()
    view._doc = DummyDoc()
    view._pages = [DummyPage(0.0), DummyPage(900.0)]
    view._zoom = 1.0
    view.verticalScrollBar().setRange(0, 10000)

    jumps = []
    monkeypatch.setattr(view, "go_to_page", lambda idx: jumps.append(idx))

    view._activate_link({"link": {"kind": fitz.LINK_GOTO, "uri": "#page=2&zoom=100,0,700"}})

    # Must use resolve_link y directly (no PDF-space inversion).
    assert jumps == [1]
    assert view.verticalScrollBar().value() == 1570


def test_link_activation_nameddest_key_resolves(monkeypatch):
    class DummyDoc:
        page_count = 2

        def resolve_names(self):
            return {"TargetA": {"page": 1, "to": (0.0, 800.0), "zoom": 0.0}}

    class DummyPage:
        def __init__(self, y):
            self._y = y
            self.page_rect = QRectF(0.0, 0.0, 595.0, 842.0)

        def pos(self):
            return QPointF(0.0, self._y)

    view = PdfView()
    view._doc = DummyDoc()
    view._pages = [DummyPage(0.0), DummyPage(900.0)]
    view._zoom = 1.0
    view.verticalScrollBar().setRange(0, 10000)

    jumps = []
    monkeypatch.setattr(view, "go_to_page", lambda idx: jumps.append(idx))

    view._activate_link({"link": {"kind": fitz.LINK_NAMED, "nameddest": "TargetA"}})

    # resolve_names y=800 (PDF coords) -> top-origin y=42.
    assert jumps == [1]
    assert view.verticalScrollBar().value() == 912


def test_json_settings_round_trip():
    win = MainWindow()
    payload = {"demo.pdf": {"page": 3, "zoom": 1.25}}
    win._save_json_setting("tests/session", payload)
    loaded = win._load_json_setting("tests/session", {})
    assert loaded == payload
    win.close()


def test_restore_document_session_applies_zoom_and_page(monkeypatch):
    class DummyDoc:
        page_count = 5

        def close(self):
            return None

    win = MainWindow()
    win._view._doc = DummyDoc()
    win._current_file = "/tmp/demo.pdf"
    win._document_sessions = {"/tmp/demo.pdf": {"page": 2, "zoom": 1.4}}

    applied_zoom = []
    jumps = []
    monkeypatch.setattr(
        win._view,
        "set_zoom",
        lambda z, immediate=False, zoom_mode=PdfView.ZOOM_MODE_CUSTOM: applied_zoom.append(
            (z, immediate, zoom_mode)
        ),
    )
    monkeypatch.setattr(win._view, "go_to_page", lambda p: jumps.append(p))

    restored = win._restore_document_session("/tmp/demo.pdf")
    QApplication.processEvents()

    assert restored is True
    assert applied_zoom == [(1.4, True, PdfView.ZOOM_MODE_CUSTOM)]
    assert jumps == [2]
    win.close()


def test_restore_document_session_applies_fit_width_mode(monkeypatch):
    class DummyDoc:
        page_count = 3

        def close(self):
            return None

    win = MainWindow()
    win._view._doc = DummyDoc()
    win._current_file = "/tmp/demo.pdf"
    win._document_sessions = {
        "/tmp/demo.pdf": {"page": 1, "zoom": 1.0, "zoom_mode": PdfView.ZOOM_MODE_FIT_WIDTH}
    }

    fit_calls = []
    jumps = []
    monkeypatch.setattr(win._view, "fit_width", lambda: fit_calls.append(True))
    monkeypatch.setattr(win._view, "go_to_page", lambda p: jumps.append(p))

    restored = win._restore_document_session("/tmp/demo.pdf")
    QApplication.processEvents()

    assert restored is True
    assert fit_calls == [True]
    assert jumps == [1]
    win.close()


def test_on_change_ignores_unrelated_paths(monkeypatch):
    win = MainWindow()
    win._current_file = "/tmp/active.pdf"
    win._auto_reload_enabled = True
    win._last_file_sig = (1, 100, 1)

    starts = []
    monkeypatch.setattr(win, "_file_signature", lambda _path: (2, 100, 1))
    monkeypatch.setattr(win._reload_timer, "start", lambda ms: starts.append(ms))

    win._on_change("/var/other.pdf")
    assert starts == []
    win.close()


def test_on_change_schedules_reload_for_current_file(monkeypatch):
    win = MainWindow()
    win._current_file = "/tmp/active.pdf"
    win._auto_reload_enabled = True
    win._last_file_sig = (1, 100, 1)

    starts = []
    monkeypatch.setattr(win, "_file_signature", lambda _path: (2, 100, 1))
    monkeypatch.setattr(win._reload_timer, "start", lambda ms: starts.append(ms))

    win._on_change("/tmp/active.pdf")
    assert starts == [200]
    win.close()


def test_do_reload_skips_when_file_not_modified(monkeypatch):
    win = MainWindow()
    ctx = win.current_context()
    ctx.file_path = "/tmp/demo.pdf"
    win._last_file_sig = (10, 2048, 1)

    monkeypatch.setattr("neoview.ui.main_window.os.path.exists", lambda _path: True)
    monkeypatch.setattr(win, "_file_signature", lambda _path: (10, 2048, 1))
    reload_calls = []
    monkeypatch.setattr(win.current_view(), "reload_document", lambda: reload_calls.append(True) or True)

    win._do_reload()
    assert reload_calls == []
    win.close()


def test_force_reload_runs_even_when_mtime_is_unchanged(monkeypatch):
    win = MainWindow()
    ctx = win.current_context()
    ctx.file_path = "/tmp/demo.pdf"
    win._last_file_sig = (10, 2048, 1)
    win._auto_reload_enabled = False

    monkeypatch.setattr("neoview.ui.main_window.os.path.exists", lambda _path: True)
    monkeypatch.setattr("neoview.ui.main_window.os.path.getsize", lambda _path: 2048)
    monkeypatch.setattr(win, "_file_signature", lambda _path: (10, 2048, 1))

    reload_calls = []
    monkeypatch.setattr(win.current_view(), "reload_document", lambda: reload_calls.append(True) or True)

    win._do_reload(force=True)
    assert reload_calls == [True]
    assert win._last_file_sig == (10, 2048, 1)
    win.close()


def test_toggle_fullscreen_enters_fullscreen(monkeypatch):
    win = MainWindow()
    calls = []

    monkeypatch.setattr(win, "isFullScreen", lambda: False)
    monkeypatch.setattr(win, "showFullScreen", lambda: calls.append("full"))

    win._toggle_fullscreen()
    assert calls == ["full"]
    win.close()


def test_toggle_fullscreen_exits_to_maximized_when_requested(monkeypatch):
    win = MainWindow()
    calls = []
    win._settings.setValue("window/start_state", "maximized")

    monkeypatch.setattr(win, "isFullScreen", lambda: True)
    monkeypatch.setattr(win, "showNormal", lambda: calls.append("normal"))
    monkeypatch.setattr(win, "showMaximized", lambda: calls.append("max"))

    win._toggle_fullscreen()
    assert calls == ["normal", "max"]
    win.close()


def test_enforce_maximized_geometry_reapplies_when_state_dropped(monkeypatch):
    win = MainWindow()
    calls = []

    monkeypatch.setattr(win, "isFullScreen", lambda: False)
    monkeypatch.setattr(win, "isMaximized", lambda: False)
    monkeypatch.setattr(win, "_best_available_geometry", lambda: QRect(0, 0, 1600, 900))
    monkeypatch.setattr(win, "setGeometry", lambda rect: calls.append(rect))

    win._enforce_maximized_geometry()
    assert len(calls) == 1
    assert calls[0].width() == 1600
    assert calls[0].height() == 900
    win.close()


def test_change_event_records_maximize_timestamp(monkeypatch):
    win = MainWindow()
    win._last_maximize_at = 0.0

    monkeypatch.setattr(win, "isMaximized", lambda: True)
    monkeypatch.setattr(win, "isFullScreen", lambda: False)
    event = QWindowStateChangeEvent(Qt.WindowState.WindowNoState)
    win.changeEvent(event)

    assert win._last_maximize_at > 0.0
    win.close()


def test_change_event_schedules_fallback_after_maximize_bounce(monkeypatch):
    win = MainWindow()
    win._last_maximize_at = time.monotonic()
    calls = []

    monkeypatch.setattr(win, "isMaximized", lambda: False)
    monkeypatch.setattr(win, "isFullScreen", lambda: False)
    monkeypatch.setattr(win, "_enforce_maximized_geometry", lambda: calls.append("enforce"))
    monkeypatch.setattr(
        "neoview.ui.main_window.QTimer.singleShot",
        lambda delay, cb: (calls.append(delay), cb()),
    )

    event = QWindowStateChangeEvent(Qt.WindowState.WindowMaximized)
    win.changeEvent(event)

    assert calls == [0, "enforce"]
    win.close()


def test_change_event_skips_fallback_when_bounce_window_is_old(monkeypatch):
    win = MainWindow()
    win._last_maximize_at = time.monotonic() - 2.0
    calls = []

    monkeypatch.setattr(win, "isMaximized", lambda: False)
    monkeypatch.setattr(win, "isFullScreen", lambda: False)
    monkeypatch.setattr(
        "neoview.ui.main_window.QTimer.singleShot",
        lambda delay, cb: calls.append(delay),
    )

    event = QWindowStateChangeEvent(Qt.WindowState.WindowMaximized)
    win.changeEvent(event)

    assert calls == []
    win.close()
