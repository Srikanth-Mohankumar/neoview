import fitz
from PySide6.QtWidgets import QApplication

from neoview.ui.main_window import MainWindow


def make_tagged(path, role):
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        root, tag = doc.get_new_xref(), doc.get_new_xref()
        doc.update_object(root, f'<< /Type /StructTreeRoot /K [{tag} 0 R] >>')
        doc.update_object(tag, f'<< /Type /StructElem /S /{role} /P {root} 0 R '
                               f'/Pg {doc.page_xref(1)} 0 R /Alt (Accessible description) >>')
        doc.xref_set_key(doc.pdf_catalog(), 'StructTreeRoot', f'{root} 0 R')
        doc.xref_set_key(doc.pdf_catalog(), 'MarkInfo', '<< /Marked true >>')
        doc.save(str(path))


def test_tags_sidebar_follows_active_tabs_and_closing_documents(tmp_path, qtbot):
    first, second = tmp_path / 'first.pdf', tmp_path / 'second.pdf'
    make_tagged(first, 'Figure')
    make_tagged(second, 'P')
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._open_file(str(first))
    first_view = window.current_view()
    assert window._tags_panel.document is None
    window._tags_panel_action.trigger()
    assert window._sidebar.current_key() == 'tags'
    assert not window._sidebar_dock.isHidden()
    assert window._tags_panel.document is first_view.document
    qtbot.waitUntil(lambda: window._tags_panel.report is not None, timeout=10000)
    assert window._tags_panel.report.nodes[0].role == 'Figure'
    window._tags_panel.page_requested.emit(1)
    assert first_view.current_page == 1
    window._open_file(str(second))
    assert window._tags_panel.document is window.current_view().document
    qtbot.waitUntil(lambda: window._tags_panel.report is not None, timeout=10000)
    assert window._tags_panel.report.nodes[0].role == 'P'
    window._tabs.setCurrentWidget(first_view)
    qtbot.waitUntil(lambda: window._tags_panel.report is not None, timeout=10000)
    assert window._tags_panel.report.nodes[0].role == 'Figure'
    previous_document = first_view.document
    window._do_reload(force=True)
    assert first_view.document is not previous_document
    assert window._tags_panel.document is first_view.document
    qtbot.waitUntil(lambda: window._tags_panel.report is not None, timeout=10000)
    window._close_current_tab()
    qtbot.waitUntil(lambda: window._tags_panel.report is not None, timeout=10000)
    assert window._tags_panel.report.nodes[0].role == 'P'
    window._close_current_tab()
    assert window._tags_panel.document is None
    assert window._tags_panel.report is None


def test_tags_sidebar_hiding_cancels_and_selection_is_persisted(tmp_path, qtbot):
    path = tmp_path / 'source.pdf'
    make_tagged(path, 'P')
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._open_file(str(path))
    window._tags_panel_action.trigger()
    assert window._settings.value('window/sidebar_page') == 'tags'
    window._set_sidebar_visible(False)
    assert window._tags_panel.document is None
    window._tags_panel_action.trigger()
    assert window._tags_panel.document is window.current_view().document
    window._show_sidebar_page('outline')
    assert window._tags_panel.document is None
    QApplication.processEvents()
