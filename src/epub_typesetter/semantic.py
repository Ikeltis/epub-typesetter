"""语义分析（M2）：把全书拆成「内容块」，给每块判定角色。

输入应是已经过 M0 规范化（engine.fix）的书：此时 <font> 已转成带 style 的 span，
命名空间、实体等都已规整。判定全部是启发式 + 可解释的理由（reason），
置信度低的留给网页上的确认板 / 大模型（guide/04 各模板的「识别信号」）。

角色：
  heading    标题（level 1–3）         para      正文段落
  figure     只有图片的块              caption   图注
  source     资料来源/图表出处         bullet    以 ● 等符号开头的列表项
  note       注释正文                  note-head 注释区小标题（「注释」）
  toc        书内目录页（由 nav 取代） junk      广告/引流内容
  meta       版权页的「键：值」行      quote     引文
  right      右对齐短行（落款）        center    居中短行
  keep       表格、pre 等原样保留的块
  note-cont  多段注的续段               heading-merged 已并入相邻标题的块（章号、章名各成标题时）
  poem / letter / dl / ol    成组结构（同组 unit 相同，part 是组内角色），见 structures.py
  item / article             中文序号项、法规条文（04 §4.10）
  loi-head / loi-entry       插图（表格）目录页        table-caption / table-note  表题、表注
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import tinycss2
from lxml import etree

from .book import NS, Book
from .nav import entries_from_ncx
from .xhtml import X, css_paths, is_external, squash

BLOCK_TAGS = {X + t for t in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'li', 'dt', 'dd', 'div',
                              'figcaption', 'pre', 'table', 'figure', 'section', 'article', 'aside',
                              'ul', 'ol', 'dl', 'nav', 'header', 'footer', 'hr')}
CONTAINERS = {X + t for t in ('div', 'section', 'article', 'blockquote', 'ul', 'ol', 'dl', 'header', 'footer',
                              'aside', 'nav')}
ATOMIC = {X + t for t in ('table', 'pre', 'figure', 'hr', 'math')}

ORDINAL_ONLY_RE = re.compile(r'^(第[一二三四五六七八九十百千零〇两\d]+[章回节卷部篇编]|chapter\s*\d+|'
                             r'[一二三四五六七八九十百千]+|[ivxlc]+|\d{1,3})$', re.I)
CHAPTER_RE = re.compile(r'^(第[一二三四五六七八九十百千零〇\d]+[章篇部卷回节]|chapter\s*\d+|part\s*\d+)', re.I)
TOC_TITLES = {'目录', '目次', 'contents', 'tableofcontents', '目录contents'}
NOTE_TITLES = {'注释', '注', '注解', '注释与参考', '尾注', '脚注', '译注', 'notes'}
BULLET_RE = re.compile(r'^[●•◆◇■□▪▫○◎※►▶➢✓✔]\s*')
NOTE_LABEL_RE = re.compile(r'^\s*(\[\d{1,3}\]|［\d{1,3}］|\(\d{1,3}\)|（\d{1,3}）|[①-⑳]|注\d{1,3}[：:.．]?)')
CAPTION_RE = re.compile(r'^(图|表|插图|figure|fig\.?|table)\s*[\d一二三四五六七八九十]', re.I)
SOURCE_RE = re.compile(r'^(资料来源|数据来源|来源|出处|图片来源|source)[：:]', re.I)
META_RE = re.compile(r'^[^：:，。]{1,10}[：:]\S')
JUNK_RE = re.compile(r'公众号|微信|扫码|电子书(搜索|下载|打包)|资源分享|书单分享|书友|交流群|QQ群|网站[：:]|'
                     r'https?://|www\.|读累了|更多(好书|电子书)')
COPYRIGHT_TITLES = ('版权信息', '版权页', '版权')

KEYWORD_SIZE = {'xx-small': 1, 'x-small': 1, 'small': 2, 'medium': 3, 'large': 4, 'x-large': 5,
                'xx-large': 6, 'xxx-large': 7}


@dataclass
class Block:
    idx: int
    doc: str
    el: etree._Element
    text: str
    anchors: list[str] = field(default_factory=list)   # 指向本块的 id（自身、内部、紧邻其前的空锚点）
    size: int = 3                                       # 字号等级（1–7，3 为正文）
    bold: bool = False
    align: str = ''
    role: str = 'para'
    level: int = 0
    confidence: float = 1.0
    reason: str = ''
    group: int = -1                                     # caption/source 归属的 figure 块序号
    merged: int = -1                                    # 与本标题合并的另一个标题块（章号 + 章名，04 §4.3）
    ordinal_first: bool = True                          # 合并后先输出哪一块：章号块在前
    indent: float = 0                                   # 段首空格缩进的字宽（规范修复删掉的也算）
    gap_before: bool = False                            # 前面紧挨着被跳过的空段（诗节、场景分隔的线索）
    unit: int = -1                                      # 成组结构的编号（诗、信、列表…），见 Analysis.units
    part: str = ''                                      # 组内角色：title / line / salutation / signature …
    attrs: dict = field(default_factory=dict)           # 组内补充信息（缩进级、序号、悬挂宽度…）
    verify: str | None = None                           # 文字校验用的期望文字（重建有意改写时，如删去手写序号）

    def short(self, n=30) -> str:
        return self.text[:n]


@dataclass
class Analysis:
    blocks: list[Block]
    toc_labels: dict[tuple[str, str], str]              # (doc, id) → 目录标签
    noterefs: dict[int, list[etree._Element]]           # note 块序号 → 指向它的 <a>
    junk_docs: set[str]
    vertical: bool = False                              # 整本竖排（重建时要保留）
    units: dict[int, dict] = field(default_factory=dict)   # 成组结构：编号 → {kind, level(A/B), …}
    suggestions: list[dict] = field(default_factory=list)  # 只给建议、不自动改的识别结果（C 级，04 各节「识别信号」）

    def counts(self) -> Counter:
        return Counter(b.role if b.role != 'heading' else f'h{b.level}' for b in self.blocks)

    def by_role(self, role: str) -> list[Block]:
        return [b for b in self.blocks if b.role == role]


def _norm(s: str) -> str:
    return re.sub(r'\s+', '', s or '')


def _local(tag) -> str:
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


# ---------- 类样式（简单层叠：.x / tag.x 选择器） ----------

def class_styles(book: Book) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for path in css_paths(book):
        css = book.files[path].decode('utf-8', 'replace')
        for rule in tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True):
            if rule.type != 'qualified-rule':
                continue
            sel = tinycss2.serialize(rule.prelude).strip()
            decls = {}
            for d in tinycss2.parse_blocks_contents(rule.content, skip_whitespace=True, skip_comments=True):
                if d.type == 'declaration':
                    decls[d.lower_name] = tinycss2.serialize(d.value).strip().lower()
            for part in sel.split(','):
                m = re.fullmatch(r'\s*[a-z0-9]*\.([\w-]+)\s*', part, re.I)
                if m:
                    out.setdefault(m.group(1), {}).update(decls)
    return out


def is_vertical(book: Book) -> bool:
    """整本竖排：OPF 声明 primary-writing-mode，或样式表里 html/body 设了 vertical 书写方向。"""
    for m in book.opf.iterfind('opf:metadata/opf:meta', NS):
        if m.get('name') == 'primary-writing-mode' and 'vertical' in (m.get('content') or ''):
            return True
    for path in css_paths(book):
        css = book.files[path].decode('utf-8', 'replace')
        for rule in tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True):
            if rule.type == 'qualified-rule':
                sel = tinycss2.serialize(rule.prelude).strip().lower()
                body = tinycss2.serialize(rule.content).lower()
                if re.fullmatch(r'(html|body)(\s*,\s*(html|body))*', sel) and re.search(r'writing-mode\s*:\s*vertical', body):
                    return True
    return False


def _style_of(el, classes: dict) -> dict[str, str]:
    st = {}
    for c in (el.get('class') or '').split():
        st.update(classes.get(c, {}))
    for part in (el.get('style') or '').split(';'):
        if ':' in part:
            k, v = part.split(':', 1)
            st[k.strip().lower()] = v.strip().lower()
    return st


def _size_level(v: str) -> int | None:
    v = v.strip()
    if v in KEYWORD_SIZE:
        return KEYWORD_SIZE[v]
    if v == 'larger':
        return 4
    if v == 'smaller':
        return 2
    m = re.match(r'([\d.]+)\s*(em|rem|%)', v)
    if m:
        x = float(m.group(1)) / (100 if m.group(2) == '%' else 1)
        return 7 if x >= 2 else 6 if x >= 1.6 else 5 if x >= 1.3 else 4 if x >= 1.1 else 3 if x >= .95 else 2
    return None


def _visual(el, classes) -> tuple[int, bool, str]:
    """块的字号等级（取文字所在元素中最大的）、是否整块加粗、对齐方式。"""
    st = _style_of(el, classes)
    align = st.get('text-align', '')
    # 每段文字的字号取「离它最近的、声明了 font-size 的祖先」（层叠继承），块内取最大
    block_size = _size_level(st.get('font-size', ''))
    known = []
    for d in el.iter():
        if not isinstance(d.tag, str) or not (d.text or '').strip():
            continue
        lv, cur = None, d
        while cur is not None and lv is None:
            lv = _size_level(_style_of(cur, classes).get('font-size', ''))
            if cur is el:
                break
            cur = cur.getparent()
        known.append(lv or block_size)
    known = [k for k in known if k]
    tag = _local(el.tag)
    size = max(known) if known else ({'h1': 7, 'h2': 6, 'h3': 5, 'h4': 4}.get(tag, 3))
    text = _norm(''.join(el.itertext()))
    bold_text = _norm(''.join(t for b in el.iter(X + 'b', X + 'strong') for t in b.itertext()))
    bold = bool(text) and bold_text == text or st.get('font-weight', '') in ('bold', '700', '800', '900')
    return size, bold, align


# ---------- 块提取 ----------

def _is_block(el) -> bool:
    return isinstance(el.tag, str) and el.tag in BLOCK_TAGS


def _has_block_child(el) -> bool:
    return any(_is_block(c) for c in el.iterdescendants())


_LEAD_WS = re.compile(r'^[ \t\r\n]*([\u3000\u00a0\u2002\u2003]+)')


def _indent_of(book: Book, el) -> float:
    """段首缩进字宽：还留在文字里的，或规范修复（TYP-001）删掉时记下的。"""
    from .rules.text import indent_width
    m = _LEAD_WS.match(''.join(el.itertext()))
    return indent_width(m.group(1)) if m else book.removed_indent.get(el, 0)


def extract_blocks(book: Book) -> list[Block]:
    classes = class_styles(book)
    blocks: list[Block] = []
    for it in book.spine_items():
        if it.media_type != 'application/xhtml+xml' or it.path not in book.files or 'nav' in it.properties:
            continue
        root = book.tree(it.path).getroot()
        body = root.find(X + 'body')
        if body is None:
            continue
        # 链接可能指向文件本身（body/html 上的 id），它们归属文件的第一块
        pending: list[str] = [x for x in (root.get('id'), body.get('id')) if x]
        gap = [False]

        def walk(el):
            for ch in el:
                if not isinstance(ch.tag, str):
                    continue
                if _is_block(ch) and (ch.tag in ATOMIC or not (ch.tag in CONTAINERS and _has_block_child(ch))
                                      and not _has_block_child(ch)):
                    text = squash(''.join(ch.itertext()))
                    ids = [ch.get('id')] if ch.get('id') else []
                    ids += [d.get('id') for d in ch.iterdescendants() if isinstance(d.tag, str) and d.get('id')]
                    size, bold, align = _visual(ch, classes)
                    has_media = any(isinstance(d.tag, str) and _local(d.tag) in ('img', 'svg', 'image')
                                    for d in ch.iter())
                    if not text and not has_media and ch.tag not in ATOMIC:
                        pending.extend(ids)       # 空块（如 <p id=x/>）当锚点用
                        gap[0] = True
                        continue
                    blocks.append(Block(len(blocks), it.path, ch, text, pending + ids, size, bold, align,
                                        indent=_indent_of(book, ch), gap_before=gap[0]))
                    pending.clear()
                    gap[0] = False
                elif _is_block(ch):
                    if ch.get('id'):
                        pending.append(ch.get('id'))
                    walk(ch)
                else:
                    # 块外的行内元素：空锚点（<span id=x/>）、游离文字（少见，作为段落）、
                    # 或与段落并列放在容器里的图片（<div><img/><p>图注</p></div>）——图片必须成块，否则会丢
                    text = squash(''.join(ch.itertext()))
                    ids = [d.get('id') for d in ch.iter() if isinstance(d.tag, str) and d.get('id')]
                    has_media = any(isinstance(d.tag, str) and _local(d.tag) in ('img', 'svg', 'image')
                                    for d in ch.iter())
                    if not text and not has_media:
                        pending.extend(ids)
                    else:
                        size, bold, align = _visual(ch, classes)
                        blocks.append(Block(len(blocks), it.path, ch, text, pending + ids, size, bold, align))
                        pending.clear()
        walk(body)
    return blocks


# ---------- 角色判定 ----------

def _toc_targets(book: Book) -> dict[tuple[str, str], str]:
    out = {}
    for e in entries_from_ncx(book):
        out[(e.path, e.fragment)] = e.label
    navs = [i for i in book.manifest() if 'nav' in i.properties and i.path in book.files]
    if navs:
        root = book.tree(navs[0].path).getroot()
        for nav in root.iter(X + 'nav'):
            if nav.get('{%s}type' % NS['epub']) != 'toc':
                continue
            for a in nav.iter(X + 'a'):
                href = a.get('href', '')
                if href and not is_external(href):
                    out.setdefault((Book.resolve(navs[0].path, href), href.partition('#')[2]),
                                   squash(''.join(a.itertext())))
    return out


def _link_only(el) -> bool:
    """块里的文字全部在内部链接中（目录页的典型特征）。"""
    total = _norm(''.join(el.itertext()))
    linked = _norm(''.join(t for a in el.iter(X + 'a') if a.get('href') and not is_external(a.get('href'))
                           for t in a.itertext()))
    return bool(total) and total == linked


# ---------- 确认板：段落样式簇 ----------

# 用户可以整簇改的角色（确认板的选项）；chapter / section 是标题的两档
REASSIGNABLE = ('para', 'quote', 'center', 'right', 'heading', 'junk', 'meta')
CLUSTER_ROLES = ('para', 'quote', 'center', 'right', 'chapter', 'section', 'meta', 'junk')


def cluster_key(b: Block) -> str:
    """段落样式簇：原元素、原类名、字号级、粗体、对齐、缩进相同的块归一簇（软件设计建议 §4）。"""
    return '|'.join((_local(b.el.tag), b.el.get('class') or '', f's{b.size}', 'b' if b.bold else '',
                     b.align, f'i{int(b.indent)}'))


def apply_cluster_roles(blocks: list[Block], clusters: dict[str, str]) -> None:
    """按用户在确认板上给的整簇角色改写块角色。"""
    if not clusters:
        return
    for b in blocks:
        role = clusters.get(cluster_key(b))
        if role is None or b.role not in REASSIGNABLE or role not in CLUSTER_ROLES:
            continue
        if b.merged >= 0 and role not in ('chapter', 'section'):    # 合并过的标题拆回两段
            other = blocks[b.merged]
            other.role, other.reason = 'para', '用户改为非标题'
            b.merged = -1
            b.verify = squash(''.join(b.el.itertext()))
        if role in ('chapter', 'section'):
            b.role, b.level, b.attrs['force'] = 'heading', 1 if role == 'chapter' else 2, role
        else:
            b.role = role
        b.reason = f'用户确认：整簇改为 {role}'


def analyze(book: Book, decisions: dict | None = None) -> Analysis:
    """decisions：确认板上的用户决定（clusters 整簇角色、kinds/items 结构取舍），见 board.py。"""
    decisions = decisions or {}
    blocks = extract_blocks(book)
    toc = _toc_targets(book)
    first_block_of_doc = {}
    for b in blocks:
        first_block_of_doc.setdefault(b.doc, b)

    # 1) 目录指向的块 → 标题候选
    for b in blocks:
        label = None
        for a in b.anchors:
            label = toc.get((b.doc, a)) or label
        if label is None and first_block_of_doc[b.doc] is b:
            label = toc.get((b.doc, ''))
        tag = _local(b.el.tag)
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            b.role, b.reason = 'heading', f'原有 <{tag}>'
            b.level = int(tag[1])
        elif label is not None and len(b.text) <= 60 and _norm(label)[:6] in _norm(b.text):
            b.role, b.reason = 'heading', f'目录项「{label[:20]}」指向此处'

    # 2) 书内目录页：标题是「目录/Contents」，其后到下一个标题前的全链接块
    in_toc = False
    for b in blocks:
        key = _norm(b.text).lower().replace('\u3000', '')
        if b.role == 'heading':
            if in_toc and _link_only(b.el):           # 目录页条目写成 <h4><a>…</a></h4>
                b.role, b.reason = 'toc', '目录页条目（链接型标题）'
                continue
            in_toc = key in TOC_TITLES or key.startswith('目录')
            if in_toc:
                b.role, b.reason = 'toc', '书内目录页标题'
            continue
        if key in TOC_TITLES:
            b.role, b.reason, in_toc = 'toc', '书内目录页标题', True
            continue
        if in_toc and (_link_only(b.el) or not b.text):
            b.role, b.reason = 'toc', '目录页条目'
        else:
            in_toc = False

    # 3) 「第一回」单独一个标题、紧挨着章名标题：合并成一个（04 §4.3，08 决策 D1）
    for b in blocks:
        if b.role != 'heading' or b.merged >= 0:
            continue
        nxt = blocks[b.idx + 1] if b.idx + 1 < len(blocks) else None
        if nxt is None or nxt.role != 'heading' or nxt.doc != b.doc or nxt.merged >= 0:
            continue
        a_ord, b_ord = bool(ORDINAL_ONLY_RE.match(b.text)), bool(ORDINAL_ONLY_RE.match(nxt.text))
        if a_ord == b_ord:                         # 两个都是章号、或都不是：不合并
            continue
        if b_ord:                                  # 章名在前、章号在后：只有章号后面不再紧跟标题时才向前合并
            after = blocks[nxt.idx + 1] if nxt.idx + 1 < len(blocks) else None
            if after is not None and after.role == 'heading' and after.doc == nxt.doc:
                continue                           # 这个章号属于后面的章名
        ordinal, title = (b, nxt) if a_ord else (nxt, b)
        b.merged, b.ordinal_first = nxt.idx, a_ord
        b.text = f'{ordinal.text}\u3000{title.text}'
        b.level = min(b.level, nxt.level) if b.level and nxt.level else (b.level or nxt.level)
        b.size = max(b.size, nxt.size)
        b.anchors = b.anchors + [x for x in nxt.anchors if x not in b.anchors]
        nxt.role, nxt.reason, nxt.anchors = 'heading-merged', f'并入标题「{b.text[:12]}」', []
        b.reason += '；章号与章名合并'

    # 4) 标题层级：按字号等级排序；无字号差异时「第X章」为 1 级
    heads = [b for b in blocks if b.role == 'heading']
    from_toc = [b for b in heads if b.reason.startswith('目录项')]
    if from_toc:
        sizes = sorted({b.size for b in from_toc}, reverse=True)
        if len(sizes) > 1:
            for b in from_toc:
                b.level = min(sizes.index(b.size) + 1, 3)
        else:
            has_chapter = any(CHAPTER_RE.match(b.text) for b in from_toc)
            for b in from_toc:
                b.level = 1 if (not has_chapter or CHAPTER_RE.match(b.text)) else 2
    if heads:
        top = min(b.level for b in heads)
        for b in heads:
            b.level = max(1, b.level - top + 1)
        # 「第X章/回/卷」至少 3 个、比它们高的标题不超过 2 个（书名页、凡例之类）：它们才是章，提为一级
        chap = [b for b in heads if CHAPTER_RE.match(b.text)]
        if len(chap) >= 3 and len({b.level for b in chap}) == 1 and chap[0].level > 1:
            lv = chap[0].level
            if sum(1 for b in heads if b.level < lv) <= 2:
                for b in heads:
                    b.level = 1 if b.level <= lv else b.level - lv + 1

    # 5) 注释：短链接 [n] → 目标块以同一编号开头
    by_anchor = {(b.doc, a): b for b in blocks for a in b.anchors}
    noterefs: dict[int, list] = {}
    for b in blocks:
        if b.role in ('toc', 'heading'):
            continue
        for a in b.el.iter(X + 'a'):
            label = _norm(''.join(a.itertext()))
            href = a.get('href', '')
            if not href or is_external(href) or '#' not in href or not NOTE_LABEL_RE.fullmatch(label or 'x'):
                continue
            target = by_anchor.get((Book.resolve(b.doc, href), href.partition('#')[2]))
            if target is None or target is b or not _norm(target.text).startswith(label):
                continue
            target.role, target.reason = 'note', f'被正文注号 {label} 指向'
            noterefs.setdefault(target.idx, []).append(a)
    # 多段注：注释段之后、下一条注或标题之前，字号与注释相同的段落是续段（04 4.12.3.3）
    for b in blocks:
        if b.role != 'note':
            continue
        j = b.idx + 1
        while j < len(blocks):
            nb = blocks[j]
            if nb.doc != b.doc or nb.role != 'para' and nb.role != 'quote' or nb.size != b.size \
                    or NOTE_LABEL_RE.match(nb.text) or _norm(nb.text) in NOTE_TITLES:
                break
            nb.role, nb.group, nb.reason = 'note-cont', b.idx, '注释的续段'
            j += 1
    for b in blocks:
        if b.role == 'para' and _norm(b.text) in NOTE_TITLES:
            nxt = blocks[b.idx + 1] if b.idx + 1 < len(blocks) else None
            if nxt is not None and nxt.role == 'note':
                b.role, b.reason = 'note-head', '注释区小标题'

    # 6) 图、图注、资料来源
    for b in blocks:
        if b.role != 'para':
            continue
        if not b.text and any(_local(d.tag) in ('img', 'svg', 'image') for d in b.el.iter() if isinstance(d.tag, str)):
            b.role, b.reason = 'figure', '只含图片'
        elif _local(b.el.tag) == 'figure':
            b.role, b.reason = 'figure', '原有 <figure>'
    for b in blocks:
        if b.role != 'figure' or _local(b.el.tag) == 'figure':   # 原有 <figure> 自带图注，不再拼接
            continue
        # 图片与几段文字同在一个图片容器里（<div class="…image"><img/><p>题</p><p>说明</p></div>）：
        # 容器里图后的文字段都是图注（04 4.11.3.5：多段图注每段一个 p）
        box = b.el.getparent() if _local(b.el.tag) in ('img', 'svg') else None
        if box is not None and _local(box.tag) in ('div', 'figure') and \
                all(_local(c.tag) in ('img', 'svg', 'p', 'span', 'br') for c in box if isinstance(c.tag, str)):
            j = b.idx + 1
            while j < len(blocks) and blocks[j].el.getparent() is box and blocks[j].role == 'para':
                blocks[j].role, blocks[j].group, blocks[j].reason = 'caption', b.idx, '与图同在图片容器里的图注'
                j += 1
            if j > b.idx + 1:
                continue
        j = b.idx + 1
        if j < len(blocks) and blocks[j].role == 'para' and len(blocks[j].text) <= 80 and blocks[j].doc == b.doc and \
                (CAPTION_RE.match(blocks[j].text) or blocks[j].align == 'center' and blocks[j].size <= 3):
            blocks[j].role, blocks[j].group, blocks[j].reason = 'caption', b.idx, '紧跟图片的图注'
            j += 1
        if j < len(blocks) and blocks[j].role in ('para', 'quote') and SOURCE_RE.match(blocks[j].text) and \
                len(blocks[j].text) <= 120:
            blocks[j].role, blocks[j].group, blocks[j].reason = 'source', b.idx, '图后的资料来源'

    # 7) 广告文件：整份文件多数块是引流内容
    junk_docs = set()
    per_doc = Counter(b.doc for b in blocks)
    junk_hits = Counter(b.doc for b in blocks if JUNK_RE.search(b.text))
    for doc, n in per_doc.items():
        if n <= 40 and junk_hits[doc] >= max(2, n * 0.3):
            junk_docs.add(doc)
    for b in blocks:
        if b.doc in junk_docs:
            b.role, b.reason = 'junk', '引流/广告页'

    # 8) 其他：列表项、版权页、对齐短行、引文
    section = ''
    for b in blocks:
        if b.role == 'heading':
            section = _norm(b.text)
            continue
        if b.role != 'para':
            continue
        if BULLET_RE.match(b.text):
            b.role, b.reason = 'bullet', '以项目符号开头'
        elif section.startswith(COPYRIGHT_TITLES) and META_RE.match(b.text) and len(b.text) <= 80:
            b.role, b.reason = 'meta', '版权页键值行'
        elif b.align == 'right' and len(b.text) <= 40:
            b.role, b.reason = 'right', '右对齐短行'
        elif b.align == 'center' and len(b.text) <= 40:
            b.role, b.reason = 'center', '居中短行'
        elif _local(b.el.tag) in ('table', 'pre', 'math', 'hr') or (_local(b.el.tag) == 'div' and b.el.find('.//' + X + 'table') is not None):
            b.role, b.reason = 'keep', f'<{_local(b.el.tag)}> 原样保留'
        elif _local(b.el.tag) == 'blockquote':
            b.role, b.reason = 'quote', '原有 <blockquote>'
    apply_cluster_roles(blocks, decisions.get('clusters') or {})
    an = Analysis(blocks, toc, noterefs, junk_docs, is_vertical(book))
    # 9) 成组结构：诗歌、书信、列表、条文、插图目录、表题表注、术语表（structures.py），再按用户取舍
    from .structures import detect
    detect(book, an, decisions)
    return an
