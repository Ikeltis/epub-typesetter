"""独立阅读器：直接打开任意一本 EPUB 来看，不建项目、不体检、不修改。

文件存在 <数据目录>/reader/<id>.epub，id 是内容 SHA-256 的前 12 位（同一本书只存一份，再打开就是同一个 id），
旁边 <id>.json 记原文件名、大小、最近打开时间。章节列表和包内文件的读取与项目预览共用 preview.py。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import zipfile
import io

from . import store

ID_RE = re.compile(r'^[0-9a-f]{12}$')


class NotEpub(ValueError):
    pass


def _dir() -> str:
    d = os.path.join(store.root(), 'reader')
    os.makedirs(d, exist_ok=True)
    return d


def epub_path(rid: str) -> str | None:
    if not ID_RE.match(rid):
        return None
    p = os.path.join(_dir(), f'{rid}.epub')
    return p if os.path.exists(p) else None


def _check(data: bytes) -> None:
    """只收 EPUB：是 ZIP，且 container.xml 指得到一个 OPF。"""
    if data[:2] != b'PK':
        raise NotEpub('不是 EPUB 文件（EPUB 是 ZIP 包）')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        container = z.read('META-INF/container.xml').decode('utf-8', 'replace')
    except (zipfile.BadZipFile, KeyError):
        raise NotEpub('不是 EPUB 文件：缺少 META-INF/container.xml') from None
    m = re.search(r'full-path="([^"]+)"', container)
    if not m or m.group(1) not in z.namelist():
        raise NotEpub('不是有效的 EPUB：container.xml 指向的 OPF 不存在')


def add(filename: str, data: bytes) -> dict:
    _check(data)
    rid = hashlib.sha256(data).hexdigest()[:12]
    p = os.path.join(_dir(), f'{rid}.epub')
    if not os.path.exists(p):
        tmp = p + '.part'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, p)
    name = re.sub(r'[\x00-\x1f/\\]', '_', os.path.basename(filename or 'book.epub'))[:200]
    meta = {'id': rid, 'filename': name, 'size': len(data), 'opened': time.time()}
    with open(os.path.join(_dir(), f'{rid}.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    return meta


def touch(rid: str) -> None:
    """记一下最近打开时间：列表按它排序。"""
    mp = os.path.join(_dir(), f'{rid}.json')
    try:
        with open(mp, encoding='utf-8') as f:
            meta = json.load(f)
        meta['opened'] = time.time()
        with open(mp, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)
    except (OSError, ValueError):
        pass


def list_all() -> list[dict]:
    out = []
    for name in os.listdir(_dir()):
        rid = name[:-5]
        if name.endswith('.json') and ID_RE.match(rid) and epub_path(rid):
            try:
                with open(os.path.join(_dir(), name), encoding='utf-8') as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda m: m.get('opened', 0), reverse=True)


def delete(rid: str) -> bool:
    p = epub_path(rid)
    if p is None:
        return False
    os.remove(p)
    try:
        os.remove(os.path.join(_dir(), f'{rid}.json'))
    except OSError:
        pass
    return True
