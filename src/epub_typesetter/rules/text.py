"""TYP / TXT：伪排版与文本规范化中可确定自动修的部分（guide/06、guide/07 §2.4/2.6）。

执行顺序说明：TYP-001（手工缩进）要先于 TXT-002（段首尾空白），
因为 TXT-002 会删掉段首全角空格，TYP-001 需要先据此判断全书是否「用空格缩进」。
"""
from __future__ import annotations

import re

from lxml import etree

from ..engine import AUTO, ERROR, INFO, MANUAL, SUGGEST, WARNING, Rule, register
from ..xhtml import RAW_TEXT_TAGS, X, body, css_paths
from ..book import Book

# 半角空格会被渲染折叠，不算缩进；但允许其前有源码换行/空格
INDENT_RE = re.compile(r'^[ \t\r\n]*[\u3000\u00a0\u2002\u2003]+')
# 删除：控制字符、BOM、零宽空格、词连接符。保留 ZWJ/ZWNJ（emoji、部分文字需要）
def indent_width(s: str) -> float:
    """行首空白的字宽：全角空格、em 空格算 1，不换行空格、en 空格算半个。"""
    return sum(1 if c in '\u3000\u2003' else .5 if c in '\u00a0\u2002' else 0 for c in s)


INVISIBLE_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufeff\u200b\u2060]')
MOJIBAKE_RE = re.compile(r'\ufffd|锟斤拷|烫烫烫|屯屯屯|Ã[\x80-\xbf]|ï¿½')
INDENT_CLASS = 'ts-indent'
OVERRIDE_CSS = 'typesetter.css'


def _text_nodes(root: etree._Element):
    """遍历 body 内可改写的文字位置 (元素, 'text'|'tail')，跳过 pre/code 等原样文本。"""
    def walk(el, raw):
        raw = raw or el.tag in RAW_TEXT_TAGS
        if not raw and el.text:
            yield el, 'text'
        for ch in el:
            if isinstance(ch.tag, str):
                yield from walk(ch, raw)
            if not raw and ch.tail:
                yield ch, 'tail'
    yield from walk(body(root), False)


def _paragraphs(root):
    return list(body(root).iter(X + 'p'))


def _leading_text(p: etree._Element) -> tuple[etree._Element, str] | None:
    """段落开头第一段文字所在的位置：p.text，或开头的内联元素的 text（如 <p><span>\u3000\u3000…）。"""
    el = p
    while True:
        if el.text and el.text.strip(' \t\r\n'):
            return el, 'text'
        if el.text and INDENT_RE.match(el.text):
            return el, 'text'
        kids = [c for c in el if isinstance(c.tag, str)]
        if not kids or el.text and el.text.strip():
            return None
        el = kids[0]


def ensure_override_css(book: Book, css: str, marker: str) -> str | None:
    """向本工具的附加样式表追加规则（已存在 marker 则跳过），并确保所有内容文档都链接它。"""
    opf_dir = book.opf_dir
    path = f'{opf_dir}/{OVERRIDE_CSS}' if opf_dir else OVERRIDE_CSS
    current = book.files[path].decode('utf-8') if path in book.files else '/* epub-typesetter 生成的附加样式 */\n'
    if marker in current:
        return None
    current += f'\n/* {marker} */\n{css}\n'
    if path not in book.files:
        book.add_item(path, 'text/css', item_id='typesetter-css')
    book.files[path] = current.encode('utf-8')
    for doc in book.content_docs():
        it = book.item_by_path(doc)
        if 'nav' in it.properties:
            continue
        root = book.tree(doc).getroot()
        head = root.find(X + 'head')
        href = Book.relative(doc, path)
        if head is not None and not any(l.get('href') == href for l in head.iter(X + 'link')):
            link = etree.SubElement(head, X + 'link')
            link.set('rel', 'stylesheet')
            link.set('type', 'text/css')
            link.set('href', href)
            book.mark_dirty(doc)
    return path


