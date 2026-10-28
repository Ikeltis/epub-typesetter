import shutil

import pytest

from epub_typesetter import engine, epubcheck
from epub_typesetter.book import NS, Book
from epub_typesetter.pipeline import optimize
from epub_typesetter.rebuild import REMOVED_ROLES
from epub_typesetter.semantic import analyze
from epub_typesetter.textcheck import compare_blocks
from epub_typesetter.xhtml import X

from conftest import JPEG, make_epub

EPUB_T = '{%s}type' % NS['epub']

# 仿 Kindle 转换书：标题靠 <font size> 区分层级，目录项指向空锚点，注释是 [n] 链接
BODY = '''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head><body>
<span id="toc0"/><p align="center"><font size="7">目录</font></p>
<blockquote><a href="c1.xhtml#a1">第1章 开始</a></blockquote>
<blockquote><a href="c1.xhtml#a2">一节</a></blockquote>
<span id="a1"/><p align="center"><font size="7"><font color="#0468BB">第1章 开始</font></font></p>
<p width="2em">第一段正文<sup><span id="r1"/><small><a href="c1.xhtml#n1">[1]</a></small></sup>。</p>
<p><img src="../Images/cover.jpg" width="420" height="255"/></p>
<p align="center"><font size="1">图1—1 示意图</font></p>
<blockquote>资料来源：某数据库。</blockquote>
<p>●要点一。</p>
<p>●要点二。</p>
<span id="a2"/><p><font size="6">一节</font></p>
<p>第二段正文。</p>
<p align="left"><font size="1"><b>注释</b></font></p>
<span id="n1"/><p><a href="c1.xhtml#r1"><font size="1">[1]</font></a> <font size="1">这是注释内容。</font></p>
<span id="a3"/><p align="center"><font size="7">第2章 继续</font></p>
<p>第三段正文。</p>
</body></html>'''

AD = '''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>ad</title></head><body>
<p>读累了记得休息一会哦~</p><p>公众号：某某书屋</p><p>网站：https://example.com</p></body></html>'''

NCX = '''<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="urn:uuid:12345678-1234-1234-1234-123456789abc"/></head>
<docTitle><text>测试书</text></docTitle><navMap>
<navPoint id="p0" playOrder="1"><navLabel><text>目录</text></navLabel><content src="Text/c1.xhtml#toc0"/></navPoint>
<navPoint id="p1" playOrder="2"><navLabel><text>第1章 开始</text></navLabel><content src="Text/c1.xhtml#a1"/></navPoint>
<navPoint id="p2" playOrder="3"><navLabel><text>一节</text></navLabel><content src="Text/c1.xhtml#a2"/></navPoint>
<navPoint id="p3" playOrder="4"><navLabel><text>第2章 继续</text></navLabel><content src="Text/c1.xhtml#a3"/></navPoint>
</navMap></ncx>'''


def kindle_like() -> bytes:
    return make_epub({'OEBPS/toc.ncx': NCX, 'OEBPS/Text/c1.xhtml': BODY,
                      'OEBPS/Text/c2.xhtml': AD, 'OEBPS/Images/cover.jpg': JPEG})


def test_analysis_roles():
    b = Book.load(kindle_like())
    engine.fix(b)
    an = analyze(b)
    roles = {blk.text[:6]: (blk.role, blk.level) for blk in an.blocks}
    assert roles['第1章 开始'] == ('heading', 1)
    assert roles['一节'] == ('heading', 2)
    assert roles['第2章 继续'] == ('heading', 1)
    assert roles['目录'][0] == 'toc'
    assert roles['图1—1 示'][0] == 'caption'
    assert roles['资料来源：某'][0] == 'source'
    assert roles['●要点一。'][0] == 'bullet'
    assert roles['注释'][0] == 'note-head'
    assert roles['[1] 这是'][0] == 'note'
    assert roles['公众号：某某'][0] == 'junk'


