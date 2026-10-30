"""成组结构的识别与重建输出（guide/04 §4.7–4.13、4.19；structures.py、rebuild.py）。"""
import shutil

import pytest

from epub_typesetter import engine, epubcheck
from epub_typesetter.book import NS, Book
from epub_typesetter.pipeline import optimize
from epub_typesetter.rebuild import REMOVED_ROLES
from epub_typesetter.textcheck import compare_blocks
from epub_typesetter.xhtml import X

from conftest import JPEG, XHTML11, make_epub

EPUB_T = '{%s}type' % NS['epub']
PREFIX = '{%s}prefix' % NS['epub']
P = '<p>' + '正文叙述，' * 8 + '。</p>'          # 普通段落（让「正文主流」明确）


def rebuild(c1: str, c2: str = '<h1>第二章</h1>' + P, extra: dict | None = None):
    files = {'OEBPS/Text/c1.xhtml': XHTML11.format(title='第一章', body=c1),
             'OEBPS/Text/c2.xhtml': XHTML11.format(title='第二章', body=c2), 'OEBPS/Images/cover.jpg': JPEG}
    files.update(extra or {})
    src = make_epub(files)
    b = Book.load(src)
    rep = optimize(b)
    data = b.to_bytes()
    out = Book.load(data)
    bc = compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out)
    assert bc.ok, bc.missing
    assert engine.fix(Book.load(data)).changes == []          # 幂等
    if shutil.which('epubcheck'):
        assert epubcheck.blocking(epubcheck.run_bytes(data)) == 0
    return out, rep, data


def docs(book):
    """正文文档（不含导航文档）。"""
    return {p: book.tree(p).getroot() for p in book.content_docs() if 'nav' not in book.item_by_path(p).properties}


def find(book, pred):
    for path, root in docs(book).items():
        for el in root.iter():
            if isinstance(el.tag, str) and pred(el):
                return path, el
    return None, None


def css(book) -> str:
    return next(book.files[p].decode() for p in book.files if p.endswith('typesetter.css'))


def test_poem_one_line_per_paragraph():
    c1 = ('<h1>第一章</h1>' + P + '<p>口内念着几句言词，道是：</p>'
          '<p>　　　　世人都晓神仙好，惟有功名忘不了！</p>'
          '<p>　　　　古今将相在何方？荒冢一堆草没了。</p>' + P)
    out, rep, _ = rebuild(c1)
    path, box = find(out, lambda e: 'poem-quote' in (e.get('class') or ''))
    # 只有两句，前无诗题：按节选写 z3998:verse（04 4.7.1.2）
    assert box is not None and box.get(EPUB_T) == 'z3998:verse' and 'poem-center' in box.get('class')
    st = box.find(X + 'p')
    assert st.get('class') == 'stanza'
    lines = st.findall(X + 'span')
    assert [s.text for s in lines] == ['世人都晓神仙好，惟有功名忘不了！', '古今将相在何方？荒冢一堆草没了。']
    assert len(st.findall(X + 'br')) == 1 and st[-1].tag == X + 'span'          # 行间一个 br，节末不带
    assert out.tree(path).getroot().get(PREFIX, '').startswith('z3998:')
    assert 'tpl:poem' in css(out) and 'tpl:letter' not in css(out)               # 只追加用到的模板


def test_poem_marked_up_with_br_and_indent():
    c1 = ('<h1>第一章</h1>' + P + '<p class="kindle-poem">春眠不觉晓，<br/>　　处处闻啼鸟。<br/><br/>'
          '夜来风雨声，<br/>花落知多少。<br/><br/></p>' + P)
    out, rep, _ = rebuild(c1)
    _, box = find(out, lambda e: 'poem-quote' in (e.get('class') or ''))
    stanzas = box.findall(X + 'p')
    assert len(stanzas) == 2                                                    # 空行 = 节界
    first = stanzas[0].findall(X + 'span')
    assert first[1].get('class') == 'line indent-1' and first[1].text == '处处闻啼鸟。'
    assert 'poem-left' in box.get('class')                                      # 有缩进不能居中


def test_prose_is_not_poem():
    c1 = '<h1>第一章</h1>' + P + '<p>他不但被逼无奈，他还是理由正当、绝无敷衍的无奈。</p>' + P
    out, rep, _ = rebuild(c1)
    assert find(out, lambda e: 'stanza' in (e.get('class') or ''))[1] is None