@register
class ManualIndent(Rule):
    id, title, order = 'TYP-001', '用空格做的首行缩进', 45
    node_fix = True

    def check(self, book):
        total = indented = 0
        per_doc = {}
        for path in book.content_docs():
            hits = []
            for p in _paragraphs(book.tree(path).getroot()):
                lt = _leading_text(p)
                if lt is None:
                    continue
                total += 1
                el, attr = lt
                if INDENT_RE.match(getattr(el, attr) or ''):
                    hits.append(self.hit(p))
            if hits:
                per_doc[path] = hits
                indented += len(hits)
        if not indented:
            return []
        ratio = indented / max(total, 1)
        level = AUTO if ratio < 0.05 or ratio > 0.5 else SUGGEST
        return [self.issue(WARNING, f'{len(hits)} 个段落用空格缩进（全书占 {ratio:.0%}）' if ratio >= 0.01 else f'{len(hits)} 个段落用空格缩进', path, level,
                           ratio=ratio, count=len(hits), hits=hits) for path, hits in per_doc.items()]

    def fix(self, book, issues):
        as_indent = issues[0].data['ratio'] > 0.5
        log = []
        for i in issues:
            k = 0
            keep = i.waived_nodes()
            for p in _paragraphs(book.tree(i.file).getroot()):
                lt = _leading_text(p)
                if lt is None or p in keep:
                    continue
                el, attr = lt
                s = getattr(el, attr) or ''
                if INDENT_RE.match(s):
                    book.removed_indent[p] = indent_width(INDENT_RE.match(s).group(0))
                    setattr(el, attr, INDENT_RE.sub('', s))
                    if as_indent:
                        cls = (p.get('class') or '').split()
                        if INDENT_CLASS not in cls:
                            p.set('class', ' '.join(cls + [INDENT_CLASS]))
                    k += 1
            book.mark_dirty(i.file)
            log.append(f'{i.file}：去掉 {k} 个段落的空格缩进')
        if as_indent:
            if ensure_override_css(book, f'p.{INDENT_CLASS} {{ text-indent: 2em; }}', 'TYP-001'):
                log.append(f'空格缩进是全书主流，改为 CSS 缩进（p.{INDENT_CLASS} {{text-indent:2em}}）')
        return log


def _is_empty_para(p: etree._Element) -> bool:
    if any(isinstance(c.tag, str) and c.tag not in (X + 'br', X + 'span', X + 'a', X + 'b', X + 'i', X + 'em',
                                                       X + 'strong', X + 'font', X + 'small')
           for c in p.iterdescendants()):
        return False                              # 含图片/svg 等
    text = ''.join(p.itertext())
    return not re.sub(r'[\s\u3000\u00a0\u200b\ufeff]', '', text)


def _referenced_ids(book: Book) -> set[tuple[str, str]]:
    from ..xhtml import is_external
    out = set()
    for path in list(book.files):
        if not path.lower().endswith(('.xhtml', '.html', '.htm', '.ncx')):
            continue
        root = book.tree(path).getroot()
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            v = el.get('href') or el.get('src')
            if v and '#' in v and not is_external(v):
                out.add((Book.resolve(path, v), v.partition('#')[2]))
    return out


def _keep_empty(p, path, refs) -> bool:
    """被链接的锚点、分页标记：保留。"""
    ids = {e.get('id') for e in p.iter() if isinstance(e.tag, str) and e.get('id')}
    return any((path, x) in refs for x in ids) or bool(PAGE_BREAK_CLASS.search(p.get('class') or ''))


PAGE_BREAK_CLASS = re.compile(r'(^|[\s_-])(pb|page-?break|pagebreak)', re.I)


