import shutil

import pytest

from epub_typesetter import engine, epubcheck
from epub_typesetter.book import NS, Book
from epub_typesetter.textcheck import compare_text
from epub_typesetter.xhtml import X

from conftest import PNG, XHTML11, make_epub


def fixed(data: bytes) -> tuple[Book, engine.FixReport]:
    b = Book.load(data)
    rep = engine.fix(b)
    return Book.load(b.to_bytes()), rep


def ids_of(issues):
    return {i.rule_id for i in issues}


def test_upgrade_to_epub3(epub_bytes):
    b, rep = fixed(epub_bytes)
    assert b.version == '3.0'
    md = b.opf.find('opf:metadata', NS)
    assert md.find("opf:meta[@property='dcterms:modified']", NS) is not None
    assert md.find("opf:meta[@property='role']", NS).text == 'aut'
    creator = md.find('dc:creator', NS)
    assert not any(k.startswith('{%s}' % NS['opf']) for k in creator.attrib)
    cover = b.item_by_id('cover-img')
    assert 'cover-image' in cover.properties
    # guide 中指向图片的项被删除（OPF-032）
    assert all(not r.get('href', '').endswith('.jpg') for r in b.opf.iterfind('opf:guide/opf:reference', NS))


def test_nav_generated_from_ncx(epub_bytes):
    b, _ = fixed(epub_bytes)
    nav = next(i for i in b.manifest() if 'nav' in i.properties)
    root = b.tree(nav.path).getroot()
    toc = root.find(f".//{X}nav[@{{{NS['epub']}}}type='toc']")
    top = toc.find(f'{X}ol').findall(f'{X}li')
    assert [li.find(f'{X}a').text for li in top] == ['第一章', '第二章']
    sub = top[0].find(f'{X}ol/{X}li/{X}a')
    assert sub.text == '第一节' and sub.get('href') == 'Text/c1.xhtml#s1'
    assert root.find(f".//{X}nav[@{{{NS['epub']}}}type='landmarks']") is not None


def test_fix_is_idempotent(epub_bytes):
    b, rep = fixed(epub_bytes)
    assert rep.changes
    rep2 = engine.fix(b)
    assert rep2.changes == []


def test_text_preserved(epub_bytes):
    b, _ = fixed(epub_bytes)
    assert compare_text(Book.load(epub_bytes), b).equal


@pytest.mark.skipif(not shutil.which('epubcheck'), reason='需要 epubcheck')
def test_epubcheck_clean_after_fix(epub_bytes):
    b, _ = fixed(epub_bytes)
    msgs = epubcheck.run_bytes(b.to_bytes())
    assert epubcheck.blocking(msgs) == 0, [(m.id, m.message) for m in msgs]


def test_bad_ids_renamed_and_links_synced():
    c1 = XHTML11.format(title='一', body='<h1 id="1abc">一</h1><p><a href="c2.xhtml#9x">去</a></p>')
    c2 = XHTML11.format(title='二', body='<h1>二</h1><p id="9x">目标</p>')
    b, _ = fixed(make_epub({'OEBPS/Text/c1.xhtml': c1, 'OEBPS/Text/c2.xhtml': c2}))
    r2 = b.tree('OEBPS/Text/c2.xhtml').getroot()
    assert r2.find(f'.//{X}p').get('id') == 'n9x'
    r1 = b.tree('OEBPS/Text/c1.xhtml').getroot()
    assert r1.find(f'.//{X}a').get('href') == 'c2.xhtml#n9x'


def test_media_type_sniff_and_rename():
    b, rep = fixed(make_epub({'OEBPS/Images/cover.jpg': PNG}))
    it = b.item_by_id('cover-img')
    assert it.media_type == 'image/png' and it.path.endswith('.png')


def test_manual_indent_majority_becomes_css():
    body = ''.join(f'<p>\u3000\u3000第{i}段。</p>' for i in range(10))
    b, rep = fixed(make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body='<h1>二</h1>' + body)}))
    ps = b.tree('OEBPS/Text/c2.xhtml').getroot().findall(f'.//{X}p')
    assert all(not p.text.startswith('\u3000') for p in ps)
    assert all('ts-indent' in p.get('class') for p in ps)
    css = next(p for p in b.files if p.endswith('typesetter.css'))
    assert b'text-indent: 2em' in b.files[css]


