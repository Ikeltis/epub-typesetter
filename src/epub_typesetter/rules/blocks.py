"""成组结构的检查：表格、伪列表、诗歌、书信与剧本、术语表、alt 文字（guide/07 §2.2、§2.7）。

这些规则查的是「已经写成某种结构」的地方是否合规；把原书识别成诗、信、列表是重建（structures.py）的事。
"""
from __future__ import annotations

import re

from ..engine import AUTO, INFO, MANUAL, SUGGEST, WARNING, Rule, register
from ..tables import bare_rows, thead_td_to_th, wrap_bare_rows
from ..xhtml import EPUB_TYPE, X, body, squash
from .text import indent_width

POEM_TYPES = {'z3998:poem', 'z3998:verse', 'z3998:song', 'z3998:hymn'}
LAYOUTS = ('poem-center', 'poem-left', 'poem-ci')
LEAD = re.compile(r'^[\u3000\u00a0\u2002\u2003]+')
OL_LIKE = re.compile(r'^\s*(\d{1,3})[.．、)）](?!\d)\s*\S')
BULLET_LIKE = re.compile(r'^\s*[·•●■]\s*\S')
INVISIBLE_ALT = re.compile(r'[\u00a0\u2060\u200b]')
ALT_PREFIX = re.compile(r'^(图片|插图|图)[：:]\s*')


def _cls(el) -> list[str]:
    return (el.get('class') or '').split()


def _types(el) -> list[str]:
    return (el.get(EPUB_TYPE) or '').split()


def _docs(book):
    for path in book.content_docs():
        it = book.item_by_path(path)
        if it is not None and 'nav' in it.properties:
            continue
        yield path, book.tree(path).getroot()


# ---------- 表格 ----------

@register
class TableSemantics(Rule):
    """SEM-013：裸 tr 包进 tbody、thead 里的 td 改 th 可自动修；缺表头、缺表题只提示。"""
    id, title, order = 'SEM-013', '表格语义', 36
    node_fix = True

    def check(self, book):
        out = []
        for path, root in _docs(book):
            auto_hits, other_hits, notes = [], [], set()
            for t in body(root).iter(X + 'table'):
                if bare_rows(t):
                    auto_hits.append(self.hit(t, fix={'op': 'wrap', 'with': 'tbody'}))
                    notes.add('tr 不在 thead/tbody 里')
                if any(td is not None for th in t.iter(X + 'thead') for td in th.iter(X + 'td')):
                    auto_hits.append(self.hit(t, fix={'op': 'rename', 'from': 'td', 'to': 'th'}))
                    notes.add('thead 内用了 td')
                rows = t.findall('.//' + X + 'tr')
                if len(rows) >= 2 and t.find('.//' + X + 'th') is None:
                    other_hits.append(self.hit(t))
                    notes.add('没有表头 th')
            if auto_hits:
                out.append(self.issue(WARNING, f'表格结构：{"、".join(sorted(notes))}', path, AUTO,
                                      hits=auto_hits + other_hits))
            elif other_hits:
                out.append(self.issue(WARNING, f'{len(other_hits)} 张表格没有表头 th', path, SUGGEST, hits=other_hits))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            keep = i.waived_nodes()
            n = 0
            for t in body(book.tree(i.file).getroot()).iter(X + 'table'):
                if t in keep:
                    continue
                n += wrap_bare_rows(t) + thead_td_to_th(t)
            if n:
                book.mark_dirty(i.file)
                log.append(f'{i.file}：表格结构规范化 {n} 处（tr 包进 tbody、表头 td 改 th）')
        return log


@register
class PseudoList(Rule):
    """SEM-014：手写序号、手写圆点的连续段落，应为 ol/ul（只提示，重建时转换）。"""
    id, title, order = 'SEM-014', '伪列表', 61

    def check(self, book):
        out = []
        for path, root in _docs(book):
            hits = []
            ps = list(body(root).iter(X + 'p'))
            i = 0
            while i < len(ps):
                txt = ''.join(ps[i].itertext())
                m = OL_LIKE.match(txt)
                if m:
                    j, last = i + 1, int(m.group(1))
                    while j < len(ps) and (mm := OL_LIKE.match(''.join(ps[j].itertext()))) and int(mm.group(1)) == last + 1:
                        last, j = last + 1, j + 1
                    if j - i >= 3:
                        hits.append(self.hit(ps[i]))
                    i = j
                    continue
                if BULLET_LIKE.match(txt):
                    j = i + 1
                    while j < len(ps) and BULLET_LIKE.match(''.join(ps[j].itertext())):
                        j += 1
                    if j - i >= 2:
                        hits.append(self.hit(ps[i]))
                    i = j
                    continue
                i += 1
            if hits:
                out.append(self.issue(INFO, f'{len(hits)} 组手写序号或圆点段落，应为列表', path, SUGGEST, hits=hits))
        return out