@register
class EmptyParagraphs(Rule):
    id, title, order = 'TYP-002', '空段与伪空行', 46
    node_fix = True

    def check(self, book):
        out = []
        refs = _referenced_ids(book)
        for path in book.content_docs():
            root = book.tree(path).getroot()
            empties = [p for p in _paragraphs(root) if _is_empty_para(p) and not _keep_empty(p, path, refs)]
            edge = [p for p in _paragraphs(root) if not _is_empty_para(p) and _edge_brs(p)]
            if empties or edge:
                # 两类合成一条问题（同规则 × 同文件），命中分别带上各自的补丁
                hits = [self.hit(p, fix={'op': 'remove_node'}) for p in empties]
                hits += [self.hit(br, fix={'op': 'remove_node'}) for p in edge for br in _edge_brs(p)]
                parts = [f'{len(empties)} 个空段落'] if empties else []
                parts += [f'{len(edge)} 个段落首尾有多余 <br/>'] if edge else []
                out.append(self.issue(WARNING, '，'.join(parts), path, AUTO, hits=hits))
        return out

    def fix(self, book, issues):
        log = []
        refs = _referenced_ids(book)
        for i in issues:
            root = book.tree(i.file).getroot()
            keep = i.waived_nodes()
            removed = kept = 0
            for p in [p for p in _paragraphs(root) if _is_empty_para(p)]:
                if _keep_empty(p, i.file, refs) or p in keep:
                    kept += 1
                    continue
                _remove_keep_tail(p)
                removed += 1
            if removed:
                log.append(f'{i.file}：删除空段 {removed} 个' + (f'（保留锚点/分页标记/已豁免 {kept} 个）' if kept else ''))
            n = 0
            for p in _paragraphs(root):
                if p in keep:
                    continue
                for br in _edge_brs(p):
                    if br not in keep:
                        _remove_keep_tail(br)
                        n += 1
            if n:
                log.append(f'{i.file}：删除段落首尾 <br/> {n} 个')
            book.mark_dirty(i.file)
        return log


def _edge_brs(p) -> list:
    """段首（前面没有文字）和段尾（后面没有文字）的 br。诗节 p.stanza 的 br 归 SEM-034 管（04 附录 B.2 第 8 条）。"""
    if 'stanza' in (p.get('class') or '').split():
        return []
    kids = [c for c in p if isinstance(c.tag, str)]
    out = []
    if not (p.text or '').strip():
        for c in kids:
            if c.tag == X + 'br' and not (c.tail or '').strip():
                out.append(c)
            elif c.tag == X + 'br':
                out.append(c)
                break
            else:
                break
    for c in reversed(kids):
        if c.tag == X + 'br' and not (c.tail or '').strip() and c not in out:
            out.append(c)
        else:
            break
    return out


def _remove_keep_tail(el):
    parent = el.getparent()
    if parent is None:
        return
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or '') + el.tail
        else:
            parent.text = (parent.text or '') + el.tail
    parent.remove(el)


@register
class InvisibleChars(Rule):
    id, title, order = 'TXT-001', '乱码与不可见字符', 50
    node_fix = True

    def check(self, book):
        out = []
        for path in book.content_docs():
            root = book.tree(path).getroot()
            inv, moj = [], []
            for el, attr in _text_nodes(root):
                s = getattr(el, attr)
                for rx, acc in ((INVISIBLE_RE, inv), (MOJIBAKE_RE, moj)):
                    if rx.search(s):
                        acc.extend(_text_hits(self, el, attr, rx))
            if inv:
                out.append(self.issue(WARNING, f'{len(inv)} 个不可见/控制字符', path, AUTO, hits=inv))
            if moj:
                out.append(self.issue(ERROR, f'{len(moj)} 处疑似乱码（U+FFFD 或误解码特征）', path, MANUAL, hits=moj))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            root = book.tree(i.file).getroot()
            keep = _waived_ranges(i)
            n = 0
            # 先算好每个文字位置的起点再改（同一元素里前面的删除会让后面的偏移变化）
            for el, attr, base in [(e, a, _text_base(e, a)) for e, a in _text_nodes(root)]:
                owner = _owner(el, attr)
                s = getattr(el, attr)
                new = INVISIBLE_RE.sub(lambda m: m.group(0) if (owner, base + m.start()) in keep else '', s)
                if new != s:
                    n += len(s) - len(new)
                    setattr(el, attr, new)
            book.mark_dirty(i.file)
            log.append(f'{i.file}：删除不可见字符 {n} 个')
        return log


def _owner(el, attr):
    """文字位置所在的元素：text 属于 el 本身，tail 属于 el 的父元素。"""
    return el if attr == 'text' else el.getparent()