def test_rebuild_structure_and_text_kept():
    b = Book.load(kindle_like())
    rep = optimize(b)
    out = Book.load(b.to_bytes())
    spine = [i.path for i in out.spine_items()]
    assert spine == ['OEBPS/Text/cover.xhtml', 'OEBPS/Text/chapter01.xhtml', 'OEBPS/Text/chapter02.xhtml']
    ch1 = out.tree('OEBPS/Text/chapter01.xhtml').getroot()
    assert ch1.find(f'.//{X}section').get(EPUB_T) == 'chapter'
    assert [h.text for h in ch1.iter(X + 'h1', X + 'h2')] == ['第1章 开始', '一节']
    fig = ch1.find(f'.//{X}figure')
    assert fig.find(f'{X}figcaption').text == '图1—1 示意图'
    assert fig.find(f'{X}img').get('alt') == '图1—1 示意图' and fig.find(f'{X}img').get('width') is None
    assert ch1.find(f".//{X}p[@class='source']") is not None
    assert [li.text for li in ch1.iter(X + 'li')] == ['要点一。', '要点二。']
    ref = ch1.find(f".//{X}a[@class='noteref']")
    assert ref.get(EPUB_T) == 'noteref' and ref.get('href') == '#note-1'
    note = ch1.find(f".//{X}aside[@id='note-1']")
    assert note.get(EPUB_T) == 'footnote'
    assert ''.join(note.itertext()).strip().endswith('这是注释内容。')
    assert note.find(f".//{X}a[@class='backlink']").get('href') == '#noteref-1'
    assert ch1.find(f'.//{X}font') is None and not any(e.get('style') for e in ch1.iter() if isinstance(e.tag, str))
    # 广告页、目录页、「注释」小标题被删，其余内容一字不少
    assert {r for r, _ in rep.rebuild.removed} == {'toc', 'junk', 'note-head'}
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok
    # nav 由新标题生成
    nav = next(i for i in out.manifest() if 'nav' in i.properties)
    labels = [a.text for a in out.tree(nav.path).getroot().iter(X + 'a')]
    assert labels[:3] == ['第1章 开始', '一节', '第2章 继续']
    assert engine.fix(out).changes == []


@pytest.mark.skipif(not shutil.which('epubcheck'), reason='需要 epubcheck')
def test_rebuild_epubcheck_clean():
    b = Book.load(kindle_like())
    optimize(b)
    msgs = epubcheck.run_bytes(b.to_bytes())
    assert epubcheck.blocking(msgs) == 0, [(m.id, m.message) for m in msgs if m.severity in ('ERROR', 'FATAL')]


def test_vertical_book_stays_vertical():
    css = 'body { writing-mode: vertical-rl; -webkit-writing-mode: vertical-rl; }'
    opf = make_epub.__globals__['OPF2'].replace(
        '<item id="cover-img"', '<item id="css" href="Styles/s.css" media-type="text/css"/>\n<item id="cover-img"')
    b = Book.load(make_epub({'OEBPS/content.opf': opf, 'OEBPS/Styles/s.css': css}))
    rep = optimize(b)
    out = Book.load(b.to_bytes())
    assert rep.analysis.vertical
    sheet = next(out.files[p] for p in out.files if p.endswith('typesetter.css'))
    assert b'writing-mode:vertical-rl' in sheet.replace(b' ', b'')


def test_semantic_inline_styles_and_glyph_images_kept():
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new('RGB', (20, 20)).save(buf, 'GIF')
    css = '.small{font-size:smaller} .kt{font-family:"KaiTi"} .red{color:#c00} .fp{height:1em}'
    opf = make_epub.__globals__['OPF2'].replace(
        '<item id="cover-img"', '<item id="css" href="Styles/s.css" media-type="text/css"/>\n'
        '<item id="g" href="Images/g.gif" media-type="image/gif"/>\n<item id="cover-img"')
    body = ('<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head><body>'
            '<h1>第二章</h1><p>正文<span class="small kt red"><img class="fp" src="../Images/g.gif" alt="侧批"/>批语。</span>续。</p>'
            '</body></html>')
    b = Book.load(make_epub({'OEBPS/content.opf': opf, 'OEBPS/Styles/s.css': css, 'OEBPS/Images/g.gif': buf.getvalue(),
                             'OEBPS/Text/c2.xhtml': body}))
    optimize(b)
    out = Book.load(b.to_bytes())
    doc = next(i.path for i in out.spine_items() if b'\xe6\x89\xb9\xe8\xaf\xad' in out.files[i.path])
    p = out.tree(doc).getroot().find(f'.//{X}p')
    span = p.find(f'{X}span')
    assert set(span.get('class').split()) == {'small', 'kaiti', 'accent'}
    assert span.find(f'{X}img').get('class') == 'glyph'
