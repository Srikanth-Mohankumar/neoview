from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from neoview.ui.presentation import PresentationWindow

# One distinct fill colour per page so a screenshot proves which page is shown.
PAGE_COLORS = [(0.85, 0.1, 0.1), (0.1, 0.6, 0.15), (0.1, 0.2, 0.85)]


def _make_pdf(path: Path, password: str | None = None) -> Path:
    doc = fitz.open()
    for i, color in enumerate(PAGE_COLORS):
        page = doc.new_page(width=800, height=600)
        page.draw_rect(fitz.Rect(40, 40, 760, 560), color=color, fill=color)
        page.insert_text((300, 330), f"Page {i + 1}", fontsize=60, color=(1, 1, 1))
    if password:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password,
                 owner_pw=password + "!")
    else:
        doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pdf(tmp_path):
    return _make_pdf(tmp_path / "slides.pdf")


@pytest.fixture
def win(qtbot, pdf):
    w = PresentationWindow(str(pdf))
    qtbot.addWidget(w)
    w.resize(640, 480)
    w.show()
    QApplication.processEvents()
    yield w
    w.close()


def _centre_rgb(widget) -> tuple[int, int, int]:
    img = widget.grab().toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 4)
    return c.red(), c.green(), c.blue()


def _dominant(rgb) -> int:
    return max(range(3), key=lambda i: rgb[i])


def test_starts_on_requested_page_clamped(qtbot, pdf):
    w = PresentationWindow(str(pdf), start_page=9)
    qtbot.addWidget(w)
    try:
        assert w.page_count() == 3
        assert w.current_page() == 2
    finally:
        w.close()


@pytest.mark.parametrize(
    "key",
    [Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Space, Qt.Key.Key_PageDown],
)
def test_next_keys(qtbot, win, key):
    with qtbot.waitSignal(win.page_changed, timeout=1000) as blocker:
        qtbot.keyClick(win, key)
    assert blocker.args == [1]
    assert win.current_page() == 1


@pytest.mark.parametrize(
    "key",
    [Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Backspace, Qt.Key.Key_PageUp],
)
def test_previous_keys(qtbot, win, key):
    win.go_to_page(2)
    qtbot.keyClick(win, key)
    assert win.current_page() == 1


def test_home_end_and_bounds(qtbot, win):
    changes = []
    win.page_changed.connect(changes.append)
    qtbot.keyClick(win, Qt.Key.Key_End)
    assert win.current_page() == 2
    qtbot.keyClick(win, Qt.Key.Key_Right)  # already last: no change, no signal
    assert win.current_page() == 2
    qtbot.keyClick(win, Qt.Key.Key_Home)
    assert win.current_page() == 0
    qtbot.keyClick(win, Qt.Key.Key_Left)  # already first
    assert win.current_page() == 0
    assert changes == [2, 0]


def test_click_advances_and_right_click_goes_back(qtbot, win):
    qtbot.mouseClick(win, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert win.current_page() == 1
    qtbot.mouseClick(win, Qt.MouseButton.RightButton, pos=QPoint(10, 10))
    assert win.current_page() == 0


def test_page_rendering_follows_navigation(qtbot, win):
    # Red, green, blue fills on pages 1-3.
    for expected_channel in range(3):
        assert _dominant(_centre_rgb(win)) == expected_channel
        qtbot.keyClick(win, Qt.Key.Key_Right)


def test_page_is_fitted_and_centred(qtbot, win):
    img = win.page_image(0)
    dpr = win.devicePixelRatioF()
    # 800x600 page in a 640x480 window: exactly fills it (same 4:3 aspect).
    assert img.width() == pytest.approx(640 * dpr, abs=1)
    assert img.height() == pytest.approx(480 * dpr, abs=1)
    win.resize(800, 400)
    QApplication.processEvents()
    img = win.page_image(0)
    assert img.height() == pytest.approx(400 * dpr, abs=1)
    assert img.width() == pytest.approx(400 * dpr * 800 / 600, abs=1)
    grab = win.grab().toImage()
    # Left margin is black letterboxing; page edge (white border) starts after it.
    assert grab.pixelColor(5, 200).value() == 0


def test_black_screen_toggle(qtbot, win):
    assert _centre_rgb(win) != (0, 0, 0)
    qtbot.keyClick(win, Qt.Key.Key_B)
    assert win.is_black()
    assert _centre_rgb(win) == (0, 0, 0)
    qtbot.keyClick(win, Qt.Key.Key_B)
    assert not win.is_black()
    assert _centre_rgb(win) != (0, 0, 0)
    qtbot.keyClick(win, Qt.Key.Key_Period)
    assert win.is_black()
    qtbot.keyClick(win, Qt.Key.Key_Right)  # navigating un-blanks
    assert not win.is_black()
    assert win.current_page() == 1


def test_next_page_is_preloaded(qtbot, win):
    win.go_to_page(1)
    qtbot.waitUntil(lambda: 2 in win.cached_pages(), timeout=2000)
    win.repaint()
    assert 1 in win.cached_pages()


def test_escape_closes_and_reports_last_page(qtbot, win):
    win.go_to_page(1)
    with qtbot.waitSignal(win.closed, timeout=1000) as blocker:
        qtbot.keyClick(win, Qt.Key.Key_Escape)
    assert blocker.args == [1]
    assert not win.isVisible()
    assert win.page_count() == 0  # its own document was closed


def test_closed_emitted_once(qtbot, win):
    seen = []
    win.closed.connect(seen.append)
    win.close()
    win.close()
    assert seen == [0]


def test_wheel_pages(qtbot, win):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent

    def wheel(dy):
        ev = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(win, ev)

    wheel(-120)
    assert win.current_page() == 1
    wheel(120)
    assert win.current_page() == 0


def test_encrypted_document(qtbot, tmp_path):
    path = _make_pdf(tmp_path / "locked.pdf", password="pw")
    with pytest.raises(PermissionError):
        PresentationWindow(str(path))
    w = PresentationWindow(str(path), password="pw")
    qtbot.addWidget(w)
    try:
        assert w.page_count() == 3
    finally:
        w.close()


def test_present_goes_full_screen(qtbot, pdf):
    w = PresentationWindow(str(pdf))
    qtbot.addWidget(w)
    try:
        w.present()
        QApplication.processEvents()
        assert w.isVisible()
        assert w.isFullScreen()
    finally:
        w.close()