def _text_base(el, attr) -> int:
    """文字位置在所属元素完整文字（itertext）中的起点。"""
    if attr == 'text':
        return 0
    owner = el.getparent()
    n = len(owner.text or '')
    for c in owner:
        if c is el:
            return n + (len(''.join(c.itertext())) if isinstance(c.tag, str) else 0)
        n += (len(''.join(c.itertext())) if isinstance(c.tag, str) else 0) + len(c.tail or '')
    return n


def _text_hits(rule, el, attr, rx):
    """文字位置里每处匹配一个命中；区间相对所在元素的完整文字（豁免的文字锚点据此判断重叠）。"""
    owner = _owner(el, attr)
    full = ''.join(owner.itertext())
    base = _text_base(el, attr)
    return [rule.hit(owner, (base + m.start(), base + m.end()), full) for m in rx.finditer(getattr(el, attr))]


def _waived_ranges(issue) -> set:
    """已豁免的文本命中：{(所属元素, 起点)}。"""
    return {(h.el, h.range[0]) for h in issue.hits if h.waived and h.range}


BLOCK_FOR_TRIM = ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'figcaption', 'dt', 'dd', 'td', 'th', 'caption')
TRIM_CHARS = ' \t\r\n\u3000\u00a0'


@register
class Whitespace(Rule):
    """只做确定无害的部分：段首尾空白、行内多个半角空格/制表符折叠。
    汉字之间的空格（可能是诗句分隔、也可能是 OCR 遗留）不自动删，留给 suggest（guide/06 SPC-06）。"""
    id, title, order = 'TXT-002', '空白规范', 51

    MULTI = re.compile(r'[ \t]{2,}|\t')

    def _targets(self, root):
        for tag in BLOCK_FOR_TRIM:
            yield from body(root).iter(X + tag)

    def check(self, book):
        out = []
        for path in book.content_docs():
            root = book.tree(path).getroot()
            edge = sum(1 for b in self._targets(root) if self._edge(b))
            multi = sum(len(self.MULTI.findall(getattr(e, a))) for e, a in _text_nodes(root))
            if edge or multi:
                out.append(self.issue(WARNING, f'段首尾空白 {edge} 处，多余空格 {multi} 处', path, AUTO))
        return out

    @staticmethod
    def _trim(b, apply: bool) -> int:
        """修剪块首尾空白；某个文字节点被剪空时继续剪相邻节点，保证一次到位（幂等）。"""
        nodes = list(_iter_block_text(b))
        n = 0
        for seq, strip in ((nodes, str.lstrip), (nodes[::-1], str.rstrip)):
            for e, a in seq:
                s = getattr(e, a) or ''
                t = strip(s, TRIM_CHARS)
                if t != s:
                    n += 1
                    if apply:
                        setattr(e, a, t)
                if t:
                    break
        return n

    def _edge(self, b) -> bool:
        return self._trim(b, apply=False) > 0

    def fix(self, book, issues):
        log = []
        for i in issues:
            root = book.tree(i.file).getroot()
            n = 0
            for e, a in _text_nodes(root):
                s = getattr(e, a)
                new = self.MULTI.sub(' ', s)
                if new != s:
                    setattr(e, a, new)
                    n += 1
            for b in self._targets(root):
                n += self._trim(b, apply=True)
            book.mark_dirty(i.file)
            log.append(f'{i.file}：规范空白 {n} 处')
        return log


def _iter_block_text(b):
    """块内按文档顺序的文字位置，不进入嵌套的块和原样文本元素；跳过纯空白节点之间的位置也保留。"""
    def walk(el):
        if el.text:
            yield el, 'text'
        for ch in el:
            if not isinstance(ch.tag, str):
                if ch.tail:
                    yield ch, 'tail'
                continue
            if ch.tag in RAW_TEXT_TAGS or ch.tag == X + 'br':
                pass
            elif ch.tag in {X + t for t in BLOCK_FOR_TRIM} | {X + 'div', X + 'blockquote', X + 'ul', X + 'ol',
                                                             X + 'table'}:
                pass
            else:
                yield from walk(ch)
            if ch.tail:
                yield ch, 'tail'
    return walk(b)
