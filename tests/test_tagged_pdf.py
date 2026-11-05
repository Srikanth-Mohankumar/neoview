"""Synthetic object fixtures exercise declared structure independently of visuals."""
import fitz

from neoview.models.tagged_pdf import inspect_tagged_pdf


def _object(doc, source):
    xref = doc.get_new_xref()
    doc.update_object(xref, source)
    return xref


def _fixture():
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    catalog = doc.pdf_catalog()
    doc.xref_set_key(catalog, "Lang", "(en-US)")
    doc.xref_set_key(catalog, "MarkInfo", "<< /Marked true >>")
    parent = _object(doc, "<< /Type /StructElem /S /Document >>")
    paragraph = _object(doc, "<< /Type /StructElem /S /Custom /K [3 1] /ActualText (A\\(B\\)) >>")
    figure = _object(doc, "<< /Type /StructElem /S /Figure /Alt <FEFF00480069> >>")
    doc.xref_set_key(parent, "Pg", f"{doc.page_xref(1)} 0 R")
    doc.xref_set_key(parent, "K", f"[{paragraph} 0 R {figure} 0 R]")
    root = _object(doc, f"<< /Type /StructTreeRoot /K {parent} 0 R /RoleMap << /Custom /P >> >>")
    doc.xref_set_key(catalog, "StructTreeRoot", f"{root} 0 R")
    return doc, root, parent, paragraph, figure


def test_structure_order_metadata_and_no_mutation():
    doc, _, _, _, _ = _fixture()
    before = [doc.xref_object(i) for i in range(1, doc.xref_length())]
    report = inspect_tagged_pdf(doc)
    assert report.tagged
    assert report.language == "en-US"
    assert [n.role for n in report.reading_order] == ["Document", "Custom", "Figure"]
    paragraph = report.nodes[0].children[0]
    assert paragraph.mapped_role == "P"
    assert paragraph.page == 1
    assert paragraph.mcids == [3, 1]
    assert paragraph.actual_text == "A(B)"
    assert report.nodes[0].children[1].alt_text == "Hi"
    assert [doc.xref_object(i) for i in range(1, doc.xref_length())] == before
    doc.close()


def test_direct_dictionaries_and_indirect_arrays_and_mcid_references():
    doc, root, parent, _, _ = _fixture()
    children = _object(doc, f"[<< /S /P /K << /Type /MCR /Pg {doc.page_xref(0)} 0 R /MCID 7 >> >>]")
    doc.xref_set_key(parent, "K", f"{children} 0 R")
    report = inspect_tagged_pdf(doc)
    assert len(report.reading_order) == 2
    assert report.nodes[0].children[0].mcids == [7]
    assert report.nodes[0].children[0].page == 1  # inherited structural page
    doc.xref_set_key(root, "K", "[<< /S /P /K 4 >>]")
    assert inspect_tagged_pdf(doc).nodes[0].mcids == [4]
    doc.close()


def test_cycles_and_limits_warn_without_crashing():
    doc, _, parent, paragraph, _ = _fixture()
    doc.xref_set_key(paragraph, "K", f"{parent} 0 R")
    report = inspect_tagged_pdf(doc)
    assert any("cyclic" in message for message in report.warnings)
    report = inspect_tagged_pdf(doc, max_nodes=1, max_pages=1)
    assert len(report.reading_order) == 1
    assert any("limit" in message for message in report.warnings)
    doc.close()


def test_artifact_lexer_excludes_strings_comments_hex_and_escaped_names():
    doc = fitz.open()
    page = doc.new_page()
    stream = _object(doc, "<< >>")
    doc.update_stream(stream, b'''% /Artifact BMC
(/Artifact BMC) Tj
<2f417274696661637420424d43> Tj
/Artifact BMC EMC
/Artifact << /Type /Pagination >> BDC EMC
/Arti#66act BMC EMC
/P << /ActualText (/Artifact BMC) >> BDC EMC
''')
    page.set_contents(stream)
    report = inspect_tagged_pdf(doc)
    assert report.artifacts[0].count == 3
    assert not report.tagged
    assert any("No structure" in message for message in report.warnings)
    doc.close()


