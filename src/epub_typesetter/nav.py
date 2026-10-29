"""导航文档（nav.xhtml）的生成（guide/01 §导航、guide/07 STR-008/STR-010）。"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from .book import NS, Book
from .xhtml import HEADINGS, X, body, squash, text_of

NCX = '{%s}' % NS['ncx']


@dataclass
class Entry:
    depth: int          # 1 起
    label: str
    path: str           # 目标 zip 内路径
    fragment: str = ''


def ncx_path(book: Book) -> str | None:
    spine = book.opf.find('opf:spine', NS)
    toc_id = spine.get('toc') if spine is not None else None
    it = book.item_by_id(toc_id) if toc_id else None
    if it is None:
        it = next((i for i in book.manifest() if i.media_type == 'application/x-dtbncx+xml'), None)
    return it.path if it is not None and it.path in book.files else None


def entries_from_ncx(book: Book) -> list[Entry]:
    p = ncx_path(book)
    if not p:
        return []
    root = book.tree(p).getroot()
    nav_map = root.find(NCX + 'navMap')
    out: list[Entry] = []

    def walk(parent, depth):
        for np_ in parent.findall(NCX + 'navPoint'):
            label_el = np_.find(f'{NCX}navLabel/{NCX}text')
            label = squash(label_el.text or '') if label_el is not None else ''
            content = np_.find(NCX + 'content')
            src = content.get('src', '') if content is not None else ''
            if src:
                path = Book.resolve(p, src)
                frag = src.partition('#')[2]
                if path in book.files and label:
                    out.append(Entry(depth, label, path, frag))
            walk(np_, depth + 1)
    if nav_map is not None:
        walk(nav_map, 1)
    return out


def entries_from_headings(book: Book, max_level: int = 3) -> list[Entry]:
    """按 spine 顺序收集 h1..h{max_level}；没有 id 的标题补稳定 id（sec-序号）。"""
    out: list[Entry] = []
    n = 0
    for it in book.spine_items():
        if it.media_type != 'application/xhtml+xml' or it.path not in book.files:
            continue
        root = book.tree(it.path).getroot()
        ids = {e.get('id') for e in root.iter() if isinstance(e.tag, str) and e.get('id')}
        for el in body(root).iter(*HEADINGS[:max_level]):
            label = squash(text_of(el))
            if not label:
                continue
            first_in_doc = not any(e.depth for e in out if e.path == it.path)
            if first_in_doc:
                frag = ''
            else:
                if not el.get('id'):
                    n += 1
                    while f'sec-{n}' in ids:
                        n += 1
                    el.set('id', f'sec-{n}')
                    ids.add(f'sec-{n}')
                    book.mark_dirty(it.path)
                frag = el.get('id')
            out.append(Entry(int(el.tag[-1]), label, it.path, frag))
    # 归一化层级：最浅的标题记为 1，且不跳级
    if out:
        base = min(e.depth for e in out)
        prev = 0
        for e in out:
            e.depth = min(e.depth - base + 1, prev + 1)
            prev = e.depth
    return out


def _ol(entries: list[Entry], nav_path: str) -> str:
    lines = []
    stack = 0
    for i, e in enumerate(entries):
        d = max(1, min(e.depth, stack + 1))
        if d > stack:
            lines.append('<ol>' * (d - stack))
        else:
            lines.append('</li>' + '</ol></li>' * (stack - d))
        stack = d
        href = Book.relative(nav_path, e.path) + (f'#{e.fragment}' if e.fragment else '')
        lines.append(f'<li><a href={quoteattr(href)}>{escape(e.label)}</a>')
    lines.append('</li>' + '</ol></li>' * (stack - 1) + '</ol>' if stack else '<ol><li><span>（无目录）</span></li></ol>')
    return ''.join(lines)      # 不在 li 内留换行：否则空白规则（TXT-002）会在下一轮再改一次


def build_nav(book: Book, nav_path: str, entries: list[Entry],
              landmarks: list[tuple[str, str, str]], lang: str, title: str = '目录') -> bytes:
    """landmarks: [(epub:type, 标签, 目标 path#frag)]。"""
    lm = ''
    if landmarks:
        items = '\n'.join(
            f'<li><a epub:type="{t}" href={quoteattr(Book.relative(nav_path, p.partition("#")[0]) + ("#" + p.partition("#")[2] if p.partition("#")[2] else ""))}>{escape(lbl)}</a></li>'
            for t, lbl, p in landmarks)
        lm = f'\n<nav epub:type="landmarks" id="landmarks" hidden="">\n<h2>导航</h2>\n<ol>\n{items}\n</ol>\n</nav>'
    lang_attr = quoteattr(lang or 'zh')
    doc = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang={lang_attr} xml:lang={lang_attr}>
<head>
<meta charset="utf-8"/>
<title>{escape(title)}</title>
</head>
<body>
<nav epub:type="toc" id="toc" role="doc-toc">
<h1>{escape(title)}</h1>
{_ol(entries, nav_path)}
</nav>{lm}
</body>
</html>
'''
    return doc.encode('utf-8')


def default_nav_path(book: Book) -> str:
    base = posixpath.join(book.opf_dir, 'nav.xhtml') if book.opf_dir else 'nav.xhtml'
    cand, n = base, 1
    while cand in book.files:
        n += 1
        cand = base.replace('nav.xhtml', f'nav-{n}.xhtml')
    return cand
