"""SEM：内容文档良构与语义（guide/07 §2.2、guide/02）。"""
from __future__ import annotations

import re
from collections import Counter

from lxml import etree

from ..book import NS, Book, _strict_parser, has_html_entities
from ..engine import AUTO, ERROR, MANUAL, WARNING, Rule, register
from ..xhtml import HEADINGS, X, body, rename_ids, text_of

# NCName 的实用近似：字母/下划线开头（含 CJK 等非 ASCII 字母），后续可含数字、. - _，不含冒号与空白
NCNAME = re.compile(r'^[A-Za-z_\u00c0-\uffff][\w.\-\u00b7\u00c0-\uffff]*$')
FILENAME_LIKE = re.compile(r'(\.x?html?$)|^\d+$|^(untitled|无标题|part\d+|chapter\d*|text\d*)$', re.I)


@register
class WellFormed(Rule):
    id, title, order = 'SEM-001', 'XHTML 良构', 30

    def check(self, book):
        out = []
        for path in book.content_docs():
            data = book.files[path]
            try:
                etree.fromstring(data, _strict_parser())
            except etree.XMLSyntaxError as e:
                out.append(self.issue(ERROR, f'不是良构 XML：{e}', path, AUTO))
                continue
            if has_html_entities(data):
                out.append(self.issue(ERROR, '含 XML 未定义的 HTML 实体（如 &nbsp;）', path, AUTO))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            before = len(book.parse_notes)
            book.tree(i.file)                     # 解析时已做确定性修复/容错
            book.mark_dirty(i.file)
            note = book.parse_notes[before:] or [None]
            log.append(f'{i.file}：{note[0].message if note[0] else "重新序列化"}')
        return log


@register
class RootStructure(Rule):
    id, title, order = 'SEM-002', '根结构与 DOCTYPE', 31

    def check(self, book):
        out = []
        for path in book.content_docs():
            root = book.tree(path).getroot()
            if root.tag == 'html':
                out.append(self.issue(ERROR, 'html 未声明 XHTML 命名空间', path, AUTO, kind='xmlns'))
                continue
            if root.tag != X + 'html':
                out.append(self.issue(ERROR, f'根元素不是 XHTML 命名空间的 html：{root.tag}', path, MANUAL))
                continue
            if book.version.startswith('3'):
                head = book.files[path][:400].decode('utf-8', 'replace')
                m = re.search(r'<!DOCTYPE[^>]*>', head, re.I)
                if m and not re.fullmatch(r'<!DOCTYPE\s+html\s*>', m.group(0), re.I):
                    out.append(self.issue(WARNING, '旧式 DOCTYPE（应为 <!DOCTYPE html>）', path, AUTO))
            if root.find(X + 'head') is None:
                out.append(self.issue(ERROR, '缺少 head', path, AUTO, kind='head'))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            if i.data.get('kind') == 'xmlns':
                # 在原始字节里给 <html> 补默认命名空间后重新解析（所有无前缀元素随之进入 XHTML 命名空间）
                data = book.files[i.file]
                data = re.sub(rb'<html(?=[\s>/])', b'<html xmlns="http://www.w3.org/1999/xhtml"', data, count=1)
                book.set_bytes(i.file, data)
                book.tree(i.file)
                book.mark_dirty(i.file)
                log.append(f'{i.file}：补 XHTML 命名空间')
                continue
            root = book.tree(i.file).getroot()
            if i.data.get('kind') == 'head':
                root.insert(0, etree.Element(X + 'head'))
                log.append(f'{i.file}：补 head')
            book.mark_dirty(i.file)
            if not i.data.get('kind'):
                log.append(f'{i.file}：DOCTYPE 改为 <!DOCTYPE html>')
        return log


def _doc_title_candidate(book: Book, path: str) -> str:
    root = book.tree(path).getroot()
    for h in HEADINGS:
        el = body(root).find('.//' + h)
        if el is not None:
            t = ' '.join(text_of(el).split())
            if t:
                return t[:80]
    md = book.opf.find('opf:metadata/dc:title', NS)
    return (md.text or '').strip() if md is not None else ''