def test_empty_paragraphs_removed_but_anchor_kept():
    body = '<h1>二</h1><p>甲</p><p>\u00a0</p><p><br/></p><p id="keep"></p><p>乙</p>'
    c1 = XHTML11.format(title='一', body='<h1>一</h1><p><a href="c2.xhtml#keep">跳</a></p>')
    b, _ = fixed(make_epub({'OEBPS/Text/c1.xhtml': c1,
                            'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body=body)}))
    ps = b.tree('OEBPS/Text/c2.xhtml').getroot().findall(f'.//{X}p')
    assert [p.get('id') or ''.join(p.itertext()) for p in ps] == ['甲', 'keep', '乙']


def test_img_alt_not_copied_from_figcaption():
    """04 4.11.2.5（D8）：缺 alt 一律补空串，不抄图注；alt 是文件名也清空；有图注的空 alt 报「待补描述」。"""
    body = ('<h1>二</h1><figure><img src="../Images/cover.jpg"/><figcaption>图 1\u3000山水</figcaption></figure>'
            '<p><img src="../Images/cover.jpg"/></p><p><img src="../Images/cover.jpg" alt="cover.jpg"/></p>')
    b, rep = fixed(make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body=body)}))
    alts = [i.get('alt') for i in b.tree('OEBPS/Text/c2.xhtml').getroot().iter(f'{X}img')]
    assert alts == ['', '', '']
    pending = [i for i in rep.after if i.rule_id == 'A11Y-001']
    assert pending and pending[0].severity == 'info' and len(pending[0].hits) == 1


def test_invisible_chars_removed_but_pre_kept():
    body = '<h1>二</h1><p>甲\u200b乙\ufeff</p><pre>a\u200bb</pre>'
    b, _ = fixed(make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body=body)}))
    root = b.tree('OEBPS/Text/c2.xhtml').getroot()
    assert root.find(f'.//{X}p').text == '甲乙'
    assert root.find(f'.//{X}pre').text == 'a\u200bb'


def test_lang_added(epub_bytes):
    b, _ = fixed(epub_bytes)
    root = b.tree('OEBPS/Text/c1.xhtml').getroot()
    assert root.get('lang') == 'zh'


def test_audit_reports_upgrade(epub_bytes):
    issues = engine.audit(Book.load(epub_bytes))
    assert 'STR-004' in ids_of(issues)


def test_obsolete_markup_to_css():
    body = ('<h1>二</h1><p align="center"><font color="red" size="+1">红</font></p>'
            '<table width="90%" cellspacing="0"><tr><td valign="top">格</td></tr></table>'
            '<ul><li>甲</li><ul><li>乙</li></ul></ul><p data-AmznRemoved="1">丙</p>'
            '<img src="../Images/cover.jpg" width="50%"/>')
    b, _ = fixed(make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body=body)}))
    root = b.tree('OEBPS/Text/c2.xhtml').getroot()
    p = root.find(f'.//{X}p')
    assert p.get('align') is None and 'text-align: center' in p.get('style')
    span = p.find(f'{X}span')
    assert 'color: red' in span.get('style') and 'font-size: larger' in span.get('style')
    assert root.find(f'.//{X}font') is None
    t = root.find(f'.//{X}table')
    assert t.get('width') is None and 'width: 90%' in t.get('style')
    ul = root.find(f'.//{X}ul')
    assert all(ch.tag == X + 'li' for ch in ul)
    assert root.find(f'.//{X}p[@data-amznremoved]') is not None
    img = root.find(f'.//{X}img')
    assert img.get('width') is None and 'width: 50%' in img.get('style')


def test_css_cleanup_and_missing_font():
    css = ('@font-face { font-family: "a"; src: url(../Fonts/none.ttf); }\n'
           '@font-face { font-family: "b"; src: local("宋体"), url(../Fonts/none2.ttf); }\n'
           'p {\n  margin: 0;\n   font-size:;\n}\nspan.lang(ja) { color: red; }\nh1 { color: blue; }\n')
    opf = (make_epub.__globals__['OPF2']
           .replace('<item id="cover-img"', '<item id="css" href="Styles/s.css" media-type="text/css"/>\n'
                    '    <item id="cover-img"'))
    b, rep = fixed(make_epub({'OEBPS/content.opf': opf, 'OEBPS/Styles/s.css': css}))
    out = b.files['OEBPS/Styles/s.css'].decode()
    assert 'none.ttf' not in out and 'none2.ttf' not in out
    assert 'font-family: "a"' not in out and 'local("宋体")' in out
    assert 'lang(ja)' not in out and 'h1 { color: blue; }' in out
    assert ' ' not in out and 'font-size' not in out


def test_missing_xmlns_fixed():
    doc = '<?xml version="1.0"?><html><body><p>甲</p></body></html>'
    b, _ = fixed(make_epub({'OEBPS/Text/c2.xhtml': doc}))
    root = b.tree('OEBPS/Text/c2.xhtml').getroot()
    assert root.tag == X + 'html' and root.find(f'{X}head/{X}title') is not None


