"""跨文件操作的公共工具：引用图、文件改名、id 改名（同步全书引用）。"""
from __future__ import annotations

import posixpath
import re
from urllib.parse import unquote

from lxml import etree

from .book import NS, XHTML_TYPES, Book

X = '{%s}' % NS['xhtml']
EPUB_TYPE = '{%s}type' % NS['epub']
XLINK_HREF = '{%s}href' % NS['xlink']
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'

HAN = r'\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f'  # CJK 统一表意文字（基本区+扩展区+兼容区）

BLOCK_TAGS = {X + t for t in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'dt', 'dd',
                              'td', 'th', 'figcaption', 'caption', 'blockquote', 'div')}
HEADINGS = [X + f'h{i}' for i in range(1, 7)]
RAW_TEXT_TAGS = {X + 'pre', X + 'code', X + 'script', X + 'style', X + 'kbd', X + 'samp'}

# 会引用包内资源的属性（元素名不限，按属性名判断）
REF_ATTRS = ('href', 'src', XLINK_HREF, 'poster', 'data')
CSS_URL = re.compile(r'''url\(\s*(['"]?)([^'")]+)\1\s*\)''')
CSS_IMPORT = re.compile(r'''@import\s+(['"])([^'"]+)\1''')


def is_external(href: str) -> bool:
    return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', href)) or href.startswith('//')


def body(root: etree._Element) -> etree._Element:
    b = root.find(X + 'body')
    return b if b is not None else root


def text_of(el: etree._Element) -> str:
    return ''.join(el.itertext())


_SRC_WS = re.compile(r'[ \t\r\n\f\v]+')


def squash(s: str) -> str:
    """合并源码里的空白（半角空格、制表、换行）并去首尾。不动全角空格：
    章号与章名之间的全角空格是规范要求的内容（04 §4.3），str.split() 会把它误当空白吃掉。"""
    return _SRC_WS.sub(' ', s or '').strip(' \t\r\n\f\v')


def is_xhtml_doc(book: Book, path: str) -> bool:
    it = book.item_by_path(path)
    return it is not None and it.media_type in XHTML_TYPES


def css_paths(book: Book) -> list[str]:
    return [i.path for i in book.manifest() if i.media_type == 'text/css' and i.path in book.files]


# ---------- 引用图 ----------

def references(book: Book) -> dict[str, set[str]]:
    """被引用文件 → 引用它的文件集合（内容文档、CSS、NCX、OPF guide）。"""
    refs: dict[str, set[str]] = {}

    def add(src: str, href: str):
        if not href or is_external(href) or href.startswith('#'):
            return
        refs.setdefault(Book.resolve(src, href), set()).add(src)

    for path in book.files:
        low = path.lower()
        if low.endswith(('.xhtml', '.html', '.htm', '.svg', '.ncx')):
            try:
                root = book.tree(path).getroot()
            except Exception:
                continue
            for el in root.iter():
                if not isinstance(el.tag, str):
                    continue
                for a in REF_ATTRS:
                    v = el.get(a)
                    if v:
                        add(path, v)
                st = el.get('style')
                if st:
                    for m in CSS_URL.finditer(st):
                        add(path, m.group(2))
                if el.tag == X + 'style' and el.text:
                    for m in CSS_URL.finditer(el.text):
                        add(path, m.group(2))
        elif low.endswith('.css'):
            css = book.files[path].decode('utf-8', 'replace')
            for m in list(CSS_URL.finditer(css)) + list(CSS_IMPORT.finditer(css)):
                add(path, m.group(2))
    for ref in book.opf.iterfind('opf:guide/opf:reference', NS):
        add(book.opf_path, ref.get('href', ''))
    return refs


# ---------- 改写引用 ----------

def _rewrite_href(src: str, href: str, fn) -> str | None:
    """对 src 文件中的一个 href 调用 fn(target_path, fragment) → (new_path, new_fragment) 或 None。"""
    if not href or is_external(href):
        return None
    path_part, _, frag = href.partition('#')
    target = Book.resolve(src, href) if path_part else src
    res = fn(target, unquote(frag) if frag else '')
    if res is None:
        return None
    new_target, new_frag = res
    new = '' if (not path_part and new_target == src) else Book.relative(src, new_target)
    if new_frag:
        new += '#' + new_frag
    return new if new != href else None


def rewrite_references(book: Book, fn) -> int:
    """遍历全书所有引用，用 fn 改写；返回改动数。fn 签名见 _rewrite_href。"""
    changed = 0
    for path in list(book.files):
        low = path.lower()
        if low.endswith(('.xhtml', '.html', '.htm', '.svg', '.ncx')):
            try:
                root = book.tree(path).getroot()
            except Exception:
                continue
            dirty = False
            for el in root.iter():
                if not isinstance(el.tag, str):
                    continue
                for a in REF_ATTRS:
                    v = el.get(a)
                    if v:
                        new = _rewrite_href(path, v, fn)
                        if new is not None:
                            el.set(a, new)
                            dirty = True
                            changed += 1
            if dirty:
                book.mark_dirty(path)
        elif low.endswith('.css'):
            css = book.files[path].decode('utf-8', 'replace')

            def sub(m, _path=path):
                nonlocal changed
                new = _rewrite_href(_path, m.group(2), fn)
                if new is None:
                    return m.group(0)
                changed += 1
                return f'url({m.group(1)}{new}{m.group(1)})'
            new_css = CSS_URL.sub(sub, css)
            if new_css != css:
                book.set_bytes(path, new_css.encode('utf-8'))
    for ref in book.opf.iterfind('opf:guide/opf:reference', NS):
        new = _rewrite_href(book.opf_path, ref.get('href', ''), fn)
        if new is not None:
            ref.set('href', new)
            book.mark_dirty(book.opf_path)
            changed += 1
    return changed


def rename_file(book: Book, old: str, new: str) -> None:
    """改名包内文件，并同步 manifest 与全书引用。"""
    assert new not in book.files, new
    rewrite_references(book, lambda t, f: (new, f) if t == old else None)
    book.files[new] = book.files.pop(old)
    if old in book._trees:
        book._trees[new] = book._trees.pop(old)
    if old in book._dirty:
        book._dirty.discard(old)
        book._dirty.add(new)
    it = book.item_by_path(old)
    if it is not None:
        it.element.set('href', Book.relative(book.opf_path, new))
        book.mark_dirty(book.opf_path)


def unique_path(book: Book, path: str) -> str:
    stem, ext = posixpath.splitext(path)
    cand, n = path, 1
    lower = {p.lower() for p in book.files}
    while cand.lower() in lower:
        n += 1
        cand = f'{stem}-{n}{ext}'
    return cand


def rename_ids(book: Book, doc: str, mapping: dict[str, str]) -> int:
    """改名 doc 内的 id，并同步全书指向 doc#旧id 的链接。返回改写的引用数。"""
    if not mapping:
        return 0
    root = book.tree(doc).getroot()
    for el in root.iter():
        if isinstance(el.tag, str) and el.get('id') in mapping:
            el.set('id', mapping[el.get('id')])
    book.mark_dirty(doc)
    return rewrite_references(book, lambda t, f: (t, mapping[f]) if t == doc and f in mapping else None)
