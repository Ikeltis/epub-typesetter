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


# ---------- 确认板与用户决定 ----------

from epub_typesetter import board  # noqa: E402


def rebuild_with(c1: str, decide, c2: str = '<h1>第二章</h1>' + P):
    """先按默认重建拿到确认板，decide(board) 返回决定，再按决定重建。"""
    files = {'OEBPS/Text/c1.xhtml': XHTML11.format(title='第一章', body=c1),
             'OEBPS/Text/c2.xhtml': XHTML11.format(title='第二章', body=c2), 'OEBPS/Images/cover.jpg': JPEG}
    src = make_epub(files)
    b = Book.load(src)
    rep = optimize(b)
    bd = board.build(rep.analysis, rep.rebuild.head_kind)
    dec = board.clean(decide(bd))
    b = Book.load(src)
    rep = optimize(b, decisions=dec)
    data = b.to_bytes()
    out = Book.load(data)
    bc = compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out)
    assert bc.ok, bc.missing
    if shutil.which('epubcheck'):
        assert epubcheck.blocking(epubcheck.run_bytes(data)) == 0
    return out, rep, board.build(rep.analysis, rep.rebuild.head_kind, dec)


def test_board_cluster_reassign():
    c1 = ('<h1>第一章</h1>' + P * 3 + '<p class="yin">引文第一段，内容。</p><p class="yin">引文第二段，内容。</p>'
          '<p class="yin">引文第三段，内容。</p>' + P + '<p class="ad">扫码关注</p><p class="ad">扫码领书</p>'
          '<p class="ad">扫码进群</p>' + '<p class="sub">一个小标题</p>' * 1 + P)

    def decide(bd):
        key = lambda cls: next(c['key'] for c in bd['clusters'] if f'|{cls}|' in c['key'])
        assert any(c['body'] for c in bd['clusters'])
        return {'clusters': {key('yin'): 'quote', key('ad'): 'junk', key('sub'): 'section'}}
    out, rep, bd = rebuild_with(c1, decide)
    _, bq = find(out, lambda e: e.tag == X + 'blockquote')
    assert bq is not None and len(bq) == 3
    assert find(out, lambda e: e.text and '扫码' in e.text)[1] is None
    assert ('junk', '扫码关注') in rep.rebuild.removed
    _, h = find(out, lambda e: e.get('class') == 'section-title')
    assert h is not None and h.text == '一个小标题' and h.tag == X + 'h3'


def test_board_reject_structure_and_accept_suggestions():
    lines = ''.join(f'<p>{n}：台词第{i}句，内容。</p>' for i in range(12) for n in ('铁梅', '李奶奶'))
    c1 = ('<h1>第一章</h1>' + P + '<p>1.第一。</p><p>2.第二。</p><p>3.第三。</p>' + P +
          '<p>他不想再说，只是低头，</p><p>未卜三生愿，频添一段愁。</p><p>闷来时敛额，行去几回眸。</p>' + P)
    c2 = '<h1>第一幕</h1>' + lines + '<p>（幕落）</p>'

    def decide(bd):
        ol = next(k for k in bd['structures'] if k['kind'] == 'ol')
        poem = next(s for s in bd['suggestions'] if s['kind'] == 's-poem')
        script = next(s for s in bd['suggestions'] if s['kind'] == 's-script')
        assert poem['actionable'] and not poem['applied']
        return {'kinds': {'ol': False}, 'items': {poem['key']: True, script['key']: True}}
    out, rep, bd = rebuild_with(c1, decide, c2)
    assert find(out, lambda e: e.tag == X + 'ol')[1] is None
    _, p1 = find(out, lambda e: e.tag == X + 'p' and (e.text or '').startswith('1.'))
    assert p1 is not None                                                   # 拒绝后原样保留序号文字
    assert find(out, lambda e: 'stanza' in (e.get('class') or ''))[1] is not None
    path, d = find(out, lambda e: 'dialogue-run' in (e.get('class') or ''))
    sp = d.find(X + 'span')
    assert sp.get('class') == 'persona' and sp.text == '铁梅' and sp.tail.startswith('：台词')
    assert 'z3998:drama' in out.tree(path).getroot().find(f'.//{X}section').get(EPUB_T)
    assert find(out, lambda e: e.get('class') == 'stage')[1].text == '（幕落）'
    assert 'min-width:3em' in css(out) and '{N' not in css(out)            # {N} 代入最长角色名字数（李奶奶）
    assert next(s for s in bd['suggestions'] if s['kind'] == 's-poem')['applied']
    ol = next(k for k in bd['structures'] if k['kind'] == 'ol')
    assert ol['items'][0]['accepted'] is False and ol['items'][0]['lines']    # 被拒绝的仍显示样例


