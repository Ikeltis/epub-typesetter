import io
import zipfile

import pytest

from epub_typesetter.book import Book, EpubError, repair_xml_bytes

from conftest import make_epub


def test_load_basic(epub_bytes):
    b = Book.load(epub_bytes)
    assert b.opf_path == 'OEBPS/content.opf'
    assert b.version == '2.0'
    assert [i.id for i in b.spine_items()] == ['c1', 'c2']
    assert b.content_docs() == ['OEBPS/Text/c1.xhtml', 'OEBPS/Text/c2.xhtml']
    assert b.zip_notes == []


def test_zip_notes():
    b = Book.load(make_epub(mimetype_first=False, compress_mimetype=True))
    assert 'mimetype 不是第一个条目' in b.zip_notes
    assert 'mimetype 被压缩' in b.zip_notes


def test_save_mimetype_first_stored(epub_bytes):
    out = Book.load(epub_bytes).to_bytes()
    first = zipfile.ZipFile(io.BytesIO(out)).infolist()[0]
    assert first.filename == 'mimetype' and first.compress_type == zipfile.ZIP_STORED
    assert not first.extra


def test_roundtrip_unchanged_bytes(epub_bytes):
    b = Book.load(epub_bytes)
    b.tree('OEBPS/Text/c1.xhtml')          # 只解析不改，不应重写
    out = Book.load(b.to_bytes())
    assert out.files['OEBPS/Text/c1.xhtml'] == b.files['OEBPS/Text/c1.xhtml']


def test_resolve_and_relative():
    assert Book.resolve('OEBPS/Text/c1.xhtml', '../Images/a%20b.jpg#x') == 'OEBPS/Images/a b.jpg'
    assert Book.relative('OEBPS/Text/c1.xhtml', 'OEBPS/Images/a b.jpg') == '../Images/a%20b.jpg'
    assert Book.relative('OEBPS/content.opf', 'OEBPS/Text/c1.xhtml') == 'Text/c1.xhtml'


def test_missing_container_single_opf():
    b = Book.load(make_epub(drop=('META-INF/container.xml',)))
    assert b.opf_path == 'OEBPS/content.opf'


def test_not_zip():
    with pytest.raises(EpubError):
        Book.load(b'not a zip')


def test_repair_entities_and_bare_amp():
    out = repair_xml_bytes(b'<p>A &amp; B & C&nbsp;D &#160; &copy;</p>')
    assert out == b'<p>A &amp; B &amp; C&#160;D &#160; &#169;</p>'


def test_parse_with_bare_amp_records_note():
    bad = make_epub({'OEBPS/Text/c2.xhtml':
                     '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
                     '<body><p>A & B&nbsp;</p></body></html>'})
    b = Book.load(bad)
    root = b.tree('OEBPS/Text/c2.xhtml').getroot()
    assert 'A & B\xa0' in ''.join(root.itertext())
    assert any('修复后可解析' in n.message for n in b.parse_notes)


def test_add_item_unique_id(epub_bytes):
    b = Book.load(epub_bytes)
    it = b.add_item('OEBPS/Text/nav.xhtml', 'application/xhtml+xml', item_id='c1', data=b'<x/>')
    assert it.id == 'c1-2'
    assert it.href == 'Text/nav.xhtml'


def test_html_entities_become_chars_not_entity_nodes():
    doc = ('<?xml version="1.0"?><!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
           '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd"><html xmlns="http://www.w3.org/1999/xhtml">'
           '<head><title>t</title></head><body><p>&nbsp;甲&mdash;</p></body></html>')
    b = Book.load(make_epub({'OEBPS/Text/c2.xhtml': doc}))
    root = b.tree('OEBPS/Text/c2.xhtml').getroot()
    assert ''.join(root.itertext()).endswith('\u00a0甲—')
    assert all(isinstance(e.tag, str) for e in root.iter())