def test_letter():
    c1 = ('<h1>第一章</h1>' + P + '<p>骝先吾兄左右：</p><p>兹有一事与兄商之。</p><p>专此敬颂</p><p>道安</p>'
          '<p style="text-align:right">弟斯年谨上</p><p>四月十八日</p>' + P)
    out, rep, _ = rebuild(c1)
    _, box = find(out, lambda e: e.tag == X + 'blockquote' and 'letter' in (e.get('class') or ''))
    parts = [(p.get('class'), p.get(EPUB_T), p.text) for p in box]
    assert parts == [('salutation', 'z3998:salutation', '骝先吾兄左右：'), (None, None, '兹有一事与兄商之。'),
                     (None, 'z3998:valediction', '专此敬颂'), ('closing', 'z3998:valediction', '道安'),
                     ('signature', 'z3998:sender z3998:signature', '弟斯年谨上'), ('date', None, '四月十八日')]
    assert ('书信', 'B') in rep.rebuild.structures


def test_narrative_colon_is_not_letter():
    c1 = '<h1>第一章</h1>' + P + '<p>他对弟弟说：</p><p>“走吧。”</p><p style="text-align:right">——完</p>' + P
    out, _, _ = rebuild(c1)
    assert find(out, lambda e: 'letter' in (e.get('class') or ''))[1] is None


def test_numbered_list_and_note_lookalike():
    c1 = ('<h1>第一章</h1>' + P + '<p>1.绝不要追高。</p><p>2.绝不要抄底。</p><p>3.始终保持一致。</p>' + P +
          '<p><a href="c2.xhtml">1.</a>杜周：酷吏。</p><p><a href="c2.xhtml">2.</a>大宛：国名。</p>'
          '<p><a href="c2.xhtml">3.</a>执金吾：官名。</p>')
    out, rep, _ = rebuild(c1)
    _, ol = find(out, lambda e: e.tag == X + 'ol')
    assert [li.text for li in ol] == ['绝不要追高。', '绝不要抄底。', '始终保持一致。'] and ol.get('start') is None
    assert len([e for r in docs(out).values() for e in r.iter(X + 'ol')]) == 1   # 序号在链接里的不转


def test_items_and_articles():
    c1 = ('<h1>第一章</h1>' + P + '<p>（一）依法登记的；</p><p>（二）经批准设立的。</p>'
          '<p>第一条 为了保护权益，制定本法。</p><p>第二条　本法适用于下列情形。</p>' + P)
    out, _, _ = rebuild(c1)
    _, item = find(out, lambda e: (e.get('class') or '').startswith('item'))
    assert item.get('class') == 'item hang-3'
    _, art = find(out, lambda e: e.get('class') == 'article')
    no = art.find(X + 'span')
    assert no.get('class') == 'article-no' and no.text == '第一条' and no.tail == '　为了保护权益，制定本法。'


def test_container_image_kept_with_multi_paragraph_caption():
    """回归：图与图注段落同在一个 div 里时，图曾被当成空行内元素丢掉。"""
    c1 = ('<h1>第一章</h1>' + P + '<div class="image" id="pic1"><img src="../Images/cover.jpg" alt=""/>'
          '<p class="caption">专宠的悲哀</p><p class="caption2">复原图（局部）</p></div>' + P)
    out, _, _ = rebuild(c1)
    _, fig = find(out, lambda e: e.tag == X + 'figure')
    assert fig is not None and fig.find(X + 'img') is not None
    cap = fig.find(X + 'figcaption')
    assert [p.text for p in cap.findall(X + 'p')] == ['专宠的悲哀', '复原图（局部）']


def test_list_of_illustrations_links_to_figure():
    loi = ('<h1>图版目次</h1><h2>插图目录</h2><p><a href="c2.xhtml#pic1">专宠的悲哀</a></p>'
           '<p><a href="c2.xhtml#pic2">杜若花谢</a></p><p><a href="c2.xhtml#nowhere">不存在的图</a></p>')
    c2 = ('<h1>第二章</h1>' + P + '<div id="pic1"><img src="../Images/cover.jpg" alt=""/><p>专宠的悲哀</p></div>' + P +
          '<div id="pic2"><img src="../Images/cover.jpg" alt=""/><p>杜若花谢</p></div>' + P)
    out, rep, _ = rebuild(loi, c2)
    path, nav = find(out, lambda e: e.tag == X + 'nav' and e.get(EPUB_T) == 'loi')
    assert path.endswith('loi.xhtml') and nav.get('id') == 'loi'
    links = [a.get('href') for a in nav.iter(X + 'a')]
    assert len(links) == 2 and all('#figure-' in h for h in links)
    target = links[0].split('#')[1]
    assert find(out, lambda e: e.tag == X + 'figure' and e.get('id') == target)[1] is not None
    assert any('不存在的图' in s['text'] for s in rep.rebuild.suggestions)
    nav_doc = next(i.path for i in out.manifest() if 'nav' in i.properties)
    assert 'epub:type="loi"' in out.files[nav_doc].decode()                    # landmarks 收录


