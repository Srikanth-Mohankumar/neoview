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


@pytest.mark.parametrize('first_suffix', [b'', b'% stream boundary comment'])
def test_multiple_content_streams_preserve_token_boundaries_and_rendering(tmp_path, first_suffix):
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=300)
        streams = []
        # Neither stream has trailing whitespace. The second starts with a
        # numeric operand, so joining raw bytes would turn the first f into f0.
        contents = [
            b'1 0 0 rg 0 0 100 100 re f' + first_suffix,
            b'0 0 1 rg 0 200 100 100 re f',
        ]
        for data in contents:
            xref = doc.get_new_xref()
            doc.update_object(xref, '<<>>')
            doc.update_stream(xref, data)
            streams.append(xref)
        refs = ' '.join(f'{xref} 0 R' for xref in streams)
        doc.xref_set_key(page.xref, 'Contents', f'[{refs}]')
        original_pixels = doc[0].get_pixmap().samples
        # An unterminated comment continues over the array stream boundary;
        # adding a newline would incorrectly reveal the second rectangle.
        expected_color = (255, 255, 255) if first_suffix else (0, 0, 255)
        assert doc[0].get_pixmap().pixel(20, 20) == expected_color
        mark_page_as_artifact(doc, 0)
        assert doc[0].get_pixmap().samples == original_pixels
        destination = tmp_path / 'multi-stream-marked.pdf'
        doc.save(destination)
    with fitz.open(destination) as saved:
        assert saved[0].get_pixmap().samples == original_pixels
        with fitz.open(stream=saved.tobytes(), filetype='pdf') as copy:
            unmark_page_artifact(copy, 0)
            assert copy[0].get_pixmap().samples == original_pixels
            restored_refs = copy[0].get_contents()
            assert [copy.xref_stream(xref) for xref in restored_refs] == contents
            unmarked = tmp_path / 'multi-stream-unmarked.pdf'
            copy.save(unmarked)
    with fitz.open(unmarked) as restored:
        assert restored[0].get_pixmap().samples == original_pixels
