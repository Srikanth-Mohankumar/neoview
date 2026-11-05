import fitz
import pytest

from neoview.models.tagged_pdf import _Name, _Parser, _Ref, inspect_tagged_pdf
from neoview.models.tagged_pdf_editing import edit_tag, move_tag


def make_document():
    document = fitz.open()
    document.new_page()
    root, parent, first, second = [document.get_new_xref() for _ in range(4)]
    document.update_object(root, f'<< /Type /StructTreeRoot /K [{parent} 0 R] >>')
    document.update_object(parent, f'<< /Type /StructElem /S /Document /P {root} 0 R '
                           f'/K [{first} 0 R 9 << /Type /MCR /MCID 3 >> '
                           f'{second} 0 R << /Type /OBJR /Obj 1 0 R >>] >>')
    for xref, role, mcid in [(first, 'P', 0), (second, 'Figure', 1)]:
        document.update_object(xref, f'<< /Type /StructElem /S /{role} /P {parent} 0 R '
                               f'/Pg {document.page_xref(0)} 0 R /K {mcid} >>')
    document.xref_set_key(document.pdf_catalog(), 'StructTreeRoot', f'{root} 0 R')
    document.xref_set_key(document.pdf_catalog(), 'MarkInfo', '<< /Marked true >>')
    return document, root, parent, first, second


def parsed(document, xref):
    return _Parser(document.xref_object(xref, compressed=False).encode('latin1')).value()


def test_metadata_edits_roundtrip_unicode_and_escape_values():
    document, _, _, first, _ = make_document()
    with document:
        text = 'Figure \\ (one) \u4e2d\u6587'
        edit_tag(document, first, role='Figure', alt_text=text, actual_text='exact\ntext',
                 language='en-GB', title='A figure')
        with fitz.open(stream=document.tobytes(), filetype='pdf') as reopened:
            node = next(node for node in inspect_tagged_pdf(reopened).reading_order
                        if node.xref == first)
            assert node.role == 'Figure'
            assert node.alt_text == text
            assert node.actual_text == 'exact\ntext'
            assert node.language == 'en-GB'
            assert node.title == 'A figure'
        edit_tag(document, first, alt_text='', language='')
        assert document.xref_get_key(first, 'Alt') == ('null', 'null')
        assert document.xref_get_key(first, 'Lang') == ('null', 'null')
        assert document.xref_get_key(first, 'T')[1] == 'A figure'


@pytest.mark.parametrize('changes', [
    {'role': 'MadeUp'}, {'alt_text': '\x00'}, {'title': 'x' * 65537},
    {'language': 42}, {'actual_text': '\ud800'},
    {'role': 'Figure', 'alt_text': '\x00'},
])
def test_invalid_properties_do_not_partially_mutate(changes):
    document, _, _, first, _ = make_document()
    with document:
        original = document.xref_object(first)
        with pytest.raises(ValueError):
            edit_tag(document, first, **changes)
        assert document.xref_object(first) == original


def test_cannot_edit_unreachable_or_non_structure_objects():
    document, _, _, first, _ = make_document()
    with document:
        rogue = document.get_new_xref()
        document.update_object(rogue, '<< /S /P >>')
        for xref in [rogue, document.pdf_catalog(), document.page_xref(0), 0, True]:
            with pytest.raises(ValueError):
                edit_tag(document, xref, title='bad')
        edit_tag(document, first, title='allowed')


def test_move_changes_only_sibling_tag_order_and_roundtrips():
    document, _, parent, first, second = make_document()
    with document:
        before = parsed(document, parent)['K']
        assert move_tag(document, second, -1)
        after = parsed(document, parent)['K']
        assert after[0] == _Ref(second)
        assert after[3] == _Ref(first)
        assert after[1:3] == before[1:3]
        assert after[4:] == before[4:]
        assert after[2]['Type'] == _Name('MCR')
        assert after[4]['Type'] == _Name('OBJR')
        with fitz.open(stream=document.tobytes(), filetype='pdf') as reopened:
            assert [node.xref for node in inspect_tagged_pdf(reopened).nodes[0].children] == [
                second, first,
            ]
        assert not move_tag(document, second, -1)
        assert move_tag(document, second, 1)
        assert parsed(document, parent)['K'] == before
        assert not move_tag(document, second, 1)