def test_whitespace_trim_through_emptied_nodes_is_idempotent():
    body = '<h1>二</h1><p>编辑 王烨 <span>　</span></p>'
    b, _ = fixed(make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body=body)}))
    assert engine.fix(b).changes == []
    assert b.tree('OEBPS/Text/c2.xhtml').getroot().find(f'.//{X}p').text == '编辑 王烨'


def test_duplicate_thead_becomes_tbody():
    body = ('<h1>二</h1><table><thead><tr><th>甲</th></tr></thead><tbody><tr><td>1</td></tr></tbody>'
            '<thead><tr><th>乙</th></tr></thead><tbody><tr><td>2</td></tr></tbody></table>')
    b, _ = fixed(make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body=body)}))
    t = b.tree('OEBPS/Text/c2.xhtml').getroot().find(f'.//{X}table')
    assert [c.tag.split('}')[1] for c in t] == ['thead', 'tbody', 'tbody', 'tbody']


def test_ineffective_presentational_attrs_are_dropped_not_converted():
    """回归：<p width="0pt" height="2em"> 在浏览器里从不生效；转成 CSS 会把段落压成 0 宽（《笑傲牛熊》事故）。"""
    body = ('<h1>二</h1><p height="2em" width="0pt" align="center">甲</p>'
            '<blockquote height="2em" width="0pt">乙</blockquote>'
            '<table width="80%" cellpadding="4"><tr><td width="30" height="0">格</td></tr></table>'
            '<p><img src="../Images/cover.jpg" width="420" height="255" align="baseline"/></p>')
    b, _ = fixed(make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body=body)}))
    root = b.tree('OEBPS/Text/c2.xhtml').getroot()
    p = root.find(f'.//{X}p')
    assert p.get('style') == 'text-align: center'
    bq = root.find(f'.//{X}blockquote')
    assert bq.get('style') is None and bq.get('width') is None
    assert root.find(f'.//{X}table').get('style') == 'width: 80%'
    td = root.find(f'.//{X}td')
    assert 'width: 30px' in td.get('style') and 'padding: 4px' in td.get('style') and 'height' not in td.get('style')
    img = root.find(f'.//{X}img')
    assert img.get('width') == '420' and img.get('style') is None and img.get('align') is None


def test_epub3_with_opf2_metadata_and_wrong_lang():
    opf = (make_epub.__globals__['OPF2'].replace('version="2.0"', 'version="3.0"')
           .replace('<meta name="cover" content="cover-img"/>',
                    '<meta name="cover" content="cover-img"/><meta property="dcterms:modified">2020-01-01T00:00:00Z</meta>'))
    c2 = ('<?xml version="1.0"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en">'
          '<head><title>二</title></head><body><h1>第二章</h1><p>这是中文正文，很长很长。</p></body></html>')
    b, _ = fixed(make_epub({'OEBPS/content.opf': opf, 'OEBPS/Text/c2.xhtml': c2}))
    creator = b.opf.find('opf:metadata/dc:creator', NS)
    assert not any(k.startswith('{%s}' % NS['opf']) for k in creator.attrib)
    assert b.tree('OEBPS/Text/c2.xhtml').getroot().get('lang') == 'zh'


@pytest.mark.skipif(not shutil.which('chromium'), reason='需要 chromium')
def test_layout_check_catches_squashed_paragraphs():
    from epub_typesetter.layoutcheck import compare_layout
    long_p = '<p>' + '这是一段足够长的中文正文，用来检验版面是否被压扁。' * 20 + '</p>'
    good = make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body='<h1>二</h1>' + long_p * 6)})
    bad = make_epub({'OEBPS/Text/c2.xhtml': XHTML11.format(
        title='二', body='<h1>二</h1>' + long_p.replace('<p>', '<p style="width: 0pt">') * 6)})
    assert compare_layout(good, good).ok
    assert not compare_layout(good, bad).ok


def test_z3998_prefix_added_on_html_and_moved_from_body():
    doc = ('<?xml version="1.0"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" '
           'xmlns:epub="http://www.idpf.org/2007/ops" lang="zh" xml:lang="zh"><head><title>二</title></head>'
           '<body epub:prefix="foo: http://example.com/"><h1>二</h1>'
           '<blockquote epub:type="z3998:poem"><p>诗</p></blockquote></body></html>')
    b, _ = fixed(make_epub({'OEBPS/Text/c2.xhtml': doc}))
    root = b.tree('OEBPS/Text/c2.xhtml').getroot()
    pre = root.get('{http://www.idpf.org/2007/ops}prefix')
    assert 'z3998: http://www.daisy.org/z3998/2012/vocab/structure/' in pre and 'foo: http://example.com/' in pre
    assert root.find('{http://www.w3.org/1999/xhtml}body').get('{http://www.idpf.org/2007/ops}prefix') is None
