"""The inspection UI presents a snapshot and emits safe zero-based navigation."""
from types import SimpleNamespace

import fitz
from PySide6.QtCore import Qt

import neoview.ui.tagged_pdf as tagged_ui


def _node(**kwargs):
    values = dict(xref=10, role="P", mapped_role="P", title="", alt_text="", actual_text="",
                  language="", page=0, mcids=[0], children=[])
    values.update(kwargs)
    if "mapped_role" not in kwargs:
        values["mapped_role"] = values["role"]
    return SimpleNamespace(**values)


def _report(**kwargs):
    values = dict(tagged=True, language="en-US", nodes=[], reading_order=[], warnings=[],
                  artifacts=[], limitations="Page streams only; not a compliance certification.")
    values.update(kwargs)
    return SimpleNamespace(**values)


def _dialog(qtbot, monkeypatch, report):
    monkeypatch.setattr(tagged_ui, "inspect_tagged_pdf", lambda doc: report)
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        dialog = tagged_ui.TaggedPdfDialog(doc)
    qtbot.addWidget(dialog)
    return dialog


def test_tags_properties_order_and_navigation_are_snapshot(qtbot, monkeypatch):
    child = _node(role="Figure", alt_text="A caf\u00e9", actual_text="replacement", language="fr",
                  page=1, mcids=[4, 5])
    parent = _node(role="Custom", mapped_role="Sect", title="Introduction", children=[child])
    report = _report(nodes=[parent], reading_order=[parent, child])
    dialog = _dialog(qtbot, monkeypatch, report)
    assert dialog.tags.topLevelItemCount() == 1
    root = dialog.tags.topLevelItem(0)
    assert root.text(0) == "Custom -> Sect"
    assert root.child(0).text(1) == "2"
    assert "Alt: A caf\u00e9" in root.child(0).text(3)
    assert "ActualText: replacement" in root.child(0).text(3)
    assert "Lang: fr" in root.child(0).text(3)
    assert dialog.order.topLevelItem(1).text(1) == "Figure"
    dialog.tags.setCurrentItem(root.child(0))
    assert dialog.go_to_page.isEnabled()
    with qtbot.waitSignal(dialog.page_requested) as signal:
        dialog.go_to_page.click()
    assert signal.args == [1]
    assert not hasattr(dialog, "document")


def test_findings_artifacts_and_absent_tags(qtbot, monkeypatch):
    report = _report(tagged=False, language="", warnings=["Missing document language"],
                     artifacts=[SimpleNamespace(page=1, count=3)])
    dialog = _dialog(qtbot, monkeypatch, report)
    assert "Marked as tagged: No" in dialog.summary.text()
    assert "Not specified" in dialog.summary.text()
    assert dialog.tags.topLevelItem(0).text(0) == "No structure tags found"
    assert dialog.checks.topLevelItem(0).text(0) == "Missing document language"
    assert dialog.artifacts.topLevelItem(0).text(1) == "3"
    dialog.tabs.setCurrentIndex(2)
    item = dialog.artifacts.topLevelItem(0)
    dialog.artifacts.setCurrentItem(item)
    with qtbot.waitSignal(dialog.page_requested) as signal:
        dialog.artifacts.itemActivated.emit(item, 0)
    assert signal.args == [1]


def test_invalid_or_missing_page_cannot_navigate(qtbot, monkeypatch):
    nodes = [_node(page=None), _node(page=20), _node(page=-1)]
    dialog = _dialog(qtbot, monkeypatch, _report(nodes=nodes, reading_order=nodes))
    emitted = []
    dialog.page_requested.connect(emitted.append)
    for index in range(len(nodes)):
        item = dialog.tags.topLevelItem(index)
        dialog.tags.setCurrentItem(item)
        assert not dialog.go_to_page.isEnabled()
        assert item.data(0, Qt.ItemDataRole.UserRole) is None
        dialog.tags.itemActivated.emit(item, 0)
    assert emitted == []
    assert "Manual review" in dialog.checks.topLevelItem(0).text(0)


def test_switching_tabs_uses_current_selection(qtbot, monkeypatch):
    node = _node(page=1)
    dialog = _dialog(qtbot, monkeypatch, _report(nodes=[node], reading_order=[node]))
    dialog.tags.setCurrentItem(dialog.tags.topLevelItem(0))
    assert dialog.go_to_page.isEnabled()
    dialog.tabs.setCurrentIndex(1)
    assert not dialog.go_to_page.isEnabled()
    dialog.order.setCurrentItem(dialog.order.topLevelItem(0))
    with qtbot.waitSignal(dialog.page_requested) as signal:
        dialog.go_to_page.click()
    assert signal.args == [1]


def test_real_tagged_pdf_backend_integration(qtbot):
    with fitz.open() as doc:
        page = doc.new_page()
        root = doc.get_new_xref()
        tag = doc.get_new_xref()
        doc.update_object(root, f"<< /Type /StructTreeRoot /K [{tag} 0 R] >>")
        doc.update_object(tag, f"<< /Type /StructElem /S /H1 /P {root} 0 R "
                          f"/Pg {page.xref} 0 R /K 3 /T (Heading) >>")
        catalog = doc.pdf_catalog()
        doc.xref_set_key(catalog, "StructTreeRoot", f"{root} 0 R")
        doc.xref_set_key(catalog, "MarkInfo", "<< /Marked true >>")
        doc.xref_set_key(catalog, "Lang", "(en-US)")
        before = [doc.xref_object(xref) for xref in range(1, doc.xref_length())]
        dialog = tagged_ui.TaggedPdfDialog(doc)
        qtbot.addWidget(dialog)
        assert dialog.tags.topLevelItem(0).text(0) == "H1"
        assert dialog.order.topLevelItem(0).text(3) == "3"
        assert [doc.xref_object(xref) for xref in range(1, doc.xref_length())] == before
    with qtbot.waitSignal(dialog.page_requested) as signal:
        dialog.tags.itemActivated.emit(dialog.tags.topLevelItem(0), 0)
    assert signal.args == [0]


def test_export_report_contains_snapshot_and_limits(qtbot, monkeypatch, tmp_path):
    import json

    from neoview.models.tagged_pdf import TaggedPdfReport
    from neoview.ui import tool_support

    report = TaggedPdfReport(language="fr", warnings=["Review order manually"])
    monkeypatch.setattr(tagged_ui, "inspect_tagged_pdf", lambda document: report)
    with fitz.open() as doc:
        doc.new_page()
        dialog = tagged_ui.TaggedPdfDialog(doc)
    qtbot.addWidget(dialog)
    target = tmp_path / "inspection.json"
    monkeypatch.setattr(tool_support, "choose_file", lambda *args: str(target))
    dialog.export_report.click()
    output = json.loads(target.read_text(encoding="utf-8"))
    assert output["language"] == "fr"
    assert output["warnings"] == ["Review order manually"]
    assert "not a PDF/UA" in output["limitations"]


def test_export_report_protects_pdf_source(qtbot, monkeypatch, tmp_path):
    from neoview.ui import tool_support

    path = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    before = path.read_bytes()
    with fitz.open(path) as doc:
        dialog = tagged_ui.TaggedPdfDialog(doc)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(tool_support, "choose_file", lambda *args: str(path))
    errors = []
    monkeypatch.setattr(tagged_ui.QMessageBox, "warning", lambda *args: errors.append(args[-1]))
    dialog.export_report.click()
    assert errors and "separate" in errors[0]
    assert path.read_bytes() == before