# ---------- 诗歌 ----------

def _poem_boxes(root):
    for el in body(root).iter():
        if isinstance(el.tag, str) and (set(_cls(el)) & {'poem', 'poem-quote'} or set(_types(el)) & POEM_TYPES):
            yield el


@register
class PoemStructure(Rule):
    """SEM-034：p.stanza 里不留裸文字、行首不用空格缩进、节末不带 br。"""
    id, title, order = 'SEM-034', '诗歌结构', 33
    node_fix = True

    @staticmethod
    def _problems(st) -> list[str]:
        out = []
        if (st.text or '').strip() or any((c.tail or '').strip() for c in st if isinstance(c.tag, str)):
            out.append('bare')
        if any(LEAD.match(sp.text or '') for sp in st if 'line' in _cls(sp)):
            out.append('lead')
        kids = [c for c in st if isinstance(c.tag, str)]
        if kids and kids[-1].tag == X + 'br':
            out.append('tail-br')
        return out

    def check(self, book):
        out = []
        for path, root in _docs(book):
            hits, kinds = [], set()
            for st in body(root).iter(X + 'p'):
                if 'stanza' not in _cls(st):
                    continue
                pr = self._problems(st)
                if pr:
                    hits.append(self.hit(st))
                    kinds.update(pr)
            if hits:
                names = {'bare': '节内有裸文字', 'lead': '行首用空格缩进', 'tail-br': '节末多余 br'}
                out.append(self.issue(WARNING, '诗歌结构：' + '、'.join(names[k] for k in sorted(kinds)), path, AUTO,
                                      hits=hits))
        return out

    def fix(self, book, issues):
        from lxml import etree
        log = []
        for i in issues:
            keep = i.waived_nodes()
            n = 0
            for st in list(body(book.tree(i.file).getroot()).iter(X + 'p')):
                if 'stanza' not in _cls(st) or st in keep:
                    continue
                # 裸文字：按 br 切开，每段包进 span.line
                if 'bare' in self._problems(st):
                    lines, cur = [], [st.text or '']
                    st.text = None
                    for c in list(st):
                        if c.tag == X + 'br':
                            lines.append(cur)
                            cur = [c.tail or '']
                        else:
                            cur.append(c)
                            if c.tail:
                                cur.append(c.tail)
                                c.tail = None
                        st.remove(c)
                    lines.append(cur)
                    first = True
                    for parts in lines:
                        if not any(isinstance(x, str) and x.strip() or not isinstance(x, str) for x in parts):
                            continue
                        if not first:
                            st.append(etree.Element(X + 'br'))
                        first = False
                        if len(parts) == 1 and not isinstance(parts[0], str) and 'line' in _cls(parts[0]):
                            st.append(parts[0])
                            continue
                        sp = etree.SubElement(st, X + 'span', {'class': 'line'})
                        for x in parts:
                            if isinstance(x, str):
                                if len(sp):
                                    sp[-1].tail = (sp[-1].tail or '') + x
                                else:
                                    sp.text = (sp.text or '') + x
                            else:
                                sp.append(x)
                        if sp.text:
                            sp.text = sp.text.strip('\n\t ') or None
                    n += 1
                for sp in st:
                    if 'line' in _cls(sp) and LEAD.match(sp.text or ''):
                        w = indent_width(LEAD.match(sp.text).group(0))
                        sp.text = LEAD.sub('', sp.text) or None
                        lv = min(3, int(-(-w // 2)))
                        if lv and not any(c.startswith('indent-') for c in _cls(sp)):
                            sp.set('class', ' '.join(_cls(sp) + [f'indent-{lv}']))
                        n += 1
                kids = [c for c in st if isinstance(c.tag, str)]
                while kids and kids[-1].tag == X + 'br':
                    br = kids.pop()
                    st.remove(br)
                    n += 1
            if n:
                book.mark_dirty(i.file)
                log.append(f'{i.file}：诗歌结构规范化 {n} 处')
        return log


@register
class PoemSemantics(Rule):
    """SEM-035：诗歌容器的 epub:type 与排版型类。"""
    id, title, order = 'SEM-035', '诗歌语义与排版型', 33
    node_fix = True

    def check(self, book):
        out = []
        for path, root in _docs(book):
            auto, sugg, kinds = [], [], set()
            for box in _poem_boxes(root):
                ty, cl = set(_types(box)), set(_cls(box))
                if not ty & POEM_TYPES:
                    auto.append(self.hit(box, fix={'op': 'set_attr', 'name': 'epub:type', 'value': 'z3998:poem'}))
                    kinds.add('容器缺 z3998 类型')
                if 'poem-center' in cl and box.find('.//' + X + 'span') is not None and \
                        any(c.startswith('indent-') for sp in box.iter(X + 'span') for c in _cls(sp)):
                    auto.append(self.hit(box, fix={'op': 'set_attr', 'name': 'class', 'value': 'poem-left'}))
                    kinds.add('居中诗用了缩进')
                if any(set(_types(x)) & POEM_TYPES for x in box.iter(X + 'p', X + 'span')):
                    auto.append(self.hit(box))
                    kinds.add('epub:type 写在节或行上')
                if len(cl & set(LAYOUTS)) != 1:
                    sugg.append(self.hit(box))
                    kinds.add('排版型类不是恰好一个')
            if auto:
                out.append(self.issue(WARNING, '诗歌语义：' + '、'.join(sorted(kinds)), path, AUTO, hits=auto + sugg))
            elif sugg:
                out.append(self.issue(WARNING, '诗歌语义：' + '、'.join(sorted(kinds)), path, SUGGEST, hits=sugg))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            keep = i.waived_nodes()
            n = 0
            for box in list(_poem_boxes(book.tree(i.file).getroot())):
                if box in keep:
                    continue
                if not set(_types(box)) & POEM_TYPES:
                    box.set(EPUB_TYPE, ' '.join(_types(box) + ['z3998:poem']))
                    n += 1
                cl = _cls(box)
                if 'poem-center' in cl and any(c.startswith('indent-') for sp in box.iter(X + 'span') for c in _cls(sp)):
                    box.set('class', ' '.join('poem-left' if c == 'poem-center' else c for c in cl))
                    n += 1
                for x in box.iter(X + 'p', X + 'span'):
                    rest = [t for t in _types(x) if t not in POEM_TYPES]
                    if len(rest) != len(_types(x)):
                        if rest:
                            x.set(EPUB_TYPE, ' '.join(rest))
                        else:
                            del x.attrib[EPUB_TYPE]
                        n += 1
            if n:
                book.mark_dirty(i.file)
                log.append(f'{i.file}：诗歌语义修正 {n} 处')
        return log


# ---------- 书信与剧本、术语表 ----------

@register
class LetterScript(Rule):
    """SEM-037：只提示（书信缺称谓语义、用了不存在的 z3998 词、对白写法混用、角色名含空白冒号）。"""
    id, title, order = 'SEM-037', '书信与剧本结构', 62

    def check(self, book):
        out = []
        for path, root in _docs(book):
            hits, kinds = [], set()
            b = body(root)
            for el in b.iter():
                if not isinstance(el.tag, str):
                    continue
                if 'letter' in _cls(el) and not any('z3998:salutation' in _types(x) for x in el.iter()
                                                   if isinstance(x.tag, str)):
                    hits.append(self.hit(el))
                    kinds.add('书信容器里没有称谓')
                if {'z3998:dateline', 'z3998:act'} & set(_types(el)):
                    hits.append(self.hit(el))
                    kinds.add('用了不存在的 z3998:dateline / z3998:act')
                if 'persona' in _cls(el) and re.search(r'[\s：:]', ''.join(el.itertext())):
                    hits.append(self.hit(el))
                    kinds.add('角色名含空白或冒号')
            if b.find('.//' + X + "p[@class='speaker-line']") is not None and \
                    any('dialogue-run' in _cls(p) for p in b.iter(X + 'p')):
                kinds.add('对白写法 A、B 混用')
                hits.append(self.hit(b))
            if hits:
                out.append(self.issue(INFO, '书信、剧本：' + '、'.join(sorted(kinds)), path, SUGGEST, hits=hits))
        return out


@register
class GlossaryStructure(Rule):
    """SEM-040：术语表的 dt 含 dfn、dd 含块级子元素（只提示，重建时规范化）。"""
    id, title, order = 'SEM-040', '术语表结构', 63

    def check(self, book):
        out = []
        for path, root in _docs(book):
            hits = []
            for dt in body(root).iter(X + 'dt'):
                if 'glossterm' in _types(dt) and dt.find('.//' + X + 'dfn') is None:
                    hits.append(self.hit(dt))
            for dd in body(root).iter(X + 'dd'):
                if 'glossdef' in _types(dd) and not any(c.tag in (X + 'p', X + 'ul', X + 'ol', X + 'blockquote')
                                                        for c in dd):
                    hits.append(self.hit(dd))
            if hits:
                out.append(self.issue(INFO, f'术语表 {len(hits)} 处词条缺 dfn 或释义缺段落', path, SUGGEST, hits=hits))
        return out


# ---------- alt ----------

def _caption_text(img) -> str | None:
    fig = img.getparent()
    while fig is not None and fig.tag != X + 'figure':
        fig = fig.getparent()
    if fig is None:
        return None
    cap = fig.find(X + 'figcaption')
    return squash(''.join(cap.itertext())) if cap is not None else None


@register
class AltEqualsCaption(Rule):
    """A11Y-014：alt 与图注一字不差，读屏会念两遍（只报告，不自动改）。"""
    id, title, order = 'A11Y-014', 'alt 与图注相同', 93

    def check(self, book):
        out = []
        for path, root in _docs(book):
            hits = [self.hit(img) for img in body(root).iter(X + 'img')
                    if (img.get('alt') or '').strip() and squash(img.get('alt')) == _caption_text(img)]
            if hits:
                out.append(self.issue(INFO, f'{len(hits)} 张图的 alt 与图注相同', path, MANUAL, hits=hits))
        return out


@register
class AltText(Rule):
    """A11Y-015：alt 里的不可见字符、「图片：」前缀自动删；块级图 alt 缺句末标点只提示。"""
    id, title, order = 'A11Y-015', 'alt 文字规范', 94
    node_fix = True

    def check(self, book):
        out = []
        for path, root in _docs(book):
            auto, sugg = [], []
            for img in body(root).iter(X + 'img'):
                alt = img.get('alt') or ''
                if INVISIBLE_ALT.search(alt) or ALT_PREFIX.match(alt):
                    auto.append(self.hit(img, fix={'op': 'set_attr', 'name': 'alt'}))
                elif alt.strip() and 'glyph' not in _cls(img) and _caption_text(img) is not None \
                        and not re.search(r'[。！？.!?]$', alt.strip()):
                    sugg.append(self.hit(img))
            if auto:
                out.append(self.issue(WARNING, f'{len(auto)} 张图的 alt 含不可见字符或「图片：」前缀', path, AUTO, hits=auto))
            if sugg:
                out.append(self.issue(INFO, f'{len(sugg)} 张插图的 alt 不是以句末标点结尾的完整句子', path, SUGGEST,
                                      hits=sugg))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            keep = i.waived_nodes()
            n = 0
            for img in body(book.tree(i.file).getroot()).iter(X + 'img'):
                alt = img.get('alt') or ''
                new = ALT_PREFIX.sub('', INVISIBLE_ALT.sub('', alt))
                if new != alt and img not in keep:
                    img.set('alt', new)
                    n += 1
            if n:
                book.mark_dirty(i.file)
                log.append(f'{i.file}：清理 alt {n} 处')
        return log


# ---------- 封面 ----------

@register
class DuplicateCover(Rule):
    """RES-019（部分）：全书只有一个封面页。只放封面图的页面不止一个，或封面图又在正文里当插图出现，读者会看到两个封面。
    只报告；排版重建会删去原封面页、另生成标准封面页。"""
    id, title, order = 'RES-019', '封面页写法', 95

    def check(self, book):
        from ..book import NS as _NS
        cover = next((i.path for i in book.manifest() if 'cover-image' in i.properties), None)
        if cover is None:
            return []
        pages, extra = [], []
        for it in book.spine_items():
            if it.path not in book.files or it.media_type != 'application/xhtml+xml' or 'nav' in it.properties:
                continue
            root = book.tree(it.path).getroot()
            b = body(root)
            imgs = [e for e in b.iter() if isinstance(e.tag, str) and e.tag.rsplit('}', 1)[-1] in ('img', 'image')]
            srcs = [book.resolve(it.path, (e.get('src') or e.get('{%s}href' % _NS['xlink']) or '').strip()) for e in imgs]
            hits = [e for e, s in zip(imgs, srcs) if s == cover]
            if not hits:
                continue
            if not ''.join(b.itertext()).strip() and all(s == cover for s in srcs):
                pages.append((it.path, hits[0]))
            else:
                extra.extend((it.path, h) for h in hits)
        n = len(pages) + len(extra)
        if n <= 1:
            return []
        out = []
        for path, el in pages[1:] + extra if pages else extra[1:]:
            out.append(self.issue(WARNING, f'封面图在全书出现 {n} 次（只放封面图的页面 {len(pages)} 个），读者会看到重复的封面',
                                  path, SUGGEST, hits=[self.hit(el)],
                                  hint='全书只留一个封面页：删去重复的封面页或正文里的封面图；「排版重建」会自动处理。'))
        return out
