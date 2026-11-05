import fitz
import pytest

from neoview.models.tagged_pdf import inspect_tagged_pdf
from neoview.models.tagged_pdf_content import (
    mark_page_as_artifact,
    unmark_page_artifact,
)


def document_with_text():
    doc = fitz.open()
    doc.new_page().insert_text((40, 40), 'Meaningful text')
    return doc


def test_artifact_mark_roundtrip_preserves_rendered_and_extracted_content(tmp_path):
    with document_with_text() as doc:
        original_contents = doc[0].read_contents()
        original_text = doc[0].get_text()
        original_pixels = doc[0].get_pixmap().samples
        mark_page_as_artifact(doc, 0)
        assert inspect_tagged_pdf(doc).artifacts[0].count == 1
        assert doc[0].get_text() == original_text
        assert doc[0].get_pixmap().samples == original_pixels
        destination = tmp_path / 'marked.pdf'
        doc.save(destination)
    with fitz.open(destination) as saved:
        memory = fitz.open(stream=saved.tobytes(), filetype='pdf')
    with memory:
        unmark_page_artifact(memory, 0)
        assert memory[0].read_contents() == original_contents
        assert inspect_tagged_pdf(memory).artifacts[0].count == 0


def test_requires_memory_copy_and_does_not_modify_source(tmp_path):
    path = tmp_path / 'source.pdf'
    with document_with_text() as doc:
        doc.save(path)
    before = path.read_bytes()
    with fitz.open(path) as source:
        with pytest.raises(ValueError, match='in-memory'):
            mark_page_as_artifact(source, 0)
        with fitz.open(stream=source.tobytes(), filetype='pdf') as copy:
            mark_page_as_artifact(copy, 0)
    assert path.read_bytes() == before


@pytest.mark.parametrize('content', [
    b'/P <</MCID 0>> BDC BT (abc) Tj ET EMC',
    b'/Artifact BMC EMC', b'/P MP', b'/P <<>> DP',
    b'BI /W 1 /H 1 ID x EI',
])
def test_refuses_existing_marked_content_and_inline_images(content):
    with document_with_text() as doc:
        stream = doc[0].get_contents()[0]
        doc.update_stream(stream, content)
        before = doc[0].read_contents()
        with pytest.raises(ValueError, match='marked content or inline images'):
            mark_page_as_artifact(doc, 0)
        assert doc[0].read_contents() == before


def test_strings_comments_and_hex_strings_are_not_operators():
    with document_with_text() as doc:
        stream = doc[0].get_contents()[0]
        content = b'% /Artifact BMC\nBT (BMC BDC EMC BI ID EI) Tj <424443> Tj ET'
        doc.update_stream(stream, content)
        mark_page_as_artifact(doc, 0)
        unmark_page_artifact(doc, 0)
        assert doc[0].read_contents() == content


@pytest.mark.parametrize('key,value', [
    ('StructTreeRoot', '<< /Type /StructTreeRoot /K [] >>'),
    ('MarkInfo', '<< /Marked true >>'),
])
def test_refuses_tagged_documents(key, value):
    with document_with_text() as doc:
        doc.xref_set_key(doc.pdf_catalog(), key, value)
        with pytest.raises(ValueError, match='tagged PDF'):
            mark_page_as_artifact(doc, 0)


def test_refuses_form_xobjects():
    with document_with_text() as doc, document_with_text() as other:
        doc[0].show_pdf_page(doc[0].rect, other, 0)
        with pytest.raises(ValueError, match='Form XObjects'):
            mark_page_as_artifact(doc, 0)


def test_unmark_refuses_unowned_or_modified_artifacts():
    with document_with_text() as doc:
        with pytest.raises(ValueError, match='no NeoView'):
            unmark_page_artifact(doc, 0)
        mark_page_as_artifact(doc, 0)
        with pytest.raises(ValueError, match='already'):
            mark_page_as_artifact(doc, 0)
        stream = doc[0].get_contents()[0]
        doc.update_stream(stream, doc.xref_stream(stream) + b'\n% changed')
        with pytest.raises(ValueError, match='changed'):
            unmark_page_artifact(doc, 0)


def test_unmark_refuses_modified_original_content():
    with document_with_text() as doc:
        original_stream = doc[0].get_contents()[0]
        mark_page_as_artifact(doc, 0)
        doc.update_stream(original_stream, b'BT (changed) Tj ET')
        with pytest.raises(ValueError, match='Original content changed'):
            unmark_page_artifact(doc, 0)


@pytest.mark.parametrize('index', [-1, 1, True, '0'])
def test_rejects_invalid_pages(index):
    with document_with_text() as doc:
        with pytest.raises(ValueError, match='Page index'):
            mark_page_as_artifact(doc, index)


def test_refuses_malformed_page_content():
    with document_with_text() as doc:
        stream = doc[0].get_contents()[0]
        doc.update_stream(stream, b'[ 1 2')
        with pytest.raises(ValueError, match='Malformed'):
            mark_page_as_artifact(doc, 0)


def test_unmark_refuses_content_reference_replacement():
    with document_with_text() as doc:
        old_stream = doc[0].get_contents()[0]
        mark_page_as_artifact(doc, 0)
        doc.xref_set_key(doc[0].xref, 'Contents', f'{old_stream} 0 R')
        with pytest.raises(ValueError, match='Page content changed'):
            unmark_page_artifact(doc, 0)
