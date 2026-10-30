"""重建（M2）：按语义分析结果把正文重写成干净的 EPUB 3 结构（规范见 guide/04）。

- 部、章各成一个文件，全书链接按 id 映射同步（04 §4.2）；
- 标题层级按全书结构：h1 只给书名页；无部时章 h2，有部时部 h2、章 h3；
  样式由角色类决定（part-title / chapter-title / section-title / subsection-title，04 §4.3）；
- 角色 → 语义标签：figure+figcaption、ul、blockquote、p.source/meta/align-*；
- 注释 → 全书一个书末尾注文件（noteref + ol/li + ↩ 回链），全书连续编号（04 §4.12）；
- 去掉表现型 span/style，统一换成主题样式表（themes/default.css，来自 guide/03、04）；
- 书内目录页、注释区小标题、广告页删除（全部记录在 RebuildReport.removed，供文字校验与界面展示）；
- 重新生成封面页、nav、NCX。

- 成组结构（structures.py 识别）：诗歌、书信、有序列表、定义列表与术语表、中文序号项、条文、
  插图（表格）目录、表题表注，按 04 §4.7–4.13、4.19 的模板输出；只追加用到的模板样式。

表格做结构规范化（tables.py）后保留内容；pre 等无法安全改写的块原样保留。
"""
from __future__ import annotations

import copy
import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from importlib import resources
from xml.sax.saxutils import escape

from lxml import etree

from .book import NS, Book
from .nav import NCX, Entry, build_nav, ncx_path
from .rules.content import Z3998_URI
from .semantic import BULLET_RE, NOTE_LABEL_RE, Analysis, Block, _local, _size_level, _style_of, class_styles
from .structures import ARTICLE, CN_ITEM, OL_NUM
from .tables import rebuild_table
from .upgrade import book_language, content_properties
from .xhtml import X, is_external, squash

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
    (re.compile(r'^(术语表|名词解释|词汇表|译名对照|人名对照|名词对照)'), 'glossary', 'doc-glossary'),
]
TEMPLATE_ORDER = ('poem', 'letter', 'article', 'list', 'figure', 'loi', 'table', 'glossary')
WS_LEAD = ' \t\r\n\u3000\u00a0\u2002\u2003'
PAGE_TAIL = re.compile(r'[\s.．·…⋯—_-]*\d+\s*$')


CHAPTER_ONLY_RE = re.compile(r'^(第[一二三四五六七八九十百千零〇两\d]+[章回]|chapter\s*\d+)', re.I)
PART_RE = re.compile(r'^(第[一二三四五六七八九十百千零〇两\d]+[部卷篇编辑]|卷[一二三四五六七八九十百千零〇\d]+|'
                     r'[上中下]篇|[上中下]卷|[上中下]部|part\s*[\divx]+|book\s*[\divx]+|volume\s*[\divx]+)', re.I)


ORDINAL_SEP_RE = re.compile(r'^(第[一二三四五六七八九十百千零〇两\d]+[章回节卷部篇编]|[上中下][篇卷部])[ \t]+(?=\S)')


@dataclass
class Chapter:
    title: str
    blocks: list[Block] = field(default_factory=list)
    path: str = ''
    epub_type: str = 'chapter'
    role: str | None = 'doc-chapter'
    kind: str = 'chapter'                 # chapter / part / front（第一个标题之前的内容）/ loi / lot
    level: int = 2                        # 本文件首标题输出的 h 数字


@dataclass
class RebuildReport:
    removed: list[tuple[str, str]] = field(default_factory=list)     # (角色, 文字)
    chapters: list[str] = field(default_factory=list)
    notes: int = 0
    log: list[str] = field(default_factory=list)
    structures: Counter = field(default_factory=Counter)          # 输出的成组结构：(类别, 置信级) → 个数
    suggestions: list[dict] = field(default_factory=list)         # 只建议、没改的（C 级识别、对不上的目录条目）


def theme_css(name: str = 'default') -> bytes:
    return resources.files('epub_typesetter').joinpath(f'themes/{name}.css').read_bytes()


def template_css(name: str) -> str:
    """04 的按需模板（scripts/build_theme.py 生成）；含 {N} 占位的悬挂变体行我们不输出，去掉。"""
    css = resources.files('epub_typesetter').joinpath(f'themes/tpl-{name}.css').read_text(encoding='utf-8')
    return '\n'.join(ln for ln in css.splitlines() if '{N' not in ln)


IMG_ATTRS = {'src', 'alt', 'title', 'id', 'lang', XML_LANG, EPUB + 'type', 'role', 'width', 'height',
             'viewBox', 'preserveAspectRatio', '{http://www.w3.org/1999/xlink}href', 'href'}


def _clean_media(e: etree._Element) -> None:
    """复制过来的图片只留标准属性：厂商私有属性（zy-enlarge-src 等）会让 epubcheck 报 RSC-005。"""
    for k in list(e.attrib):
        if k not in IMG_ATTRS and not k.startswith('aria-'):
            del e.attrib[k]


def _el(tag: str, attrib: dict | None = None, text: str | None = None) -> etree._Element:
    e = etree.Element(X + tag, {k: v for k, v in (attrib or {}).items() if v is not None})
    if text:
        e.text = text
    return e