@register
class DocTitle(Rule):
    id, title, order = 'SEM-003', 'title 非空', 32

    def check(self, book):
        out = []
        for path in book.content_docs():
            root = book.tree(path).getroot()
            if root.tag != X + 'html' or root.find(X + 'head') is None:
                continue                  # 交给 SEM-002
            t = root.find(f'{X}head/{X}title')
            text = ' '.join((t.text or '').split()) if t is not None else ''
            if not text:
                out.append(self.issue(ERROR, '<title> 缺失或为空', path, AUTO))
            elif FILENAME_LIKE.search(text):
                cand = _doc_title_candidate(book, path)
                if cand and cand != text:
                    out.append(self.issue(WARNING, f'<title> 像文件名：{text}', path, AUTO))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            root = book.tree(i.file).getroot()
            head = root.find(X + 'head')
            t = head.find(X + 'title')
            if t is None:
                t = etree.Element(X + 'title')
                head.insert(0, t)
            t.text = _doc_title_candidate(book, i.file) or '正文'
            book.mark_dirty(i.file)
            log.append(f'{i.file}：title = {t.text}')
        return log


@register
class Ids(Rule):
    id, title, order = 'SEM-004', 'id 唯一且合法', 33

    def check(self, book):
        out = []
        for path in book.content_docs():
            root = book.tree(path).getroot()
            ids = [e.get('id') for e in root.iter() if isinstance(e.tag, str) and e.get('id') is not None]
            dup = [k for k, n in Counter(ids).items() if n > 1]
            bad = sorted({i for i in ids if not NCNAME.match(i)})
            if dup:
                out.append(self.issue(ERROR, f'重复 id {len(dup)} 个：{", ".join(dup[:3])}', path, AUTO, dup=dup))
            if bad:
                out.append(self.issue(ERROR, f'非法 id {len(bad)} 个（如 {bad[0]}）', path, AUTO, bad=bad))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            root = book.tree(i.file).getroot()
            existing = {e.get('id') for e in root.iter() if isinstance(e.tag, str) and e.get('id')}
            if 'bad' in i.data:
                mapping = {}
                for old in i.data['bad']:
                    base = re.sub(r'[^\w.\-\u00b7\u00c0-\uffff]', '_', old) or 'id'
                    if not re.match(r'[A-Za-z_\u00c0-\uffff]', base):
                        base = 'n' + base
                    new, k = base, 1
                    while new in existing:
                        k += 1
                        new = f'{base}-{k}'
                    existing.add(new)
                    mapping[old] = new
                n = rename_ids(book, i.file, mapping)
                log.append(f'{i.file}：重命名非法 id {len(mapping)} 个，同步引用 {n} 处')
            if 'dup' in i.data:
                seen, k = set(), 0
                for e in root.iter():
                    if not isinstance(e.tag, str) or e.get('id') is None:
                        continue
                    v = e.get('id')
                    if v in seen:
                        n, new = 2, f'{v}-2'
                        while new in existing:
                            n += 1
                            new = f'{v}-{n}'
                        e.set('id', new)
                        existing.add(new)
                        k += 1
                    seen.add(v)
                book.mark_dirty(i.file)
                log.append(f'{i.file}：重复 id 改名 {k} 个（链接仍指向第一个）')
        return log


# ---------- SEM-015：废弃的表现型标记 → CSS ----------

EMBEDDED = {X + t for t in ('img', 'video', 'canvas', 'iframe', 'embed', 'object', 'input')}
FONT_SIZES = {'1': 'x-small', '2': 'small', '3': 'medium', '4': 'large', '5': 'x-large', '6': 'xx-large',
              '7': 'xxx-large', '-2': 'smaller', '-1': 'smaller', '+1': 'larger', '+2': 'larger'}
LIST_TYPES = {'1': 'decimal', 'a': 'lower-alpha', 'A': 'upper-alpha', 'i': 'lower-roman', 'I': 'upper-roman',
              'disc': 'disc', 'circle': 'circle', 'square': 'square'}
OBSOLETE_ELEMENTS = {X + t: t for t in ('font', 'center', 'big', 'tt', 'strike', 'acronym')}
DATA_ATTR_OK = re.compile(r'^data-[a-z0-9_.\-\u00b7\u00c0-\uffff]+$')
LIST_TAGS = (X + 'ul', X + 'ol')


def _px(v: str) -> str:
    v = v.strip()
    return v + 'px' if re.fullmatch(r'\d+(\.\d+)?', v) else v


def _add_style(el, decl: str) -> None:
    cur = (el.get('style') or '').strip().rstrip(';')
    el.set('style', f'{cur}; {decl}' if cur else decl)