def test_board_glossary_lines_and_tfoot():
    terms = ''.join(f'<p>术语{i}：这是第{i}个术语的释义。</p>' for i in range(6))
    c2 = '<h1>术语表</h1>' + terms
    c1 = ('<h1>第一章</h1>' + P + '<table><tr><th>项</th><th>数</th></tr><tr><td>甲</td><td>1</td></tr>'
          '<tr><td>合计</td><td>1</td></tr></table>' + P)

    def decide(bd):
        return {'kinds': {'s-glossary': True, 's-table': True}}
    out, rep, _ = rebuild_with(c1, decide, c2)
    _, dl = find(out, lambda e: e.tag == X + 'dl')
    assert dl.get('class') == 'glossary' and dl[0].find(X + 'dfn').text == '术语0'
    assert dl[1].find(X + 'p').text == '这是第0个术语的释义。'
    _, foot = find(out, lambda e: e.tag == X + 'tfoot')
    assert foot is not None and foot[0][0].tag == X + 'th' and foot[0][0].get('scope') == 'row'


def test_decisions_clean_rejects_garbage():
    d = board.clean({'clusters': {'a': 'quote', 'b': 'evil'}, 'kinds': {'poem': 'yes'}, 'items': {'x': False},
                     'extra': 1})
    assert d == {'version': 1, 'clusters': {'a': 'quote'}, 'kinds': {}, 'items': {'x': False}, 'heads': {}, 'matter': {},
                 'alts': {}}
    d = board.clean({'heads': {'k': 'section', 'j': 'h7'}, 'matter': {'k': 'afterword', 'j': 'evil'}})
    assert d['heads'] == {'k': 'section'} and d['matter'] == {'k': 'afterword'}


def test_board_heads_and_matter():
    c1 = '<h1>第一章</h1>' + P + '<h2>不是标题的短句</h2>' + P
    c2 = '<h1>写在后面</h1>' + P

    def decide(bd):
        k = {h['text']: h['key'] for h in bd['heads']}
        assert bd['heads'][0]['kind'] == 'chapter'
        return {'heads': {k['不是标题的短句']: 'para'}, 'matter': {k['写在后面']: 'afterword'}}
    out, rep, bd = rebuild_with(c1, decide, c2)
    _, p = find(out, lambda e: e.text == '不是标题的短句')
    assert p.tag == X + 'p'
    path, sec = find(out, lambda e: e.tag == X + 'section' and e.get(EPUB_T) == 'afterword')
    assert sec is not None and sec.get('role') == 'doc-afterword' and path.endswith('afterword.xhtml')


# ---------- 注释配对：注号与注文互相链接（04 4.12.5） ----------

def test_mutual_link_notes_bare_digits_and_shared_labels():
    body = ('<h1>第一章</h1>' + P +
            '<p>正文甲<a id="z1" href="c2.xhtml#bz1">1</a>继续，正文乙<a id="z2" href="c2.xhtml#bz2">2</a>结束。</p>' + P)
    notes = ('<h1>第二章</h1>' + P + '<p><b>第一章　注释</b></p>'
             '<p class="zhu"><a id="bz1" href="c1.xhtml#z1">[1]</a><a id="bz2" href="c1.xhtml#z2">[2]</a>《某书》，某社出版。</p>')
    out, rep, _ = rebuild(body, notes)
    assert rep.rebuild.notes == 1                                   # 两个注号共用一条注文
    _, li = find(out, lambda e: e.tag == X + 'li' and e.get('id') == 'note-1')
    assert ''.join(li.itertext()).startswith('《某书》')               # 开头的「[1][2]」都去掉
    refs = [a for r in docs(out).values() for a in r.iter(X + 'a') if a.get('class') == 'noteref']
    assert [a.get('id') for a in refs] == ['noteref-1', 'noteref-1-2']
    assert ('note-head', '第一章　注释') in rep.rebuild.removed


def test_backlink_direction_does_not_make_body_a_note():
    """注文的回链指着正文段落：正文段落中间有注号，不能反过来被当成注文（红楼梦的写法）。"""
    body = ('<h1>第一章</h1>' + P + '<p>正文<a id="ref1" href="c1.xhtml#back1"><sup>①</sup></a>继续写。</p>' + P +
            '<p><a id="back1" href="c1.xhtml#ref1">①</a>这是校记。</p>')
    out, rep, _ = rebuild(body)
    assert rep.rebuild.notes == 1
    _, p = find(out, lambda e: e.tag == X + 'p' and '继续写' in ''.join(e.itertext()))
    assert p is not None and p.find(f'.//{X}a').get('class') == 'noteref'


def test_backlink_target_starting_with_same_digit_is_not_a_note():
    """回归：正文段落以「7月9日」开头、段中注号是「7」，不能因为字面相同被当成注文开头。"""
    body = ('<h1>第一章</h1>' + P + '<p>7月9日，正文写到这里<a id="z7" href="c2.xhtml#bz7">7</a>继续。</p>' + P)
    notes = '<h1>第二章</h1>' + P + '<p><a id="bz7" href="c1.xhtml#z7">[7]</a>《某书》。</p>'
    out, rep, _ = rebuild(body, notes)
    assert rep.rebuild.notes == 1
    _, p = find(out, lambda e: e.tag == X + 'p' and '正文写到这里' in ''.join(e.itertext()))
    assert p is not None and p.find(f'.//{X}a').get('class') == 'noteref'
