"""重建（M2）：按语义分析结果把正文重写成干净的 EPUB 3 结构。

- 一级标题处拆分文件（章），全书链接按 id 映射同步；
- 角色 → 语义标签：h1/h2、figure+figcaption、ul、blockquote、p.source/meta/align-*；
- 注释 → EPUB 3 标准弹注（noteref + aside footnote + 回链），全书连续编号，放在所在章末；
- 去掉表现型 span/style，统一换成主题样式表（themes/default.css，来自 guide/03、04）；
- 书内目录页、注释区小标题、广告页删除（全部记录在 RebuildReport.removed，供文字校验与界面展示）；
- 重新生成封面页、nav、NCX。

表格、pre 等无法安全改写的块原样保留。
"""
from __future__ import annotations

import copy
import posixpath
import re
from dataclasses import dataclass, field
from importlib import resources
from xml.sax.saxutils import escape

from lxml import etree

from .book import NS, Book
from .nav import NCX, Entry, build_nav, ncx_path
from .semantic import BULLET_RE, NOTE_LABEL_RE, Analysis, Block, _local, _size_level, _style_of, class_styles
from .upgrade import book_language, content_properties
from .xhtml import X, is_external

EPUB = '{%s}' % NS['epub']
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
KEEP_INLINE = {'a', 'b', 'strong', 'i', 'em', 'sup', 'sub', 'u', 's', 'del', 'ins', 'abbr', 'cite', 'q', 'code',
               'kbd', 'samp', 'ruby', 'rt', 'rp', 'rb', 'small', 'time', 'var', 'dfn', 'mark', 'bdi', 'bdo', 'wbr',
               'br', 'img', 'span'}
REMOVED_ROLES = {'toc', 'note-head', 'junk'}
TYPE_BY_TITLE = [
    (re.compile(r'^版权'), 'copyright-page', None),
    (re.compile(r'^(编辑手记|前言|序|序言|自序|推荐序|代序|引言|导言|导读|致读者|写在前面)'), 'preface', 'doc-preface'),
    (re.compile(r'^(致谢|鸣谢)'), 'acknowledgments', 'doc-acknowledgments'),
    (re.compile(r'^(后记|尾声|结语|跋)'), 'afterword', 'doc-afterword'),
    (re.compile(r'^附录'), 'appendix', 'doc-appendix'),
    (re.compile(r'^(参考文献|参考书目)'), 'bibliography', 'doc-bibliography'),
]


@dataclass
class Chapter:
    title: str
    blocks: list[Block] = field(default_factory=list)
    path: str = ''
    epub_type: str = 'chapter'
    role: str | None = 'doc-chapter'


@dataclass
class RebuildReport:
    removed: list[tuple[str, str]] = field(default_factory=list)     # (角色, 文字)
    chapters: list[str] = field(default_factory=list)
    notes: int = 0
    log: list[str] = field(default_factory=list)


def theme_css(name: str = 'default') -> bytes:
    return resources.files('epub_typesetter').joinpath(f'themes/{name}.css').read_bytes()


def _el(tag: str, attrib: dict | None = None, text: str | None = None) -> etree._Element:
    e = etree.Element(X + tag, {k: v for k, v in (attrib or {}).items() if v is not None})
    if text:
        e.text = text
    return e


_HAN_PUNCT = r'[\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]'   # 汉字与全角标点


def _clean_ws(s: str) -> str:
    """源码排版产生的换行：夹在汉字/全角标点之间的删掉，其余变一个空格。"""
    if not s:
        return s
    s = s.replace('\r', '\n')
    s = re.sub(rf'(?<={_HAN_PUNCT})[ \t]*\n\s*(?={_HAN_PUNCT})', '', s)
    return re.sub(r'[ \t]*\n[\s]*', ' ', s)