def test_move_handles_indirect_k_array_without_mutating_other_references():
    document, _, parent, first, second = make_document()
    with document:
        array = document.get_new_xref()
        document.update_object(array, f'[{first} 0 R {second} 0 R]')
        document.xref_set_key(parent, 'K', f'{array} 0 R')
        before = document.xref_object(array)
        assert move_tag(document, second, -1)
        assert document.xref_object(array) == before
        assert parsed(document, parent)['K'] == [_Ref(second), _Ref(first)]


@pytest.mark.parametrize('malformation', ['duplicate', 'direct', 'wrong_parent', 'not_in_parent'])
def test_move_rejects_ambiguous_or_unsupported_children(malformation):
    document, root, parent, first, second = make_document()
    with document:
        if malformation == 'duplicate':
            document.xref_set_key(parent, 'K', f'[{first} 0 R {second} 0 R {second} 0 R]')
        elif malformation == 'direct':
            document.xref_set_key(parent, 'K', f'[{first} 0 R << /S /P /P {parent} 0 R >> '
                                  f'{second} 0 R]')
        elif malformation == 'wrong_parent':
            document.xref_set_key(first, 'P', f'{root} 0 R')
        else:
            # Reachable via root but the declared parent does not contain it.
            document.xref_set_key(root, 'K', f'[{parent} 0 R {second} 0 R]')
            document.xref_set_key(parent, 'K', f'[{first} 0 R]')
        before = document.xref_object(parent)
        with pytest.raises(ValueError):
            move_tag(document, second, -1)
        assert document.xref_object(parent) == before


def test_clone_edit_does_not_change_original_file(tmp_path):
    source = tmp_path / 'source.pdf'
    document, _, _, first, _ = make_document()
    with document:
        document.save(str(source))
    original = source.read_bytes()
    with fitz.open(str(source)) as opened:
        with fitz.open(stream=opened.tobytes(), filetype='pdf') as clone:
            edit_tag(clone, first, alt_text='An accessible figure', role='Figure')
            clone.save(str(tmp_path / 'edited.pdf'))
        assert opened.xref_get_key(first, 'S') == ('name', '/P')
    assert source.read_bytes() == original


def test_named_source_document_is_refused(tmp_path):
    source = tmp_path / 'source.pdf'
    document, _, _, first, _ = make_document()
    with document:
        document.save(str(source))
    with fitz.open(str(source)) as opened:
        with pytest.raises(ValueError, match='private PDF copy'):
            edit_tag(opened, first, title='do not modify source view')


def test_nonzero_reference_generation_is_refused_without_mutation():
    document, _, parent, first, second = make_document()
    with document:
        # An embedded reference is still part of the reserialized direct /K data.
        document.xref_set_key(parent, 'K', f'[{first} 0 R {second} 0 R '
                              '<< /Type /OBJR /Obj 1 2 R >>]')
        before = document.xref_object(parent)
        with pytest.raises(ValueError, match='Nonzero-generation'):
            move_tag(document, second, -1)
        assert document.xref_object(parent) == before


def test_authenticated_protected_copy_is_refused():
    document, _, _, first, _ = make_document()
    with document:
        encrypted = document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,
                                    owner_pw='owner', user_pw='reader')
    with fitz.open(stream=encrypted, filetype='pdf') as protected:
        assert protected.authenticate('owner')
        assert not protected.is_encrypted
        with pytest.raises(ValueError, match='Protected PDFs'):
            edit_tag(protected, first, title='cannot strip protection')


def test_signature_flags_are_refused():
    document, _, _, first, _ = make_document()
    with document:
        document.xref_set_key(document.pdf_catalog(), 'AcroForm', '<< /SigFlags 1 >>')
        with pytest.raises(ValueError, match='signature fields'):
            edit_tag(document, first, title='cannot invalidate signatures')