def test_table_normalized_with_caption_and_note():
    c1 = ('<h1>第一章</h1>' + P + '<p>表 2-1　各季度销量</p>'
          '<table border="1"><tr><td>季度</td><td>销量</td><td>同比</td></tr>'
          '<tr><td>一季度</td><td>1,500</td><td>+5%</td></tr><tr><td>二季度</td><td>750</td><td>-2%</td></tr></table>'
          '<p>注：同比以上年同期为基数。</p>' + P)
    out, _, _ = rebuild(c1)
    _, t = find(out, lambda e: e.tag == X + 'table')
    assert t[0].tag == X + 'caption' and ''.join(t[0].itertext()) == '表 2-1　各季度销量'
    assert [th.text for th in t.find(X + 'thead').iter(X + 'th')] == ['季度', '销量', '同比']
    assert t.find(X + 'tr') is None and t.get('border') is None                 # 无裸 tr、无表现型属性
    assert [td.get('class') for td in t.find(X + 'tbody')[0]] == [None, 'num', 'num']
    _, note = find(out, lambda e: e.get('class') == 'table-note')
    assert note.text.startswith('注：')


def test_glossary_dl():
    c2 = ('<h1>术语表</h1><dl><dt>夔</dt><dd>传说中的一足神兽。</dd><dt>庶人</dt><dd>平民百姓的泛称。</dd></dl>')
    out, _, _ = rebuild('<h1>第一章</h1>' + P, c2)
    path, dl = find(out, lambda e: e.tag == X + 'dl')
    assert dl.get('class') == 'glossary'
    dt, dd = dl[0], dl[1]
    assert dt.get(EPUB_T) == 'glossterm' and dt.find(X + 'dfn').text == '夔'
    assert dd.get(EPUB_T) == 'glossdef' and dd.find(X + 'p').text == '传说中的一足神兽。'
    sec = out.tree(path).getroot().find(f'.//{X}section')
    assert sec.get(EPUB_T) == 'glossary' and sec.get('role') == 'doc-glossary' and path.endswith('glossary.xhtml')


def test_script_only_suggested():
    lines = ''.join(f'<p>{n}：台词第{i}句，内容。</p>' for i in range(12) for n in ('铁梅', '李奶奶'))
    out, rep, _ = rebuild('<h1>第一幕</h1>' + lines)
    assert any(s['kind'] == 'script' for s in rep.rebuild.suggestions)
    assert find(out, lambda e: 'persona' in (e.get('class') or ''))[1] is None


# ---------- 规则 ----------

def fixed(body: str):
    b = Book.load(make_epub({'OEBPS/Text/c1.xhtml': XHTML11.format(title='一', body=body)}))
    rep = engine.fix(b)
    return Book.load(b.to_bytes()), rep


def test_rule_poem_structure_and_semantics():
    body = ('<h1>一</h1><div class="poem poem-center"><p class="stanza" epub:type="z3998:poem">'
            '<span class="line">　　床前明月光，</span><br/><span class="line">疑是地上霜。</span><br/></p></div>')
    body = body.replace('<div', '<div xmlns:epub="http://www.idpf.org/2007/ops"', 1)
    b, rep = fixed(body)
    root = b.tree('OEBPS/Text/c1.xhtml').getroot()
    box = root.find(f'.//{X}div')
    st = box.find(X + 'p')
    assert box.get(EPUB_T) == 'z3998:poem' and st.get(EPUB_T) is None
    assert 'poem-left' in box.get('class')                                     # 居中诗出现缩进 → 居左
    assert st[0].get('class') == 'line indent-1' and st[0].text == '床前明月光，'
    assert st[-1].tag == X + 'span'
    assert root.get(PREFIX, '').startswith('z3998:')
    assert not {'SEM-034', 'SEM-035'} & {i.rule_id for i in rep.after}


def test_rule_table_bare_rows():
    b, rep = fixed('<h1>一</h1><table><thead><tr><td>甲</td></tr></thead><tr><td>1</td></tr></table>')
    t = b.tree('OEBPS/Text/c1.xhtml').getroot().find(f'.//{X}table')
    assert t.find(X + 'tr') is None and t.find(f'{X}tbody/{X}tr') is not None
    assert t.find(f'{X}thead//{X}th') is not None


def test_rule_alt_text_cleanup():
    b, rep = fixed('<h1>一</h1><figure><img src="../Images/cover.jpg" alt="图片：山\u00a0水"/>'
                   '<figcaption>图 1</figcaption></figure>')
    img = b.tree('OEBPS/Text/c1.xhtml').getroot().find(f'.//{X}img')
    assert img.get('alt') == '山水'
    assert any(i.rule_id == 'A11Y-015' and i.severity == 'info' for i in rep.after)   # 缺句末标点只提示