def _attr_to_css(el) -> list[str]:
    """把一个元素上的废弃属性转成 style，返回处理掉的属性名。"""
    done = []
    tag = el.tag
    for a in list(el.attrib):
        v = el.get(a)
        css = None
        if a == 'align':
            if tag in (X + 'img', X + 'table') and v.lower() in ('left', 'right'):
                css = f'float: {v.lower()}'
            elif tag == X + 'table' and v.lower() == 'center':
                css = 'margin-left: auto; margin-right: auto'
            elif v.lower() in ('left', 'right', 'center', 'justify'):
                css = f'text-align: {v.lower()}'
        elif a == 'valign':
            css = f'vertical-align: {v.lower()}'
        elif a == 'bgcolor':
            css = f'background-color: {v}'
        elif a in ('width', 'height'):
            if tag in EMBEDDED and re.fullmatch(r'\d+', v.strip()):
                continue                                   # 合法：嵌入元素的整数像素
            if tag in EMBEDDED and re.fullmatch(r'\d+px', v.strip()):
                el.set(a, v.strip()[:-2])
                done.append(a)
                continue
            css = f'{a}: {_px(v)}' if v.strip() else None
        elif a == 'cellspacing':
            css = f'border-spacing: {_px(v)}'
        elif a == 'cellpadding':
            css = None                                     # 需作用在 td 上，这里只删除（多为 0）
        elif a == 'border' and tag != X + 'table':
            css = f'border-width: {_px(v)}; border-style: solid' if v.strip() not in ('', '0') else None
        elif a == 'border' and tag == X + 'table':
            if v.strip() in ('', '1'):
                continue
            css = 'border: 1px solid' if v.strip() not in ('0',) else None
        elif a in ('hspace', 'vspace'):
            m = _px(v)
            css = f'margin-left: {m}; margin-right: {m}' if a == 'hspace' else f'margin-top: {m}; margin-bottom: {m}'
        elif a == 'clear' and tag == X + 'br':
            css = f'clear: {"both" if v.lower() == "all" else v.lower()}'
        elif a == 'nowrap':
            css = 'white-space: nowrap'
        elif a == 'type' and tag in (X + 'ul', X + 'li'):
            css = f'list-style-type: {LIST_TYPES.get(v, LIST_TYPES.get(v.lower(), "disc"))}'
        elif a == 'background':
            css = f'background-image: url({v})'
        elif a == 'name' and tag == X + 'a':
            if not el.get('id'):
                el.set('id', v)
        elif a == 'charset' and tag in (X + 'a', X + 'link', X + 'script'):
            pass
        elif a == 'language' and tag == X + 'script':
            pass
        else:
            continue
        del el.attrib[a]
        if css:
            _add_style(el, css)
        done.append(a)
    return done


def _fix_obsolete_element(el) -> str:
    name = OBSOLETE_ELEMENTS[el.tag]
    styles = []
    if name == 'font':
        if el.get('color'):
            styles.append(f'color: {el.get("color")}')
        if el.get('face'):
            styles.append(f'font-family: {el.get("face")}')
        if el.get('size') and el.get('size').strip() in FONT_SIZES:
            styles.append(f'font-size: {FONT_SIZES[el.get("size").strip()]}')
        for a in ('color', 'face', 'size'):
            el.attrib.pop(a, None)
        el.tag = X + 'span'
    elif name == 'center':
        el.tag = X + 'div'
        styles.append('text-align: center')
    elif name == 'big':
        el.tag = X + 'span'
        styles.append('font-size: larger')
    elif name == 'tt':
        el.tag = X + 'span'
        styles.append('font-family: monospace')
    elif name == 'strike':
        el.tag = X + 's'
    elif name == 'acronym':
        el.tag = X + 'abbr'
    if styles:
        _add_style(el, '; '.join(styles))
    if el.tag == X + 'span' and not el.attrib:
        _unwrap(el)
    return name


def _unwrap(el) -> None:
    parent = el.getparent()
    idx = parent.index(el)
    prev = el.getprevious()
    if el.text:
        if prev is not None:
            prev.tail = (prev.tail or '') + el.text
        else:
            parent.text = (parent.text or '') + el.text
    kids = list(el)
    for k, ch in enumerate(kids):
        parent.insert(idx + k, ch)
    if el.tail:
        last = kids[-1] if kids else el.getprevious()
        if last is not None and last is not el:
            last.tail = (last.tail or '') + el.tail
        else:
            parent.text = (parent.text or '') + el.tail
    parent.remove(el)