class Rebuilder:
    def __init__(self, book: Book, an: Analysis, theme: str = 'default'):
        self.book, self.an, self.theme = book, an, theme
        self.rep = RebuildReport()
        self.out_dir = posixpath.dirname(an.blocks[0].doc) if an.blocks else book.opf_dir
        self.css_path = posixpath.join(book.opf_dir, 'styles', 'typesetter.css') if book.opf_dir \
            else 'styles/typesetter.css'
        self.lang = book_language(book) or 'zh'
        self.id_map: dict[tuple[str, str], str] = {}     # (旧文档, id) → 新文档
        self.doc_map: dict[str, str] = {}                # 旧文档 → 新文档（其第一块所在）
        self.noteref_els: dict[int, tuple[int, str]] = {}  # id(<a>) → (注序号, 注所在章)
        self.note_of_block: dict[int, int] = {}          # 注块序号 → 注序号
        self.cur_doc = ''                                 # 正在渲染的块所在的旧文档
        self.cur_new = ''                                 # 正在写入的新文档
        self.heading_no = 0
        self.classes = class_styles(book)                # 原样式表的类样式：用于把语义性的行内样式映射到主题类
        self.img_height: dict[str, int | None] = {}
        self.note_home: dict[int, str] = {}              # 注块序号 → 注文所在新文档
        self.notes_for: dict[str, list] = {}             # 新文档 → [(注序号, 注块)]
        self.frag_map: dict[tuple[str, str], str] = {}   # (旧文档, id) → 新 id（id 被替换时）
        self.removed_docs: set[str] = set()

    # ---------- 1. 分章 ----------

    def split(self) -> list[Chapter]:
        chapters: list[Chapter] = []
        cur = None
        # 拆分层级：一级标题只有一个（书名级大标题）时往下一级拆，否则全书会并成一个文件
        heads = [b for b in self.an.blocks if b.role == 'heading']
        split_level = next((lv for lv in (1, 2, 3) if sum(1 for h in heads if h.level <= lv) > 1), 1)
        for b in self.an.blocks:
            if b.role in REMOVED_ROLES:
                self.rep.removed.append((b.role, b.text))
                continue
            if b.role == 'heading' and b.level <= split_level or cur is None:
                cur = Chapter(b.text if b.role == 'heading' else '')
                chapters.append(cur)
            cur.blocks.append(b)
        used = set()
        n = 0
        for ch in chapters:
            for rx, t, role in TYPE_BY_TITLE:
                if rx.match(ch.title):
                    ch.epub_type, ch.role = t, role
                    break
            if ch.epub_type == 'chapter':
                n += 1
                name = f'chapter{n:02d}'
            else:
                name = ch.epub_type.replace('-page', '')
            cand, k = name, 1
            while cand in used:
                k += 1
                cand = f'{name}-{k}'
            used.add(cand)
            ch.path = posixpath.join(self.out_dir, f'{cand}.xhtml') if self.out_dir else f'{cand}.xhtml'
            for b in ch.blocks:
                for a in b.anchors:
                    self.id_map[(b.doc, a)] = ch.path
                self.doc_map.setdefault(b.doc, ch.path)
        self.removed_docs = {b.doc for b in self.an.blocks} - set(self.doc_map)
        # nav 会按新标题重新生成，原 nav 里的自定义段落（如「表格目录」）不再存在，指向它的链接只留文字
        self.removed_docs |= {i.path for i in self.book.manifest() if 'nav' in i.properties}
        return chapters

    # ---------- 2. 注释编号 ----------

    def number_notes(self, chapters: list[Chapter]) -> None:
        notes_by_ref = {}
        for note_idx, refs in self.an.noterefs.items():
            for a in refs:
                notes_by_ref[id(a)] = note_idx
        n = 0
        for ch in chapters:
            for b in ch.blocks:
                for a in b.el.iter(X + 'a'):
                    note_idx = notes_by_ref.get(id(a))
                    if note_idx is None:
                        continue
                    if note_idx not in self.note_of_block:
                        n += 1
                        self.note_of_block[note_idx] = n
                    num = self.note_of_block[note_idx]
                    self.noteref_els[id(a)] = (num, ch.path)
                    note_block = self.an.blocks[note_idx]
                    if note_idx not in self.note_home:          # 注文放在首次引用它的那一章末尾
                        self.note_home[note_idx] = ch.path
                        self.notes_for.setdefault(ch.path, []).append((num, note_block))
                        for anc in note_block.anchors:
                            self.id_map[(note_block.doc, anc)] = ch.path
                            self.frag_map[(note_block.doc, anc)] = f'note-{num}'
        self.rep.notes = n

    # ---------- 3. 链接改写 ----------

    def _href(self, href: str) -> str | None:
        """把旧文档里的 href 改写为新文档里的；目标整份被删（如广告页）时返回 None。"""
        if not href or is_external(href):
            return href
        path, _, frag = href.partition('#')
        target = Book.resolve(self.cur_doc, href) if path else self.cur_doc
        if target in self.removed_docs:
            return None
        if target in self.doc_map:
            new = self.id_map.get((target, frag))
            if new is None:                            # 锚点所在块被删（如目录页条目）：退回文件开头
                new, frag = self.doc_map[target], ''
            frag = self.frag_map.get((target, frag), frag)
        else:
            new = target
        rel = '' if new == self.cur_new else Book.relative(self.cur_new, new)
        return (rel + (f'#{frag}' if frag else '')) or Book.relative(self.cur_new, new)

    # ---------- 4. 行内内容 ----------

    def _inline_style(self, el) -> tuple[list[str], bool, bool]:
        """行内元素的原样式里有语义的部分 → (主题类, 加粗, 斜体)。如脂批的小号楷体红字、正文里的强调色。"""
        st = _style_of(el, self.classes)
        cls = []
        size = _size_level(st.get('font-size', ''))
        if size is not None and size < 3:
            cls.append('small')
        ff = st.get('font-family', '')
        if re.search(r'kai|楷', ff):
            cls.append('kaiti')
        elif re.search(r'fang\s*song|仿宋', ff):
            cls.append('fangsong')
        elif re.search(r'hei|黑|sans', ff):
            cls.append('heiti')
        color = st.get('color', '').replace(' ', '')
        if color and color not in ('#000', '#000000', 'black', 'inherit', 'initial', 'currentcolor', 'rgb(0,0,0)'):
            cls.append('accent')
        bold = st.get('font-weight', '') in ('bold', 'bolder', '600', '700', '800', '900')
        italic = st.get('font-style', '') == 'italic'
        return cls, bold, italic

    def _is_glyph(self, img) -> bool:
        """嵌在文字里的小图（图片字、生僻字、版本标记）：原样式限定 ≤2em，或原图高 ≤64px。"""
        h = _style_of(img, self.classes).get('height', '')
        m = re.match(r'([\d.]+)\s*em', h)
        if m:
            return float(m.group(1)) <= 2
        src = img.get('src')
        if not src:
            return False
        path = Book.resolve(self.cur_doc, src)
        if path not in self.img_height:
            self.img_height[path] = None
            if path in self.book.files:
                try:
                    from PIL import Image
                    import io
                    self.img_height[path] = Image.open(io.BytesIO(self.book.files[path])).size[1]
                except Exception:
                    pass
        hh = self.img_height[path]
        return hh is not None and hh <= 64

    def inline(self, src: etree._Element, dst: etree._Element, strip_prefix: re.Pattern | None = None,
               plain: bool = False, sized: bool = False) -> None:
        """把 src 的行内内容（不含 src 自身标签）规范化后追加进 dst。
        plain=True：去掉一切行内样式（标题）；sized=True：字号由块的角色样式决定，不再输出 small（图注、出处、注文）。"""
        state = {'strip': strip_prefix}

        def add_text(parent, text):
            text = _clean_ws(text)
            if state['strip'] is not None and text.strip():
                text = state['strip'].sub('', text.lstrip(), count=1)
                state['strip'] = None
            if not text:
                return
            if len(parent):
                parent[-1].tail = (parent[-1].tail or '') + text
            else:
                parent.text = (parent.text or '') + text

        def walk(s, d):
            if s.text:
                add_text(d, s.text)
            for ch in s:
                if isinstance(ch.tag, str):
                    convert(ch, d)
                if ch.tail:
                    add_text(d, ch.tail)

        def convert(ch, d):
            tag = _local(ch.tag)
            if id(ch) in self.noteref_els:
                num, _ = self.noteref_els[id(ch)]
                if ch.get('id'):                       # 原注号上的 id 可能是注文回链的目标，保留
                    d.append(_el('span', {'id': ch.get('id')}))
                a = _el('a', {'class': 'noteref', EPUB + 'type': 'noteref', 'role': 'doc-noteref',
                              'href': f'#note-{num}', 'id': f'noteref-{num}'})
                sup = etree.SubElement(a, X + 'sup')
                sup.text = str(num)
                d.append(a)
                return
            if ch.tag == X + 'sup' and self._wraps_noteref(ch):
                walk(ch, d)                    # 原来的 <sup><small><a>[1]</a></small></sup>：外壳去掉
                return
            if ch.get('id') and not (tag in KEEP_INLINE and tag != 'span'):
                d.append(_el('span', {'id': ch.get('id')}))
            if tag in ('img', 'svg'):
                glyph = tag == 'img' and self._is_glyph(ch)
                e = copy.deepcopy(ch)
                e.tail = None                  # deepcopy 会带上 tail；tail 由外层 walk 统一追加，否则文字重复
                for k in ('style', 'align', 'border', 'hspace', 'vspace', 'class'):
                    e.attrib.pop(k, None)
                if glyph:
                    e.set('class', 'glyph')    # 主题里限定为一个字大小
                    e.attrib.pop('width', None)
                    e.attrib.pop('height', None)
                if e.get('src'):
                    e.set('src', self._href(e.get('src')))
                d.append(e)
                return
            if tag == 'span' or tag not in KEEP_INLINE:
                keep = {k: v for k, v in ch.attrib.items() if k in ('lang', XML_LANG, EPUB + 'type')}
                cls, bold, italic = ([], False, False) if plain else self._inline_style(ch)
                if sized:
                    cls = [c for c in cls if c != 'small']
                if cls:
                    keep['class'] = ' '.join(cls)
                inner = d
                if keep:
                    inner = _el('span', keep)
                    d.append(inner)
                for flag, t in ((bold, 'b'), (italic, 'i')):
                    if flag:
                        w = _el(t)
                        inner.append(w)
                        inner = w
                walk(ch, inner)                # 无语义的表现型 span / 未知元素：去壳
                return
            if plain and tag in ('b', 'strong', 'i', 'em', 'small', 'u'):
                walk(ch, d)                    # 标题内的字体修饰由标题样式统一
                return
            attrs = {}
            for k in ('href', 'title', 'lang', XML_LANG, 'datetime', 'id'):
                if ch.get(k) is not None:
                    attrs[k] = self._href(ch.get(k)) if k == 'href' else ch.get(k)
            if tag == 'a' and 'href' in attrs and attrs['href'] is None:
                if attrs.get('id'):
                    d.append(_el('span', {'id': attrs['id']}))
                walk(ch, d)                            # 链接目标已删除：只留文字
                return
            e = _el(tag, attrs)
            d.append(e)
            walk(ch, e)

        walk(src, dst)
        # 块首尾空白
        if dst.text:
            dst.text = dst.text.lstrip()
        last = dst[-1] if len(dst) else None
        if last is not None and last.tail:
            last.tail = last.tail.rstrip()
        elif last is None and dst.text:
            dst.text = dst.text.rstrip()

    def _wraps_noteref(self, el) -> bool:
        return any(id(a) in self.noteref_els for a in el.iter(X + 'a'))

    # ---------- 5. 块 ----------

    def _anchors(self, b: Block, el: etree._Element) -> None:
        """把指向原块的 id 都保留下来：第一个放在元素上，其余用空 span。"""
        own = {d.get('id') for d in el.iter() if isinstance(d.tag, str) and d.get('id')}
        rest = [a for a in b.anchors if a not in own]
        if rest and not el.get('id'):
            el.set('id', rest.pop(0))
        elif rest and el.tag in (X + 'h1', X + 'h2', X + 'h3', X + 'h4', X + 'h5', X + 'h6'):
            el.set('id', rest.pop(0))                   # 标题用原锚点做 id（外部链接直达）
        for a in reversed(rest):
            el.insert(0, _el('span', {'id': a}))
            if el.text:
                el[0].tail, el.text = el.text, None

    def render_chapter(self, ch: Chapter) -> etree._Element:
        self.cur_new = ch.path
        html = etree.Element(X + 'html', nsmap={None: NS['xhtml'], 'epub': NS['epub']})
        html.set('lang', self.lang)
        html.set(XML_LANG, self.lang)
        head = etree.SubElement(html, X + 'head')
        etree.SubElement(head, X + 'meta', {'charset': 'utf-8'})
        etree.SubElement(head, X + 'title').text = ch.title or self._book_title()
        etree.SubElement(head, X + 'link', {'rel': 'stylesheet', 'type': 'text/css',
                                            'href': Book.relative(ch.path, self.css_path)})
        body = etree.SubElement(html, X + 'body')
        sec = etree.SubElement(body, X + 'section', {EPUB + 'type': ch.epub_type})
        if ch.role:
            sec.set('role', ch.role)
        blocks = ch.blocks
        i = 0
        while i < len(blocks):
            b = blocks[i]
            self.cur_doc = b.doc
            if b.role == 'note':
                if b.idx in self.note_of_block:       # 注文在首次引用的那一章末尾输出
                    i += 1
                    continue
                b.role = 'para'                       # 没被引用的注（孤注）：按普通段落保留
            if b.role == 'figure' and _local(b.el.tag) != 'figure':   # 原有 <figure> 走下面的整体保留
                fig = _el('figure')
                self._anchors(b, fig)
                for img in b.el.iter():
                    if isinstance(img.tag, str) and _local(img.tag) in ('img', 'svg'):
                        e = copy.deepcopy(img)
                        e.tail = None
                        for k in ('style', 'width', 'height', 'align', 'border', 'hspace', 'vspace'):
                            if _local(img.tag) == 'img':
                                e.attrib.pop(k, None)
                        if e.get('src'):
                            e.set('src', self._href(e.get('src')))
                        fig.append(e)
                j = i + 1
                if j < len(blocks) and blocks[j].role == 'caption' and blocks[j].group == b.idx:
                    cap = _el('figcaption')
                    self.cur_doc = blocks[j].doc
                    self.inline(blocks[j].el, cap, sized=True)
                    self._anchors(blocks[j], cap)
                    fig.append(cap)
                    cap_text = ' '.join(''.join(cap.itertext()).split())
                    for img in fig.iter(X + 'img'):
                        if not img.get('alt'):
                            img.set('alt', cap_text)
                    j += 1
                for img in fig.iter(X + 'img'):
                    if img.get('alt') is None:
                        img.set('alt', '')
                sec.append(fig)
                i = j
                continue
            if b.role in ('bullet', 'quote'):
                wrap = _el('ul', {'class': 'bullets'}) if b.role == 'bullet' else _el('blockquote')
                while i < len(blocks) and blocks[i].role == b.role:
                    self.cur_doc = blocks[i].doc
                    item = _el('li' if b.role == 'bullet' else 'p')
                    self.inline(blocks[i].el, item, BULLET_RE if b.role == 'bullet' else None)
                    self._anchors(blocks[i], item)
                    wrap.append(item)
                    i += 1
                sec.append(wrap)
                continue
            if b.role == 'keep' or b.role == 'figure' and _local(b.el.tag) == 'figure':
                e = copy.deepcopy(b.el)
                e.tail = None
                for d in e.iter():
                    if isinstance(d.tag, str):
                        for k in ('href', 'src'):
                            if d.get(k):
                                new = self._href(d.get(k))
                                if new is None:
                                    del d.attrib[k]
                                else:
                                    d.set(k, new)
                self._anchors(b, e)
                sec.append(e)
                i += 1
                continue
            if b.role == 'heading':
                e = _el(f'h{min(b.level, 6)}')
                self.heading_no += 1
                e.set('id', f'h{self.heading_no}')     # 稳定 id，供 nav 定位；原有锚点由 _anchors 另加
            elif b.role in ('caption',):              # 没跟在图后面的图注：居中小字
                e = _el('p', {'class': 'align-center small'})
            else:
                cls = {'source': 'source', 'meta': 'meta', 'right': 'align-right', 'center': 'align-center'}
                e = _el('p', {'class': cls.get(b.role)})
            self.inline(b.el, e, plain=b.role == 'heading', sized=b.role in ('caption', 'source'))
            self._anchors(b, e)
            sec.append(e)
            i += 1
        notes_here = self.notes_for.get(ch.path, [])
        if notes_here:
            fn = etree.SubElement(sec, X + 'section', {'class': 'footnotes', EPUB + 'type': 'footnotes'})
            for num, b in sorted(notes_here):
                self.cur_doc = b.doc
                aside = etree.SubElement(fn, X + 'aside', {'id': f'note-{num}', EPUB + 'type': 'footnote',
                                                         'role': 'doc-footnote'})
                p = etree.SubElement(aside, X + 'p')
                back = etree.SubElement(p, X + 'a', {'class': 'backlink', 'role': 'doc-backlink',
                                                     'href': f'#noteref-{num}'})
                back.text = str(num)
                body_src = copy.deepcopy(b.el)
                for a in list(body_src.iter(X + 'a')):         # 去掉原来的「[n]」回链
                    if NOTE_LABEL_RE.fullmatch(re.sub(r'\s+', '', ''.join(a.itertext())) or 'x'):
                        tail = a.tail
                        parent = a.getparent()
                        prev = a.getprevious()
                        parent.remove(a)
                        if tail:
                            if prev is not None:
                                prev.tail = (prev.tail or '') + tail
                            else:
                                parent.text = (parent.text or '') + tail
                        break
                holder = _el('span')
                self.inline(body_src, holder, NOTE_LABEL_RE, sized=True)
                back.tail = '\u3000' + (holder.text or '')
                for c in holder:
                    p.append(c)
        return html

    def _book_title(self) -> str:
        t = self.book.opf.find('opf:metadata/dc:title', NS)
        return (t.text or '').strip() if t is not None else ''

    # ---------- 6. 写回 ----------

    def run(self) -> RebuildReport:
        book = self.book
        chapters = self.split()
        self.number_notes(chapters)
        old_docs = {b.doc for b in self.an.blocks}
        trees = [(ch, self.render_chapter(ch)) for ch in chapters]

        # 删除旧正文文件、旧样式表
        old_css = [i for i in book.manifest() if i.media_type == 'text/css']
        for it in book.manifest():
            if it.path in old_docs or it in old_css:
                it.element.getparent().remove(it.element)
                book.delete(it.path)
        spine = book.opf.find('opf:spine', NS)
        for ref in list(spine):
            spine.remove(ref)
        guide = book.opf.find('opf:guide', NS)         # 指向旧文件；EPUB 3 由 nav 的 landmarks 取代
        if guide is not None:
            guide.getparent().remove(guide)

        # 主题样式表
        css = theme_css(self.theme)
        if self.an.vertical:                          # 整本竖排：追加竖排模板（guide/04 T19）
            css += b'\n' + theme_css('vertical')
            self.rep.log.append('保留整本竖排（追加 vertical 样式）')
        book.add_item(self.css_path, 'text/css', item_id='typesetter-css', data=css)

        # 封面页
        cover_item = next((i for i in book.manifest() if 'cover-image' in i.properties), None)
        spine_ids = []
        if cover_item is not None:
            cover_path = posixpath.join(self.out_dir, 'cover.xhtml') if self.out_dir else 'cover.xhtml'
            src = Book.relative(cover_path, cover_item.path)
            doc = (f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
                   f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
                   f'lang="{self.lang}" xml:lang="{self.lang}"><head><meta charset="utf-8"/><title>封面</title>'
                   f'<style>html,body{{margin:0;padding:0;height:100%;text-align:center}}'
                   f'img{{max-width:100%;max-height:100vh}}</style></head>'
                   f'<body><section epub:type="cover"><img role="doc-cover" src="{escape(src)}" alt="封面"/>'
                   f'</section></body></html>\n')
            it = book.add_item(cover_path, 'application/xhtml+xml', item_id='cover-page', data=doc.encode())
            spine_ids.append(it.id)

        for ch, html in trees:
            data = b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n' + \
                etree.tostring(html, encoding='utf-8') + b'\n'
            it = book.add_item(ch.path, 'application/xhtml+xml', item_id=posixpath.basename(ch.path)[:-6], data=data)
            props = content_properties(book, ch.path)
            if props:
                it.element.set('properties', ' '.join(sorted(props)))
            spine_ids.append(it.id)
            self.rep.chapters.append(ch.path)
        for sid in spine_ids:
            etree.SubElement(spine, '{%s}itemref' % NS['opf'], {'idref': sid})

        self._rebuild_nav(trees, cover_item is not None)
        book.mark_dirty(book.opf_path)
        self.rep.log.append(f'重建 {len(chapters)} 个文件，注释 {self.rep.notes} 条，删除 {len(self.rep.removed)} 块')
        return self.rep

    def _rebuild_nav(self, trees, has_cover: bool) -> None:
        book = self.book
        entries = []
        for ch, html in trees:
            for k, h in enumerate(html.iter(X + 'h1', X + 'h2')):
                entries.append(Entry(int(h.tag[-1]), ' '.join(''.join(h.itertext()).split()), ch.path,
                                     '' if k == 0 else h.get('id')))
        chapters = [ch for ch, _ in trees]
        if not entries and chapters:                  # 全书没有标题：至少给一条指向正文开头
            entries.append(Entry(1, self._book_title() or '正文', chapters[0].path, ''))
        landmarks = []
        if has_cover:
            landmarks.append(('cover', '封面', posixpath.join(self.out_dir, 'cover.xhtml') if self.out_dir
                              else 'cover.xhtml'))
        body_ch = next((c for c in chapters if c.epub_type == 'chapter'), chapters[0] if chapters else None)
        if body_ch is not None:
            landmarks.append(('bodymatter', '正文', body_ch.path))
        nav_item = next((i for i in book.manifest() if 'nav' in i.properties), None)
        nav_path = nav_item.path if nav_item else posixpath.join(self.out_dir, 'nav.xhtml')
        data = build_nav(book, nav_path, entries, landmarks, self.lang)
        if nav_item:
            book.set_bytes(nav_path, data)
        else:
            book.add_item(nav_path, 'application/xhtml+xml', item_id='nav', properties='nav', data=data)
        p = ncx_path(book)
        if p:
            book.set_bytes(p, self._ncx(entries, p))

    def _ncx(self, entries: list[Entry], ncx_file: str) -> bytes:
        uid_el = None
        uid = self.book.opf.get('unique-identifier')
        for e in self.book.opf.iterfind('opf:metadata/dc:identifier', NS):
            if e.get('id') == uid:
                uid_el = e
        out = ['<?xml version="1.0" encoding="utf-8"?>',
               '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">',
               f'<head><meta name="dtb:uid" content="{escape((uid_el.text or "").strip() if uid_el is not None else "")}"/>'
               f'<meta name="dtb:depth" content="{max([e.depth for e in entries] or [1])}"/></head>',
               f'<docTitle><text>{escape(self._book_title())}</text></docTitle>', '<navMap>']
        stack = 0
        order: dict[str, int] = {}             # 同一目标必须同一 playOrder（NCX 规范）
        for k, e in enumerate(entries, 1):
            d = max(1, min(e.depth, stack + 1))
            out.append('</navPoint>' * (stack - d + 1) if stack >= d else '')
            href = Book.relative(ncx_file, e.path) + (f'#{e.fragment}' if e.fragment else '')
            po = order.setdefault(href, len(order) + 1)
            out.append(f'<navPoint id="np-{k}" playOrder="{po}"><navLabel><text>{escape(e.label)}</text></navLabel>'
                       f'<content src="{escape(href)}"/>')
            stack = d
        out.append('</navPoint>' * stack)
        out += ['</navMap>', '</ncx>']
        return '\n'.join(x for x in out if x).encode('utf-8')


def rebuild(book: Book, analysis: Analysis, theme: str = 'default') -> RebuildReport:
    return Rebuilder(book, analysis, theme).run()

