import re
import shutil

import pytest

from epub_typesetter import engine, epubcheck
from epub_typesetter.book import NS, Book
from epub_typesetter.pipeline import optimize
from epub_typesetter.rebuild import REMOVED_ROLES
from epub_typesetter.semantic import analyze
from epub_typesetter.textcheck import compare_blocks
from epub_typesetter.xhtml import X

from conftest import JPEG, OPF2, XHTML11, make_epub

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
    assert spine == ['OEBPS/Text/cover.xhtml', 'OEBPS/Text/chapter01.xhtml', 'OEBPS/Text/chapter02.xhtml',
                     'OEBPS/Text/endnotes.xhtml']
    ch1 = out.tree('OEBPS/Text/chapter01.xhtml').getroot()
    sec = ch1.find(f'.//{X}section')
    assert sec.get(EPUB_T) == 'chapter' and sec.get('id') == 'chapter01'
    # 04 §4.3：h1 只给书名页；章 h2.chapter-title，节 h3.section-title
    assert [(h.tag[-2:], h.get('class'), h.text) for h in ch1.iter(X + 'h1', X + 'h2', X + 'h3')] == \
        [('h2', 'chapter-title', '第1章\u3000开始'), ('h3', 'section-title', '一节')]   # 章号章名间统一全角空格
    fig = ch1.find(f'.//{X}figure')
    assert fig.find(f'{X}figcaption').text == '图1—1 示意图'
    # 04 4.11.2.5：缺 alt 不复制图注（读屏会念两遍），写 alt="" 待补描述
    assert fig.find(f'{X}img').get('alt') == '' and fig.find(f'{X}img').get('width') is None
    assert ch1.find(f".//{X}p[@class='source']") is not None
    assert [li.text for li in ch1.iter(X + 'li')] == ['要点一。', '要点二。']
    # 注释：同 Standard Ebooks，书末尾注文件 + 不包 sup 的注号 + 注文末尾 ↩ 回链
    ref = ch1.find(f".//{X}a[@class='noteref']")
    assert ref.get(EPUB_T) == 'noteref' and ref.get('href') == 'endnotes.xhtml#note-1' and ref.text == '1'
    assert ref.find(f'{X}sup') is None and ref.getparent().tag != X + 'small'
    en = out.tree('OEBPS/Text/endnotes.xhtml').getroot()
    assert en.find(f'.//{X}section').get(EPUB_T) == 'endnotes'
    assert en.find(f'.//{X}h2').get('class') == 'chapter-title' and en.find(f'.//{X}h1') is None
    li = en.find(f".//{X}li[@id='note-1']")
    assert ''.join(li.itertext()).strip().startswith('这是注释内容。')
    back = li.find(f".//{X}a[@class='backlink']")
    assert back.get('href') == 'chapter01.xhtml#noteref-1' and back.get(EPUB_T) == 'backlink' and back.text == '↩'
    assert spine[-1] == 'OEBPS/Text/endnotes.xhtml'
    # 注号前后不留源码换行造成的空格
    assert '正文1。' in ''.join(ch1.find(f'.//{X}p').itertext()).replace('\n', '')
    assert ch1.find(f'.//{X}font') is None and not any(e.get('style') for e in ch1.iter() if isinstance(e.tag, str))
    # 广告页、目录页、「注释」小标题被删，其余内容一字不少
    assert {r for r, _ in rep.rebuild.removed} == {'toc', 'junk', 'note-head'}
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok
    # nav 由新标题生成
    nav = next(i for i in out.manifest() if 'nav' in i.properties)
    labels = [a.text for a in out.tree(nav.path).getroot().iter(X + 'a')]
    assert labels[:4] == ['第1章\u3000开始', '一节', '第2章\u3000继续', '注释']
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