_HAN_PUNCT = r'[\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]'   # 汉字与全角标点


SOFT = '\ufdd0'     # 源码换行产生的空白（Unicode 非字符，真实文本不会出现；XML 允许），留待跨标签判断


def _clean_ws(s: str) -> str:
    """源码排版产生的换行：夹在汉字/全角标点之间的直接删；其余先标成 SOFT，
    等整块拼好后再看它跨标签的左右邻字决定删还是变一个空格。"""
    if not s:
        return s
    s = s.replace('\r', '\n')
    s = re.sub(rf'(?<={_HAN_PUNCT})[ \t]*\n\s*(?={_HAN_PUNCT})', '', s)
    return re.sub(r'[ \t]*\n[\s]*', SOFT, s)


def _resolve_soft(dst: etree._Element) -> None:
    """SOFT 两侧（跨标签看）有汉字或全角标点就删掉，两侧都是西文才变一个空格。"""
    order = []

    def walk(el):
        order.append((el, 'text'))
        for ch in el:
            if isinstance(ch.tag, str):
                walk(ch)
            order.append((ch, 'tail'))
    walk(dst)
    texts = [getattr(e, a) or '' for e, a in order]
    full = ''.join(texts)
    if SOFT not in full:
        return
    han = re.compile(_HAN_PUNCT)
    res: list[str] = []
    for i, c in enumerate(full):
        if c != SOFT:
            res.append(c)
            continue
        j = i - 1
        while j >= 0 and full[j] in (SOFT, ' '):
            j -= 1
        k = i + 1
        while k < len(full) and full[k] in (SOFT, ' '):
            k += 1
        prev_c = full[j] if j >= 0 else ''
        next_c = full[k] if k < len(full) else ''
        drop = (not prev_c or not next_c or han.match(prev_c) or han.match(next_c)
                or (res and res[-1] == ' ') or (k < len(full) and full[i + 1:k].strip(SOFT)))
        res.append('' if drop else ' ')
    pos = 0
    for (e, a), t in zip(order, texts):
        new = ''.join(res[pos:pos + len(t)])
        pos += len(t)
        if new != t:
            setattr(e, a, new or None)


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
        # 注释采用 Standard Ebooks 的做法：全书一个书末尾注文件，正文注号链接过去，注文末尾 ↩ 回链
        self.endnotes_path = posixpath.join(self.out_dir, 'endnotes.xhtml') if self.out_dir else 'endnotes.xhtml'
        self.endnotes: list[tuple[int, Block, str]] = []  # (注序号, 注块, 首次引用所在新文档)
        self.frag_map: dict[tuple[str, str], str] = {}   # (旧文档, id) → 新 id（id 被替换时）
        self.removed_docs: set[str] = set()
        self.tpl_used: set[str] = set()                   # 用到的 04 模板，样式表只追加这些
        self.block_path: dict[int, str] = {}              # 块序号 → 新文档
        self.target_ids: dict[int, str] = {}              # 被目录引用的图、表块序号 → 输出 id（figure-N / table-N）
        self.list_entries: dict[int, tuple[str, str] | None] = {}   # 目录条目块 → (链接, 文字)

    # ---------- 1. 分章 ----------

    def plan_headings(self) -> None:
        """按全书结构给每个标题定输出层级和角色类（04 §4.3）：
        「第X章/回」所在层级为章；章的上一级若是「第X部/卷/篇」等，则为部。
        结果存入 self.head_out：块序号 → (h 数字, 角色类或 None, 'part'/'chapter'/'sub')。"""
        heads = [b for b in self.an.blocks if b.role == 'heading']
        self.head_out: dict[int, tuple[int, str | None, str]] = {}
        if not heads:
            return
        chap = Counter(h.level for h in heads if CHAPTER_ONLY_RE.match(h.text))
        if chap and chap.most_common(1)[0][1] >= 2:
            chapter_level = chap.most_common(1)[0][0]
        else:   # 没有「第X章」：取最浅的、拆出不止一个文件的层级（书名级大标题时往下一级）
            chapter_level = next((lv for lv in (1, 2, 3) if sum(1 for h in heads if h.level <= lv) > 1), 1)
            # 这一级全是前言、后记、版权页之类的辅文，或数量不到下一级的三分之一：章在下一级
            # （如「一　费尧多尔……」只用中文数字编号的章，上一级只有译序、人物表、尾声）
            here = [h for h in heads if h.level == chapter_level]
            below = [h for h in heads if h.level == chapter_level + 1]
            front_back = re.compile(r'^(版权|献给|献词|人物表|重要人物|主要人物|作者的话|译本序|译序|译者|出版说明|尾声)')
            if below and len(below) >= 3 * len(here) and all(
                    any(rx.match(h.text) for rx, _, _ in TYPE_BY_TITLE) or front_back.match(h.text) for h in here):
                chapter_level += 1
        part_level = chapter_level - 1 if chapter_level > 1 and any(
            h.level == chapter_level - 1 and PART_RE.match(h.text) for h in heads) else None
        in_part = False
        cur_n = 2
        for h in heads:
            if part_level is not None and h.level == part_level and PART_RE.match(h.text):
                self.head_out[h.idx] = (2, 'part-title', 'part')
                in_part, cur_n = True, 2
            elif h.level <= chapter_level:
                special = any(rx.match(h.text) for rx, t, _ in TYPE_BY_TITLE)   # 前言、后记等不属于部
                if special:
                    in_part = False
                cur_n = 3 if in_part else 2
                self.head_out[h.idx] = (cur_n, 'chapter-title', 'chapter')
            else:
                depth = h.level - chapter_level
                cls = {1: 'section-title', 2: 'subsection-title'}.get(depth)
                self.head_out[h.idx] = (min(cur_n + depth, 6), cls, 'sub')

    def split(self) -> list[Chapter]:
        chapters: list[Chapter] = []
        cur = None
        self.plan_headings()
        for b in self.an.blocks:
            if b.role in REMOVED_ROLES:
                self.rep.removed.append((b.role, b.text))
                continue
            out = self.head_out.get(b.idx) if b.role == 'heading' else None
            if b.role == 'loi-head':                  # 插图（表格）目录自成一个文件（04 4.11.4.4）
                kind = self.an.units[b.unit]['kind']
                cur = Chapter(b.text, kind=kind, epub_type=kind, role=None)
                chapters.append(cur)
            elif cur is not None and cur.kind in ('loi', 'lot') and b.role != 'loi-entry' and \
                    not (out is not None and out[2] in ('part', 'chapter')):
                cur = Chapter('', kind='front')        # 目录页之后、下一个标题之前的内容
                chapters.append(cur)
            elif out is not None and out[2] in ('part', 'chapter') or cur is None:
                if out is not None and out[2] in ('part', 'chapter'):
                    cur = Chapter(b.text, kind=out[2], level=out[0])
                else:
                    cur = Chapter('', kind='front')
                chapters.append(cur)
            cur.blocks.append(b)
        used = set()
        n = 0
        for ch in chapters:
            for rx, t, role in TYPE_BY_TITLE:
                if rx.match(ch.title):
                    ch.epub_type, ch.role = t, role
                    break
            if ch.kind in ('loi', 'lot'):
                name = ch.kind
            elif ch.kind == 'part':
                ch.epub_type, ch.role = 'part', 'doc-part'
                n_part = sum(1 for c in chapters[:chapters.index(ch) + 1] if c.kind == 'part')
                name = f'part{n_part:02d}'
            elif ch.epub_type == 'chapter':
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
                self.block_path[b.idx] = ch.path
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
                    k = sum(1 for v in self.noteref_els.values() if v[0] == num) + 1   # 这是第 k 次引用
                    self.noteref_els[id(a)] = (num, ch.path, f'noteref-{num}' if k == 1 else f'noteref-{num}-{k}')
                    note_block = self.an.blocks[note_idx]
                    if len(self.endnotes) < num:                 # 首次引用：登记到书末尾注
                        self.endnotes.append((num, note_block, ch.path))
                        conts = [x for x in self.an.blocks if x.role == 'note-cont' and x.group == note_idx]
                        for nb in [note_block] + conts:
                            for anc in nb.anchors:
                                self.id_map[(nb.doc, anc)] = self.endnotes_path
                                self.frag_map[(nb.doc, anc)] = f'note-{num}'
        self.rep.notes = n

    # ---------- 2b. 插图、表格目录：条目对到图表，给被引用的图表定 id（04 4.11.1.7、4.11.4、4.13.1.9） ----------

    def _caption_of(self, idx: int) -> str:
        """图（表）的图注（表题）第一行文字。"""
        blocks = self.an.blocks
        b = blocks[idx]
        if _local(b.el.tag) == 'figure':
            cap = b.el.find(X + 'figcaption')
            return squash(''.join(cap.itertext())) if cap is not None else ''
        for c in blocks[max(0, idx - 1): idx + 2]:
            if c.role in ('caption', 'table-caption') and c.group == idx:
                return c.text
        cap = b.el.find('.//' + X + 'caption')
        return squash(''.join(cap.itertext())) if cap is not None else ''

    def plan_lists_of(self) -> None:
        blocks = self.an.blocks
        units = {u: info for u, info in self.an.units.items() if info['kind'] in ('loi', 'lot')}
        if not units:
            return
        figures = [b.idx for b in blocks if b.role == 'figure']
        tables = [b.idx for b in blocks if b.role == 'keep'
                  and (_local(b.el.tag) == 'table' or b.el.find('.//' + X + 'table') is not None)]
        by_anchor = {(b.doc, a): b for b in blocks for a in b.anchors}
        for u, info in units.items():
            pool = figures if info['kind'] == 'loi' else tables
            captions = {i: re.sub(r'\s', '', self._caption_of(i)) for i in pool}
            for e in (b for b in blocks if b.unit == u and b.role == 'loi-entry'):
                text = PAGE_TAIL.sub('', e.text).strip()
                hit = None
                a = e.el.find('.//' + X + 'a')
                if a is not None and a.get('href') and not is_external(a.get('href')):
                    href = a.get('href')
                    t = by_anchor.get((Book.resolve(e.doc, href), href.partition('#')[2]))
                    if t is not None:
                        near = [x for x in blocks[max(0, t.idx - 1): t.idx + 3] if x.doc == t.doc]
                        if t.idx in pool:
                            hit = t.idx
                        elif t.role in ('caption', 'table-caption') and t.group in pool:
                            hit = t.group
                        else:
                            hit = next((x.idx for x in near if x.idx in pool), None)
                if hit is None and text:                 # 没有链接：按图号、题名对图注
                    key = re.sub(r'\s', '', text)
                    hit = next((i for i, c in captions.items() if c and (c.startswith(key) or key.startswith(c))), None)
                if hit is None:
                    self.list_entries[e.idx] = None
                    self.rep.suggestions.append({'kind': info['kind'], 'doc': e.doc,
                                                 'text': f'{info["title"]}的条目「{text[:30]}」对不上任何图表，保留文字、不加链接'})
                    continue
                n = pool.index(hit) + 1
                fid = self.target_ids.setdefault(hit, f'{"figure" if info["kind"] == "loi" else "table"}-{n}')
                cap = self._caption_of(hit)
                label = cap.split('\n')[0] if cap and len(cap) <= 40 else text
                self.list_entries[e.idx] = (f'{self.block_path.get(hit, "")}#{fid}', label or text)

    # ---------- 3. 链接改写 ----------

    def _href(self, href: str) -> str | None:
        """把旧文档里的 href 改写为新文档里的；目标整份被删（如广告页）时返回 None。"""
        href = (href or '').strip()
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
                num, _, ref_id = self.noteref_els[id(ch)]
                if ch.get('id'):                       # 原注号上的 id 可能是注文回链的目标，保留
                    d.append(_el('span', {'id': ch.get('id')}))
                # 不包 <sup>：上标效果由 CSS（a.noteref）实现，避免与 sup/small 叠加缩小（同 Standard Ebooks）
                a = _el('a', {'class': 'noteref', EPUB + 'type': 'noteref', 'role': 'doc-noteref',
                              'href': f'{Book.relative(self.cur_new, self.endnotes_path)}#note-{num}',
                              'id': ref_id}, str(num))
                d.append(a)
                return
            if self._only_noteref(ch):
                # <sup><small><a>[1]</a></small></sup> 这类外壳里只有注号：整个外壳去掉，只留注号（和其中的锚点 id），
                # 否则注号会被 small 和 sup 双重缩小
                for x in ch.iterdescendants():
                    if not isinstance(x.tag, str):
                        continue
                    if id(x) in self.noteref_els:
                        convert(x, d)
                    elif x.get('id') and not any(id(p) in self.noteref_els for p in x.iterancestors()):
                        d.append(_el('span', {'id': x.get('id')}))
                return
            if ch.get('id') and not (tag in KEEP_INLINE and tag != 'span'):
                d.append(_el('span', {'id': ch.get('id')}))
            if tag in ('img', 'svg'):
                glyph = tag == 'img' and self._is_glyph(ch)
                e = copy.deepcopy(ch)
                e.tail = None                  # deepcopy 会带上 tail；tail 由外层 walk 统一追加，否则文字重复
                _clean_media(e)
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
        _resolve_soft(dst)
        # 块首尾空白
        ws = ' \t\r\n\f\v'                  # 只剪源码空白；全角空格是内容（如章号与章名之间）
        if dst.text:
            dst.text = dst.text.lstrip(ws)
        last = dst[-1] if len(dst) else None
        if last is not None and last.tail:
            last.tail = last.tail.rstrip(ws)
        elif last is None and dst.text:
            dst.text = dst.text.rstrip(ws)

    def _only_noteref(self, el) -> bool:
        """el 不是注号本身，但里面有注号，且除注号文字外没有别的文字。"""
        if id(el) in self.noteref_els:
            return False
        refs = [a for a in el.iter(X + 'a') if id(a) in self.noteref_els]
        if not refs:
            return False
        rest = ''.join(el.itertext())
        for a in refs:
            rest = rest.replace(''.join(a.itertext()), '', 1)
        return not rest.strip()

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
        if ch.kind in ('loi', 'lot'):                 # 目录页的根就是 nav（04 4.11.4.3），不再套 section
            sec = body
            pos = self.chapters.index(ch)              # 位置随原书：在全书前半为前置部分，否则为后置部分
            body.set(EPUB + 'type', 'frontmatter' if pos < len(self.chapters) / 2 else 'backmatter')
        else:
            sec = etree.SubElement(body, X + 'section', {'id': posixpath.basename(ch.path)[:-6],
                                                         EPUB + 'type': ch.epub_type})
            if ch.role:
                sec.set('role', ch.role)
        blocks = ch.blocks
        i = 0
        while i < len(blocks):
            b = blocks[i]
            self.cur_doc = b.doc
            if b.role == 'heading-merged':            # 已并入相邻标题
                i += 1
                continue
            if b.role == 'note-cont':
                if b.group in self.note_of_block:     # 随注文搬到书末尾注
                    i += 1
                    continue
                b.role = 'para'
            if b.role == 'note':
                if b.idx in self.note_of_block:       # 注文搬到书末尾注
                    i += 1
                    continue
                b.role = 'para'                       # 没被引用的注（孤注）：按普通段落保留
            if b.role in ('poem', 'letter', 'ol', 'dl') and b.unit >= 0:
                j = i
                while j < len(blocks) and blocks[j].unit == b.unit and blocks[j].role == b.role:
                    j += 1
                sec.append(getattr(self, f'_render_{b.role}')(blocks[i:j]))
                i = j
                continue
            if b.role == 'loi-head':
                sec.append(self._render_list_of(blocks[i:], ch))
                i += 1
                while i < len(blocks) and blocks[i].role == 'loi-entry':
                    i += 1
                continue
            if b.role == 'table-caption' and i + 1 < len(blocks) and blocks[i + 1].idx == b.group:
                i += 1                                # 由后面的表格收进 caption
                continue
            if b.role == 'figure' and _local(b.el.tag) != 'figure':   # 原有 <figure> 走下面的整体保留
                fig = _el('figure', {'id': self.target_ids.get(b.idx)})
                self._anchors(b, fig)
                for img in b.el.iter():
                    if isinstance(img.tag, str) and _local(img.tag) in ('img', 'svg'):
                        e = copy.deepcopy(img)
                        e.tail = None
                        _clean_media(e)
                        if _local(img.tag) == 'img':
                            e.attrib.pop('width', None)
                            e.attrib.pop('height', None)
                        if e.get('src'):
                            e.set('src', self._href(e.get('src')))
                        fig.append(e)
                j = i + 1
                caps = []
                while j < len(blocks) and blocks[j].role == 'caption' and blocks[j].group == b.idx:
                    caps.append(blocks[j])
                    j += 1
                if caps:
                    cap = _el('figcaption')
                    for c in caps:                    # 多段图注：每段一个 p（04 4.11.3.5）
                        part = cap if len(caps) == 1 else etree.SubElement(cap, X + 'p')
                        self.cur_doc = c.doc
                        self.inline(c.el, part, sized=True)
                        self._anchors(c, part)
                    fig.append(cap)
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
                if b.idx in self.target_ids and not e.get('id'):
                    e.set('id', self.target_ids[b.idx])
                for d in e.iter():
                    if isinstance(d.tag, str):
                        if _local(d.tag) in ('img', 'image'):
                            _clean_media(d)
                        for k in ('href', 'src'):
                            if d.get(k):
                                new = self._href(d.get(k))
                                if new is None:
                                    del d.attrib[k]
                                else:
                                    d.set(k, new)
                if b.role == 'keep':                  # 链接改写之后再收表题（表题的链接已由 inline 改写过）
                    self._render_tables(b, e, blocks[i - 1] if i else None)
                self._anchors(b, e)
                sec.append(e)
                i += 1
                if i < len(blocks) and blocks[i].role == 'table-note' and blocks[i].group == b.idx:
                    note = _el('p', {'class': 'table-note'})
                    self.cur_doc = blocks[i].doc
                    self.inline(blocks[i].el, note, sized=True)
                    self._anchors(blocks[i], note)
                    sec.append(note)
                    i += 1
                continue
            if b.role == 'heading':
                n_out, cls, _ = self.head_out.get(b.idx, (min(b.level + 1, 6), None, 'sub'))
                e = _el(f'h{n_out}', {'class': cls})
                self.heading_no += 1
                e.set('id', f'h{self.heading_no}')     # 稳定 id，供 nav 定位；原有锚点由 _anchors 另加
            elif b.role in ('caption',):              # 没跟在图后面的图注：居中小字
                e = _el('p', {'class': 'align-center small'})
            elif b.role == 'item':                    # 中文序号项（04 4.10.2）
                e = _el('p', {'class': f'item hang-{b.attrs.get("hang", 2)}'})
                self.tpl_used.add('article')
            elif b.role == 'article':                 # 条文：条号包 span，后接一个全角空格（04 4.10.1）
                e = _el('p', {'class': 'article'})
                self.tpl_used.add('article')
                self.inline(b.el, e)
                m = ARTICLE.match(e.text or '')
                if m:
                    rest = e.text[m.end():]
                    e.text = None
                    no = _el('span', {'class': 'article-no'}, m.group(1))
                    no.tail = '\u3000' + rest
                    e.insert(0, no)
                self._anchors(b, e)
                sec.append(e)
                i += 1
                continue
            else:
                cls = {'source': 'source', 'meta': 'meta', 'right': 'align-right', 'center': 'align-center'}
                e = _el('p', {'class': cls.get(b.role)})
            if b.role == 'heading' and b.merged >= 0:     # 章号与章名两个标题合并：「第一回　章名」
                other = self.an.blocks[b.merged]
                first, second = (b, other) if b.ordinal_first else (other, b)
                self.cur_doc = first.doc
                self.inline(first.el, e, plain=True)
                if len(e):
                    e[-1].tail = (e[-1].tail or '') + '\u3000'
                else:
                    e.text = (e.text or '') + '\u3000'
                self.cur_doc = second.doc
                self.inline(second.el, e, plain=True)
            else:
                self.inline(b.el, e, plain=b.role == 'heading', sized=b.role in ('caption', 'source'))
                if b.role == 'heading' and e.text:            # 章号与章名之间统一为一个全角空格（04 §4.3）
                    e.text = ORDINAL_SEP_RE.sub('\\1\u3000', e.text, count=1)
            self._anchors(b, e)
            sec.append(e)
            i += 1
        if ch.epub_type == 'glossary':
            for dl in sec.iter(X + 'dl'):
                self._glossary_dl(dl)
        self._declare_prefix(html)
        return html

    # ---------- 5b. 成组结构 ----------

    @staticmethod
    def _declare_prefix(html) -> None:
        """用了 z3998: 就在 <html> 上声明前缀（04 4.1.4.3、4.7.1.5）。"""
        if any('z3998:' in (e.get(EPUB + 'type') or '') for e in html.iter() if isinstance(e.tag, str)):
            html.set(EPUB + 'prefix', f'z3998: {Z3998_URI}')

    def _line_spans(self, b: Block) -> list:
        """把一块的行内内容按 <br/> 切成诗行：返回 span 列表，None 表示节界（空行）。"""
        tmp = _el('p')
        self.cur_doc = b.doc
        self.inline(b.el, tmp)
        out, cur = [], _el('span', {'class': 'line'})
        cur.text = tmp.text

        def close():
            nonlocal cur
            empty = not ''.join(cur.itertext()).strip(WS_LEAD) and not len(cur)
            out.append(None if empty else cur)
            cur = _el('span', {'class': 'line'})
        for ch in list(tmp):
            if ch.tag == X + 'br':
                tail = ch.tail
                close()
                cur.text = tail
            else:
                cur.append(ch)
        close()
        for sp in out:                                # 行首的缩进空格交给 indent-N
            if sp is not None and sp.text:
                sp.text = sp.text.lstrip(WS_LEAD) or None
        while out and out[-1] is None:
            out.pop()
        while out and out[0] is None:
            out.pop(0)
        return out

    def _render_poem(self, group: list[Block]) -> etree._Element:
        """诗歌（04 §4.7）：一节一个 p.stanza，一行一个 span.line，行间 <br/>，缩进用 indent-N。"""
        info = self.an.units[group[0].unit]
        self.tpl_used.add('poem')
        self.rep.structures[('诗歌', info['level'])] += 1
        tag = 'div' if info['container'] == 'div' else 'blockquote'
        box = _el(tag, {'class': ('poem ' if tag == 'div' else 'poem-quote ') + info['layout'],
                        EPUB + 'type': info['type']})
        stanza = None

        def add_line(span, indent: int):
            nonlocal stanza
            if stanza is None:
                stanza = _el('p', {'class': 'stanza'})
                box.append(stanza)
            elif len(stanza):
                stanza[-1].tail = None
                stanza.append(_el('br'))
            if indent and info['layout'] != 'poem-center':
                span.set('class', f'line indent-{indent}')
            stanza.append(span)

        for b in group:
            if b.part in ('title', 'author', 'attribution'):
                e = _el('p', {'class': {'title': 'poem-title', 'author': 'poem-author',
                                        'attribution': 'attribution'}[b.part]})
                self.cur_doc = b.doc
                self.inline(b.el, e, sized=True)
                self._anchors(b, e)
                if b.part == 'attribution':
                    box.append(e)
                else:
                    box.insert(len([x for x in box if x.get('class') in ('poem-title', 'poem-author')]), e)
                continue
            indents = b.attrs.get('indents', [])
            spans = self._line_spans(b)
            multi = b.el.find('.//' + X + 'br') is not None
            if multi or b.gap_before:
                stanza = None                         # 一块多行 = 一节；单行块前有空段 = 新一节
            first = True
            k = 0
            for sp in spans:
                if sp is None:
                    stanza = None
                    k += 1
                    continue
                if first:
                    self._anchors(b, sp)
                    first = False
                add_line(sp, indents[k] if k < len(indents) else 0)
                k += 1
            if multi:
                stanza = None
        return box

    def _render_letter(self, group: list[Block]) -> etree._Element:
        """书信（04 §4.8）：叙事中引信用 blockquote.letter，各部分各自成段并带 z3998 语义。"""
        self.tpl_used.add('letter')
        self.rep.structures[('书信', 'B')] += 1
        box = _el('blockquote', {'class': 'letter', EPUB + 'type': 'z3998:letter'})
        spec = {'salutation-pre': ('salutation', 'z3998:salutation'), 'salutation': ('salutation', 'z3998:salutation'),
                'valediction': (None, 'z3998:valediction'), 'closing': ('closing', 'z3998:valediction'),
                'signature': ('signature', 'z3998:sender z3998:signature'), 'date': ('date', None),
                'dateline': ('dateline', None), 'postscript': ('postscript', 'z3998:postscript'), 'body': (None, None)}
        for b in group:
            cls, et = spec.get(b.part, (None, None))
            e = _el('p', {'class': cls, EPUB + 'type': et})
            self.cur_doc = b.doc
            self.inline(b.el, e)
            self._anchors(b, e)
            box.append(e)
        return box

    def _render_ol(self, group: list[Block]) -> etree._Element:
        """阿拉伯数字序号段 → ol，文字里的序号删去，由 ol 生成（04 4.10.3.1）。"""
        info = self.an.units[group[0].unit]
        self.rep.structures[('有序列表', 'B')] += 1
        ol = _el('ol', {'start': str(info['start']) if info.get('start', 1) != 1 else None})
        for b in group:
            li = _el('li')
            self.cur_doc = b.doc
            self.inline(b.el, li, OL_NUM)
            self._anchors(b, li)
            ol.append(li)
        return ol

    def _render_dl(self, group: list[Block]) -> etree._Element:
        info = self.an.units[group[0].unit]
        self.tpl_used.add('list')
        self.rep.structures[('定义列表', 'A')] += 1
        dl = _el('dl')
        for b in group:
            e = _el('dt' if b.part == 'dt' else 'dd')
            self.cur_doc = b.doc
            self.inline(b.el, e)
            self._anchors(b, e)
            dl.append(e)
        if info.get('glossary'):
            self._glossary_dl(dl)
        return dl

    def _glossary_dl(self, dl) -> None:
        """术语表的 dl（04 §4.19）：dt 加 glossterm 与 dfn，dd 加 glossdef 且内含 p。"""
        if 'glossary' in (dl.get('class') or ''):
            return
        self.tpl_used.add('glossary')
        dl.set('class', 'glossary')
        for e in dl:
            if e.tag == X + 'dt':
                e.set(EPUB + 'type', 'glossterm')
                if e.find(X + 'dfn') is None:
                    dfn = _el('dfn')
                    dfn.text, e.text = e.text, None
                    for c in list(e):
                        dfn.append(c)
                    e.append(dfn)
            elif e.tag == X + 'dd':
                e.set(EPUB + 'type', 'glossdef')
                if e.find(X + 'p') is None:
                    p = _el('p')
                    p.text, e.text = e.text, None
                    for c in list(e):
                        p.append(c)
                    e.append(p)

    def _render_list_of(self, rest: list[Block], ch: Chapter) -> etree._Element:
        """插图（表格）目录（04 4.11.4、4.13.1.10）：nav + h2 + ol，条目链接到图表的 id，删页码。"""
        head = rest[0]
        kind = self.an.units[head.unit]['kind']
        self.tpl_used.add('loi' if kind == 'loi' else 'table')
        self.rep.structures[('插图目录' if kind == 'loi' else '表格目录', 'A')] += 1
        nav = _el('nav', {'id': kind, 'class': kind, EPUB + 'type': kind})
        h = _el('h2', {'class': 'chapter-title'})
        self.cur_doc = head.doc
        self.inline(head.el, h, plain=True)
        self._anchors(head, h)
        nav.append(h)
        ol = _el('ol')
        for e in rest[1:]:
            if e.role != 'loi-entry':
                break
            li = _el('li')
            plan = self.list_entries.get(e.idx)
            if plan is None:
                li.text = PAGE_TAIL.sub('', e.text).strip()
            else:
                target, label = plan
                path, _, frag = target.partition('#')
                a = _el('a', {'href': f'{Book.relative(self.cur_new, path) if path != self.cur_new else ""}#{frag}'},
                        label)
                li.append(a)
            self._anchors(e, li)
            ol.append(li)
        nav.append(ol)
        return nav

    def _render_tables(self, b: Block, e: etree._Element, prev: Block | None) -> None:
        """表格结构规范化（04 4.13.1），上方的表题收进 caption。"""
        tables = [e] if e.tag == X + 'table' else list(e.iter(X + 'table'))
        if not tables:
            return
        self.tpl_used.add('table')
        for t in tables:
            for line in rebuild_table(t):
                self.rep.structures[(f'表格：{line}', 'A')] += 1
        if prev is not None and prev.role == 'table-caption' and prev.group == b.idx:
            cap = _el('caption')
            self.cur_doc = prev.doc
            self.inline(prev.el, cap, sized=True)
            self._anchors(prev, cap)
            self.cur_doc = b.doc
            tables[0].insert(0, cap)

    def render_endnotes(self) -> etree._Element:
        """书末尾注：<section epub:type="endnotes"><ol><li id="note-n"><p>注文 <a epub:type="backlink">↩</a></p></li></ol>。"""
        self.cur_new = self.endnotes_path
        html = etree.Element(X + 'html', nsmap={None: NS['xhtml'], 'epub': NS['epub']})
        html.set('lang', self.lang)
        html.set(XML_LANG, self.lang)
        head = etree.SubElement(html, X + 'head')
        etree.SubElement(head, X + 'meta', {'charset': 'utf-8'})
        etree.SubElement(head, X + 'title').text = '注释'
        etree.SubElement(head, X + 'link', {'rel': 'stylesheet', 'type': 'text/css',
                                            'href': Book.relative(self.endnotes_path, self.css_path)})
        body = etree.SubElement(html, X + 'body', {EPUB + 'type': 'backmatter'})
        sec = etree.SubElement(body, X + 'section', {'id': 'endnotes', 'class': 'endnotes',
                                                     EPUB + 'type': 'endnotes', 'role': 'doc-endnotes'})
        etree.SubElement(sec, X + 'h2', {'id': 'endnotes-title', 'class': 'chapter-title'}).text = '注释'   # h1 只给书名页
        ol = etree.SubElement(sec, X + 'ol')
        for num, b, ref_path in self.endnotes:
            self.cur_doc = b.doc
            li = etree.SubElement(ol, X + 'li', {'id': f'note-{num}'})
            p = etree.SubElement(li, X + 'p')
            body_src = copy.deepcopy(b.el)
            for a in list(body_src.iter(X + 'a')):         # 去掉原来的「[n]」回链（编号由 ol 自动生成）
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
            self.inline(body_src, p, NOTE_LABEL_RE, sized=True)
            last = p
            for nb in (x for x in self.an.blocks if x.role == 'note-cont' and x.group == b.idx):   # 多段注保留块结构
                self.cur_doc = nb.doc
                if nb.role == 'note-cont' and _local(nb.el.tag) == 'blockquote':
                    last = etree.SubElement(li, X + 'blockquote')
                    self.inline(nb.el, etree.SubElement(last, X + 'p'), sized=True)
                else:
                    last = etree.SubElement(li, X + 'p')
                    self.inline(nb.el, last, sized=True)
            back = _el('a', {'class': 'backlink', EPUB + 'type': 'backlink', 'role': 'doc-backlink',
                             'aria-label': '返回正文',
                             'href': f'{Book.relative(self.endnotes_path, ref_path)}#noteref-{num}'}, '↩')
            if last.tag == X + 'p':                       # 末块是段落：回链放段末，前面一个空格（SE 7.E）
                if len(last):
                    last[-1].tail = (last[-1].tail or '') + ' '
                else:
                    last.text = (last.text or '') + ' '
                last.append(back)
            else:                                        # 末块不是段落：回链单独成段
                etree.SubElement(li, X + 'p').append(back)
        return html

    def _book_title(self) -> str:
        t = self.book.opf.find('opf:metadata/dc:title', NS)
        return (t.text or '').strip() if t is not None else ''

    # ---------- 6. 写回 ----------

    def run(self) -> RebuildReport:
        book = self.book
        chapters = self.chapters = self.split()
        self.number_notes(chapters)
        self.plan_lists_of()
        old_docs = {b.doc for b in self.an.blocks}
        trees = [(ch, self.render_chapter(ch)) for ch in chapters]
        if self.endnotes:
            notes_ch = Chapter('注释', path=self.endnotes_path, epub_type='endnotes', role=None)
            trees.append((notes_ch, self.render_endnotes()))
        # 新文件继承来源文件的历史路径（guide/07 §7.4：拆分继承、合并取并集）
        hist = {d: book.history(d) for d in old_docs}
        for ch in chapters:
            book.origins[ch.path] = set().union(*(hist[b.doc] for b in ch.blocks)) - {ch.path}
        if self.endnotes:
            book.origins[self.endnotes_path] = set().union(*(hist[b.doc] for _, b, _ in self.endnotes))

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
        for name in TEMPLATE_ORDER:                   # 只追加用到的模板（04 附录 B.2 第 2 条）
            if name in self.tpl_used:
                css += b'\n' + template_css(name).encode('utf-8') + b'\n'
        if self.tpl_used:
            self.rep.log.append('追加模板样式：' + '、'.join(n for n in TEMPLATE_ORDER if n in self.tpl_used))
        self.rep.suggestions = self.an.suggestions + self.rep.suggestions
        book.add_item(self.css_path, 'text/css', item_id='typesetter-css', data=css)

        # 封面页
        cover_item = next((i for i in book.manifest() if 'cover-image' in i.properties), None)
        spine_ids = []
        if cover_item is not None:
            cover_path = posixpath.join(self.out_dir, 'cover.xhtml') if self.out_dir else 'cover.xhtml'
            src = Book.relative(cover_path, cover_item.path)
            # 04 §4.14：封面页引用主题样式表（不写内联样式），alt 带书名
            title = self._book_title()
            alt = f'封面：《{title}》' if title else '封面'
            css = Book.relative(cover_path, self.css_path)
            doc = (f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
                   f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
                   f'lang="{self.lang}" xml:lang="{self.lang}"><head><meta charset="utf-8"/><title>封面</title>'
                   f'<link rel="stylesheet" type="text/css" href="{escape(css)}"/></head>'
                   f'<body epub:type="frontmatter"><section id="cover" class="cover-page" epub:type="cover">'
                   f'<img role="doc-cover" src="{escape(src)}" alt="{escape(alt, {chr(34): "&quot;"})}"/>'
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
            heads = [h for h in html.iter(X + 'h2', X + 'h3', X + 'h4')
                     if set((h.get('class') or '').split()) & {'part-title', 'chapter-title', 'section-title'}]
            for k, h in enumerate(heads):
                entries.append(Entry(int(h.tag[-1]) - 1, squash(''.join(h.itertext())), ch.path,
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
        for c in chapters:
            if c.kind in ('loi', 'lot'):
                landmarks.append((c.kind, c.title, c.path))
        if any(c.epub_type == 'endnotes' for c in chapters):
            landmarks.append(('endnotes', '注释', self.endnotes_path))
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