def test_inline_images_are_explicitly_partial():
    doc = fitz.open()
    page = doc.new_page()
    stream = _object(doc, "<< >>")
    doc.update_stream(stream, b"/Artifact BMC EMC BI /W 1 /H 1 ID /Artifact BMC EI")
    page.set_contents(stream)
    report = inspect_tagged_pdf(doc)
    assert report.artifacts[0].count == 1
    assert any("partial" in message for message in report.warnings)
    doc.close()


def test_missing_figure_alt_and_custom_role_cycle_are_review_findings():
    doc, root, _, _, figure = _fixture()
    doc.xref_set_key(figure, "Alt", "null")
    doc.xref_set_key(root, "RoleMap", "<< /Custom /Another /Another /Custom >>")
    report = inspect_tagged_pdf(doc)
    assert any("Figure" in message for message in report.warnings)
    assert any("role mapping" in message for message in report.warnings)
    doc.close()


def test_indirect_scalar_mcid_and_root_array_and_inherited_language():
    doc, root, parent, paragraph, _ = _fixture()
    scalar = _object(doc, "12")
    array = _object(doc, f"[{parent} 0 R]")
    doc.xref_set_key(root, "K", f"{array} 0 R")
    doc.xref_set_key(parent, "Lang", "(de-DE)")
    doc.xref_set_key(paragraph, "K", f"{scalar} 0 R")
    report = inspect_tagged_pdf(doc)
    assert report.reading_order[1].mcids == [12]
    assert report.reading_order[1].language == "de-DE"
    doc.close()


def test_pdfdocencoding_and_mixed_content_pages_are_explicit():
    doc, _, _, paragraph, _ = _fixture()
    doc.xref_set_key(paragraph, "ActualText", "<8093a0>")
    doc.xref_set_key(paragraph, "K", f"<< /Type /MCR /MCID 1 /Pg {doc.page_xref(0)} 0 R >>")
    report = inspect_tagged_pdf(doc)
    assert report.reading_order[1].actual_text == "\u2022\ufb01\u20ac"
    assert any("content page differs" in warning for warning in report.warnings)
    doc.close()


def test_numeric_lexer_does_not_copy_remaining_stream_for_reference_lookahead():
    from neoview.models.tagged_pdf import _Parser

    class NoTailCopies(bytes):
        def __getitem__(self, key):
            if isinstance(key, slice) and key.start and key.stop is None:
                raise AssertionError("Reference lookahead copied the remaining stream")
            return super().__getitem__(key)

    parser = _Parser(NoTailCopies(b"12 34 m " * 20000 + b"9 0 R"))
    for _ in range(20000):
        assert parser.value() == 12
        assert parser.value() == 34
        assert parser.value() == "m"
    assert parser.value().xref == 9


def test_cancelled_inspection_returns_explicit_incomplete_report():
    doc, _, _, _, _ = _fixture()
    report = inspect_tagged_pdf(doc, cancelled=lambda: True)
    assert not report.nodes
    assert any("cancelled" in message and "incomplete" in message for message in report.warnings)
    doc.close()


def test_parser_cancellation_interrupts_long_comments_and_strings():
    import pytest

    from neoview.models.tagged_pdf import _Parser

    for content in (b"%" + b"x" * 100000, b"(" + b"x" * 100000 + b")"):
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 2

        parser = _Parser(content, cancelled=cancelled)
        with pytest.raises(ValueError, match="cancelled"):
            parser.value()
        assert parser.pos <= 8192


def test_structure_only_inspection_preserves_pages_without_reading_content():
    with fitz.open() as document:
        document.new_page()
        root, tag = document.get_new_xref(), document.get_new_xref()
        document.update_object(root, f'<< /Type /StructTreeRoot /K {tag} 0 R >>')
        document.update_object(tag, f'<< /S /P /Pg {document.page_xref(0)} 0 R >>')
        document.xref_set_key(document.pdf_catalog(), 'StructTreeRoot', f'{root} 0 R')

        class WithoutContentReads:
            def __len__(self):
                return len(document)

            def __getattr__(self, name):
                return getattr(document, name)

            def __getitem__(self, index):
                raise AssertionError('Structure-only mode must not read page drawing streams')

        report = inspect_tagged_pdf(WithoutContentReads(), scan_artifacts=False)
        assert report.nodes[0].page == 0
        assert report.artifacts == []
