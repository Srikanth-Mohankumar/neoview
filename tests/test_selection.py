from PySide6.QtCore import QRectF, QPointF

from neoview.ui.selection import SelectionRect


def test_selection_clamps_to_page():
    page = QRectF(0, 0, 100, 100)
    rect = QRectF(-10, -10, 5, 5)
    sel = SelectionRect(rect, page)
    assert sel.pdf_rect.left() >= 0
    assert sel.pdf_rect.top() >= 0


def test_selection_drag_move():
    page = QRectF(0, 0, 100, 100)
    rect = QRectF(10, 10, 20, 20)
    sel = SelectionRect(rect, page)
    sel.start_drag(QPointF(10, 10), "move")
    sel.update_drag(QPointF(20, 20))
    sel.end_drag()
    assert sel.pdf_rect.x() == 20
    assert sel.pdf_rect.y() == 20


def test_clear_text_selection_after_scene_clear():
    from PySide6.QtWidgets import QGraphicsScene
    from neoview.ui.pdf_view import PdfView

    view = PdfView()
    scene = QGraphicsScene()
    view.setScene(scene)

    rect_item = scene.addRect(QRectF(0, 0, 10, 10))
    view._text_select_item = rect_item

    scene.clear()
    view.clear_text_selection()