def _fix_list_children(lst) -> int:
    """ul/ol 的直接子元素只能是 li：把嵌套列表并入前一个 li，其他元素包进新 li。"""
    n = 0
    for ch in list(lst):
        if not isinstance(ch.tag, str) or ch.tag in (X + 'li', X + 'script', X + 'template'):
            continue
        prev = ch.getprevious()
        if ch.tag in LIST_TAGS and prev is not None and prev.tag == X + 'li':
            prev.append(ch)
        else:
            li = etree.Element(X + 'li')
            lst.replace(ch, li)
            li.append(ch)
            if ch.tag in LIST_TAGS:
                li.set('style', 'list-style-type: none')
        n += 1
    return n


def _fix_table_order(table) -> int:
    """thead 只能有一个，且在 tbody/tr 之前；多余的 thead 改为 tbody（单元格仍是 th）。"""
    theads = table.findall(X + 'thead')
    if not theads:
        return 0
    n = 0
    for extra in theads[1:]:
        extra.tag = X + 'tbody'
        n += 1
    thead = theads[0]
    first_body = next((c for c in table if c.tag in (X + 'tbody', X + 'tr')), None)
    if first_body is not None and table.index(thead) > table.index(first_body):
        table.remove(thead)
        table.insert(table.index(first_body), thead)
        n += 1
    return n


@register
class ObsoleteMarkup(Rule):
    id, title, order = 'SEM-015', '废弃的表现型标记', 34

    def _scan(self, root) -> Counter:
        c = Counter()
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            if el.tag in OBSOLETE_ELEMENTS:
                c[f'<{OBSOLETE_ELEMENTS[el.tag]}>'] += 1
            for a in el.attrib:
                if a.startswith('data-') and not DATA_ATTR_OK.match(a):
                    c['非法 data-* 属性'] += 1
            if el.tag == X + 'meta' and el.get('http-equiv'):
                c['meta http-equiv'] += 1
            if el.tag in LIST_TAGS and any(isinstance(ch.tag, str) and ch.tag not in (X + 'li', X + 'script', X + 'template')
                                            for ch in el):
                c['列表直接子元素非 li'] += 1
            if el.tag == X + 'table':
                ths = el.findall(X + 'thead')
                th = ths[0] if ths else None
                fb = next((ch for ch in el if ch.tag in (X + 'tbody', X + 'tr')), None)
                if len(ths) > 1 or th is not None and fb is not None and el.index(th) > el.index(fb):
                    c['thead 位置错误'] += 1
        for el in root.iter():
            if isinstance(el.tag, str):
                probe = etree.Element(el.tag, dict(el.attrib))
                for a in _attr_to_css(probe):
                    c[f'@{a}'] += 1
        return c

    def check(self, book):
        if not book.version.startswith('3'):
            return []
        out = []
        for path in book.content_docs():
            root = book.tree(path).getroot()
            if root.tag != X + 'html':
                continue
            c = self._scan(root)
            if c:
                desc = '、'.join(f'{k}×{n}' for k, n in c.most_common(6))
                out.append(self.issue(ERROR, f'HTML5 中已废弃/非法的标记：{desc}', path, AUTO))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            root = book.tree(i.file).getroot()
            c = Counter()
            for el in list(root.iter()):
                if not isinstance(el.tag, str):
                    continue
                for a in _attr_to_css(el):
                    c[f'@{a}'] += 1
                for a in list(el.attrib):
                    if a.startswith('data-') and not DATA_ATTR_OK.match(a):
                        v = el.attrib.pop(a)
                        low = a.lower()
                        if DATA_ATTR_OK.match(low) and low not in el.attrib:
                            el.set(low, v)
                        c['data-*'] += 1
                if el.tag == X + 'meta' and el.get('http-equiv'):
                    el.getparent().remove(el)      # 编码由 XML 声明给出；其余 http-equiv 对电子书无意义
                    c['meta http-equiv'] += 1
            for el in [e for e in root.iter() if isinstance(e.tag, str) and e.tag in OBSOLETE_ELEMENTS]:
                c[f'<{_fix_obsolete_element(el)}>'] += 1
            for lst in [e for e in root.iter(*LIST_TAGS)]:
                k = _fix_list_children(lst)
                if k:
                    c['列表嵌套'] += k
            for t in root.iter(X + 'table'):
                if _fix_table_order(t):
                    c['thead 位置'] += 1
            book.mark_dirty(i.file)
            log.append(f'{i.file}：' + '、'.join(f'{k}×{n}' for k, n in c.most_common()))
        return log