PARTS = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head><body>
<h1>第一部　山河</h1><h2>第一章　开端</h2><p>甲。<a href="c1.xhtml#n1" id="r1">[1]</a></p><h2>第二章　远行</h2><p>乙。<a href="c1.xhtml#n1" id="r2">[1]</a></p>
<h1>第二部　风雨</h1><h2>第三章　归来</h2><p>丙。</p><h1>后记</h1><p>丁。</p>
<p id="n1"><a href="c1.xhtml#r1">[1]</a>注文第一段。</p><p>注文第二段。</p><h1>附录</h1><p>戊。</p>
</body></html>"""


def test_parts_chapters_multiref_and_multiblock_notes():
    b = Book.load(make_epub({'OEBPS/Text/c1.xhtml': PARTS, 'OEBPS/Text/c2.xhtml': None}))
    rep = optimize(b)
    out = Book.load(b.to_bytes())
    spine = [i.path.rsplit('/', 1)[-1] for i in out.spine_items()]
    assert spine[:7] == ['cover.xhtml', 'part01.xhtml', 'chapter01.xhtml', 'chapter02.xhtml', 'part02.xhtml',
                         'chapter03.xhtml', 'afterword.xhtml']
    part = out.tree('OEBPS/Text/part01.xhtml').getroot()
    assert part.find(f'.//{X}section').get(EPUB_T) == 'part'
    assert part.find(f'.//{X}h2').get('class') == 'part-title'
    ch = out.tree('OEBPS/Text/chapter01.xhtml').getroot()
    assert ch.find(f'.//{X}h3').get('class') == 'chapter-title'           # 有部时章用 h3
    aft = out.tree('OEBPS/Text/afterword.xhtml').getroot()
    assert aft.find(f'.//{X}h2').get('class') == 'chapter-title'          # 后记不属于部，回到 h2
    # 同一条注被引用两次：第二处 id 为 noteref-1-2，回链指第一处（04 4.12.1.6）
    ids = [a.get('id') for p in ('chapter01.xhtml', 'chapter02.xhtml')
           for a in out.tree('OEBPS/Text/' + p).getroot().iter(X + 'a') if a.get('class') == 'noteref']
    assert ids == ['noteref-1', 'noteref-1-2']
    li = out.tree('OEBPS/Text/endnotes.xhtml').getroot().find(f".//{X}li[@id='note-1']")
    ps = li.findall(f'{X}p')
    assert len(ps) == 2 and ps[0].text.startswith('注文第一段') and ps[1].text.startswith('注文第二段')
    assert ps[1].find(f"{X}a[@class='backlink']").get('href') == 'chapter01.xhtml#noteref-1'
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok
    # nav：部在顶层，章嵌套其下
    nav = next(i for i in out.manifest() if 'nav' in i.properties)
    toc = out.tree(nav.path).getroot().find(f".//{X}nav[@{EPUB_T}='toc']")
    top = [li.find(f'{X}a').text for li in toc.find(f'{X}ol').findall(f'{X}li')]
    assert top[:3] == ['第一部\u3000山河', '第二部\u3000风雨', '后记']
    assert engine.fix(out).changes == []


def test_cover_page_alt_and_no_inline_style():
    b = Book.load(kindle_like())
    optimize(b)
    out = Book.load(b.to_bytes())
    cover = out.files['OEBPS/Text/cover.xhtml'].decode()
    assert 'alt="封面：《测试书》"' in cover and '<style' not in cover and 'typesetter.css' in cover


def test_ordinal_and_title_headings_merged_and_toc_headings_dropped():
    body = ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title>'
            '</head><body><p>目 录</p><h4><a href="c1.xhtml#a1">第一回　开端</a></h4><h4><a href="c1.xhtml#a2">第二回　远行</a></h4>'
            '<h3 id="a1">第一回</h3><h2>开端</h2><p>甲。</p><h3 id="a2">第二回</h3><h2>远行</h2><p>乙。</p></body></html>')
    b = Book.load(make_epub({'OEBPS/Text/c1.xhtml': body, 'OEBPS/Text/c2.xhtml': None}))
    rep = optimize(b)
    out = Book.load(b.to_bytes())
    chs = [i.path for i in out.spine_items() if 'chapter' in i.path]
    assert len(chs) == 2
    h = out.tree(chs[0]).getroot().find(f'.//{X}h2')
    assert ''.join(h.itertext()) == '第一回　开端' and h.get('class') == 'chapter-title'
    assert h.get('id') == 'a1'                                       # 原锚点保留
    assert sum(1 for r, _ in rep.rebuild.removed if r == 'toc') == 3  # 目录页标题 + 两个链接型标题
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok


OMNIBUS_T1 = XHTML11.format(title='1', body='<h1 title="Ⅰ 甲书"><img alt="t1" src="../Images/cover.jpg"/></h1>'
                            '<h2><span>第1章</span><br/>开端</h2>'
                            '<p><span style="float: left; font-size: 2em; font-weight: bold; color: #694776">甲</span>'
                            '书开头。</p><h2>第2章 远行</h2><p>乙。</p>')
OMNIBUS_T2 = ('<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><title>2</title>'
              '</head><body style="background: url(../Images/bg.jpg) no-repeat center">'
              '<div class="img0"><h1 title="Ⅱ 乙书"><br/></h1></div></body></html>')
OMNIBUS_T3 = XHTML11.format(title='3', body='<h2>第1章 归来</h2><p>丙。</p><h2>第2章 再会</h2><p>丁。</p>'
                            '<h2>尾声</h2><p>戊。</p><h2>阿不思·邓布利多<br/>的序言</h2><p>己。</p>')
OMNIBUS_T4 = XHTML11.format(title='4', body='<h1>Ⅲ 丙书</h1><h2>第1章 启程</h2><p>庚。</p><h2>第2章 终点</h2><p>辛。</p>'
                            '<h1>附录</h1><h2>前传</h2><p>癸。</p><h2>小书</h2><h3>版权信息</h3><p>子。</p>'
                            '<h1>制作手记</h1><p>壬。</p>')


def _omnibus() -> bytes:
    opf = OPF2.replace('<item id="cover-img"', '<item id="c3" href="Text/c3.xhtml" media-type="application/xhtml+xml"/>'
                       '<item id="c4" href="Text/c4.xhtml" media-type="application/xhtml+xml"/>'
                       '<item id="bg" href="Images/bg.jpg" media-type="image/jpeg"/><item id="cover-img"')
    opf = opf.replace('<itemref idref="c2"/>', '<itemref idref="c2"/><itemref idref="c3"/><itemref idref="c4"/>')
    return make_epub({'OEBPS/content.opf': opf, 'OEBPS/Images/bg.jpg': JPEG,
                      'OEBPS/Text/c1.xhtml': OMNIBUS_T1, 'OEBPS/Text/c2.xhtml': OMNIBUS_T2,
                      'OEBPS/Text/c3.xhtml': OMNIBUS_T3, 'OEBPS/Text/c4.xhtml': OMNIBUS_T4})


def _nav_top(out: Book) -> list:
    nav = next(i for i in out.manifest() if 'nav' in i.properties)
    toc = out.tree(nav.path).getroot().find(f".//{X}nav[@{EPUB_T}='toc']")
    return toc.find(f'{X}ol').findall(f'{X}li')


def test_omnibus_titles_in_title_attr_become_parts():
    """合集：各册标题字只在 title 属性里（图片标题 / 背景图上的空标题），不叫「第X部」也要认作部；
    背景整页图转成插图；目录文字里 <br/> 的处理。"""
    b = Book.load(_omnibus())
    rep = optimize(b)
    out = Book.load(b.to_bytes())
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok
    top = _nav_top(out)
    assert [li.find(f'{X}a').text for li in top] == ['Ⅰ 甲书', 'Ⅱ 乙书', 'Ⅲ 丙书', '附录', '制作手记']
    assert [a.text for a in top[0].iter(X + 'a')][1:] == ['第1章　开端', '第2章　远行']
    assert [a.text for a in top[1].iter(X + 'a')][1:] == ['第1章　归来', '第2章　再会', '尾声',
                                                          '阿不思·邓布利多的序言']   # 尾声留在本册里
    # 附录下面不是「第X章」：附录不算部，作章，子项作节嵌在下面
    assert [a.text for a in top[3].iter(X + 'a')][1:] == ['前传', '小书']
    xs = {p: out.files[p].decode() for p in out.files if p.endswith('.xhtml')}
    assert sum(s.count('class="part-title"') for s in xs.values()) == 3
    assert any('<h2 class="chapter-title"' in s and '>附录</h2>' in s for s in xs.values())
    # 首字下沉：放大、浮动去掉后，颜色、加粗也不留
    assert any('<p>甲书开头。</p>' in s for s in xs.values())
    assert any('alt="Ⅰ 甲书"' in s for s in xs.values())                    # 图片标题：文字进 alt，图照常显示
    assert any('>Ⅱ 乙书</h2>' in s for s in xs.values())                     # 空标题：直接输出文字
    assert any('bg.jpg' in s for s in xs.values()) and 'OEBPS/Images/bg.jpg' in out.files   # 背景整页图没丢


def test_omnibus_volume_forced_to_chapter_and_image_title_renamed():
    """确认板：把一册（与部同级）指定为章 → 并进前一部，原来的各章随它降为节；
    改写图片标题的文字 → 图片保留，新文字进 alt 和目录。"""
    from epub_typesetter import board
    from epub_typesetter.semantic import block_keys
    an = analyze(Book.load(_omnibus()))
    keys = block_keys(an.blocks)
    key = {b.text: keys[b.idx] for b in an.blocks if b.role == 'heading'}
    d = board.empty()
    d['heads'][key['Ⅱ 乙书']] = 'chapter'
    d['titles'][key['Ⅰ 甲书']] = '甲书'
    b = Book.load(_omnibus())
    rep = optimize(b, decisions=d)
    out = Book.load(b.to_bytes())
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok
    top = _nav_top(out)
    assert [li.find(f'{X}a').text for li in top] == ['甲书', 'Ⅲ 丙书', '附录', '制作手记']
    first = [li.find(f'{X}a').text for li in top[0].find(f'{X}ol').findall(f'{X}li')]
    assert first == ['第1章　开端', '第2章　远行', 'Ⅱ 乙书']           # 乙书在甲书这一部里
    vol2 = top[0].find(f'{X}ol').findall(f'{X}li')[2]
    assert [li.find(f'{X}a').text for li in vol2.find(f'{X}ol').findall(f'{X}li')][:3] == \
        ['第1章　归来', '第2章　再会', '尾声']                            # 原来的章降为节，嵌在乙书下
    xs = ''.join(out.files[p].decode() for p in out.files if p.endswith('.xhtml'))
    assert 'alt="甲书"' in xs and 'Ⅰ' not in xs.replace('alt="Ⅰ', '')    # 图片还在，文字改了
    assert '<h3 class="chapter-title"' in xs and '>Ⅱ 乙书</h3>' in xs


def test_visible_toc_with_group_rows_removed():
    """书内目录页里夹着「第一部」+ 装饰图这样的分组行：整页都要删掉，成品里不留看得见的目录。"""
    toc_page = XHTML11.format(title='目录', body=(
        '<h1>目录</h1><p class="c">第一部<br/><img src="../Images/cover.jpg" alt=""/><br/>'
        '<a href="c2.xhtml">甲书</a></p><p><a href="c2.xhtml#a1">第1章 开端</a></p>'
        '<p><a href="c2.xhtml#a2">第2章 远行</a></p><div><img src="../Images/cover.jpg" alt=""/></div>'
        '<p class="c">第二部</p><p><a href="c2.xhtml#a3">第3章 归来</a></p>'))
    body = XHTML11.format(title='正文', body='<h1 id="a1">第1章 开端</h1><p>甲。</p><h1 id="a2">第2章 远行</h1>'
                                             '<p>乙。</p><h1 id="a3">第3章 归来</h1><p>丙。</p>')
    b = Book.load(make_epub({'OEBPS/Text/c1.xhtml': toc_page, 'OEBPS/Text/c2.xhtml': body}))
    rep = optimize(b)
    out = Book.load(b.to_bytes())
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok
    text = ''.join(out.files[p].decode() for p in out.files if p.endswith('.xhtml') and 'nav' not in p)
    assert '第一部' not in text and '第二部' not in text and '>目录<' not in text
    bodies = ''.join(re.findall(r'<body.*?</body>', text, re.S))
    assert bodies.count('第1章') == 1                  # 只剩正文里的章标题（<title> 里的不算）
