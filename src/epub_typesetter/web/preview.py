"""实时预览：直接把 EPUB 包里的文件按原路径交给浏览器，章节在网页的预览框里像阅读器一样渲染。

    /api/books/{id}/view/{which}/{包内路径}   which = original、fixed、vN
    /api/books/{id}/spine/{which}            章节列表（spine 顺序，带标题）

书里的脚本一律不执行：响应头带 CSP（script-src 'none'），预览框本身也是不允许脚本的 sandbox。
"""
from __future__ import annotations

import mimetypes
import os
import posixpath
import re
import threading
import zipfile
from functools import lru_cache

from ..book import NS, XHTML_TYPES, Book
from . import store

_lock = threading.Lock()
MIME = {'.xhtml': 'application/xhtml+xml', '.html': 'application/xhtml+xml', '.htm': 'application/xhtml+xml',
        '.css': 'text/css', '.svg': 'image/svg+xml', '.otf': 'font/otf', '.ttf': 'font/ttf', '.woff': 'font/woff',
        '.woff2': 'font/woff2', '.ncx': 'application/xml', '.opf': 'application/xml'}
CSP = "default-src 'self' data: blob:; script-src 'none'; object-src 'none'; style-src 'self' 'unsafe-inline' data:"


def epub_path(pid: str, which: str) -> str | None:
    if which in ('original', 'fixed'):
        p = store.path(pid, f'{which}.epub')
    elif re.fullmatch(r'v\d{1,6}', which):
        p = os.path.join(store.path(pid, 'versions'), f'{which}.epub')
    else:
        return None
    return p if os.path.exists(p) else None


@lru_cache(maxsize=8)
def _zip(path: str, mtime: float) -> zipfile.ZipFile:
    return zipfile.ZipFile(path)


def read(pid: str, which: str, inner: str) -> tuple[bytes, str] | None:
    """项目某个版本的包内文件 → (内容, MIME)。路径不规范或不存在时返回 None。"""
    return read_file(epub_path(pid, which), inner)


def read_file(p: str | None, inner: str) -> tuple[bytes, str] | None:
    """EPUB 文件 p 的包内文件 → (内容, MIME)；项目预览和独立阅读器共用。"""
    inner = posixpath.normpath(inner).lstrip('/')
    if p is None or inner.startswith('..') or inner in ('.', ''):
        return None
    with _lock:
        z = _zip(p, os.path.getmtime(p))
        try:
            data = z.read(inner)
        except KeyError:
            return None
    ext = posixpath.splitext(inner)[1].lower()
    return data, MIME.get(ext) or mimetypes.guess_type(inner)[0] or 'application/octet-stream'


def _title_of(book: Book, path: str) -> str:
    try:
        root = book.tree(path).getroot()
    except Exception:
        return ''
    from ..rebuild import _nav_label            # 与目录同一套取法：<br/> 处补空格，纯图片标题取 alt
    x = '{%s}' % NS['xhtml']
    for tag in ('h1', 'h2', 'h3', 'h4'):
        h = root.find(f'.//{x}body//{x}{tag}')
        label = _nav_label(h) if h is not None else ''
        if label:
            return re.sub(r'\s+', ' ', label).strip()[:40]
    t = root.find(f'{x}head/{x}title')
    return (t.text or '').strip()[:40] if t is not None else ''


@lru_cache(maxsize=16)
def _spine(path: str, mtime: float) -> list[dict]:
    book = Book.load(path)
    out = []
    for it in book.spine_items():
        if it.media_type not in XHTML_TYPES or it.path not in book.files:
            continue
        title = _title_of(book, it.path)
        if not title and 'cover' in it.path.lower():
            title = '封面'
        out.append({'path': it.path, 'title': title or posixpath.basename(it.path)})
    return out


def spine(pid: str, which: str) -> list[dict] | None:
    return spine_file(epub_path(pid, which))


def spine_file(p: str | None) -> list[dict] | None:
    if p is None:
        return None
    return _spine(p, os.path.getmtime(p))

