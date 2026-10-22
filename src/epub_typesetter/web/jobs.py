"""后台任务：体检与修复（epubcheck 一本书要几秒到几十秒，不能阻塞请求）。"""
from __future__ import annotations

import os
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .. import engine, epubcheck
from ..book import NS, Book, EpubError
from ..textcheck import compare_text
from . import store

EPUBCHECK_LOCALE = os.environ.get('EPUBTS_EPUBCHECK_LOCALE', 'zh-TW')
MAX_MESSAGES = 300
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get('EPUBTS_WORKERS', '2')))


def submit(fn, pid: str) -> None:
    _pool.submit(_guard, fn, pid)


def _guard(fn, pid):
    try:
        fn(pid)
    except EpubError as e:
        store.update(pid, status='error', message=f'无法作为 EPUB 读取：{e}')
    except Exception as e:  # noqa: BLE001  后台任务必须把错误落到状态里，否则前端会一直转圈
        traceback.print_exc()
        store.update(pid, status='error', message=f'处理失败：{type(e).__name__}: {e}')


def _book_info(book: Book) -> dict:
    md = book.opf.find('opf:metadata', NS)

    def first(tag):
        el = md.find(tag, NS) if md is not None else None
        return ' '.join((el.text or '').split()) if el is not None else ''
    return {'title': first('dc:title'), 'author': first('dc:creator'), 'version': book.version,
            'language': first('dc:language'), 'files': len(book.files), 'documents': len(book.content_docs())}


def _epubcheck_report(msgs) -> dict:
    if msgs is None:
        return {'available': False}
    items = [{'id': m.id, 'severity': m.severity, 'message': m.message, 'count': max(1, len(m.locations)),
              'locations': m.locations[:5]} for m in msgs]
    order = {'FATAL': 0, 'ERROR': 1, 'WARNING': 2, 'USAGE': 3, 'INFO': 4}
    items.sort(key=lambda m: (order.get(m['severity'], 9), -m['count']))
    return {'available': True, **epubcheck.summarize(msgs), 'blocking': epubcheck.blocking(msgs),
            'messages': items[:MAX_MESSAGES]}


def _issues_report(issues) -> dict:
    by_rule = Counter((i.rule_id, i.severity) for i in issues)
    return {'total': len(issues),
            'by_severity': dict(Counter(i.severity for i in issues)),
            'by_rule': [{'rule': r, 'severity': s, 'count': n} for (r, s), n in sorted(by_rule.items())],
            'items': [i.to_dict() for i in issues]}


def audit(pid: str) -> None:
    store.update(pid, status='auditing', message='')
    book = Book.load(store.path(pid, 'original.epub'))
    info = _book_info(book)
    issues = engine.audit(book)
    store.update(pid, title=info['title'], author=info['author'], version=info['version'])
    msgs = epubcheck.run(store.path(pid, 'original.epub'), locale=EPUBCHECK_LOCALE)
    store.write_json(pid, 'audit.json', {'book': info, 'issues': _issues_report(issues),
                                         'parse_notes': [n.message for n in book.parse_notes][:50],
                                         'epubcheck': _epubcheck_report(msgs)})
    store.update(pid, status='ready')


def fix(pid: str) -> None:
    store.update(pid, status='fixing', message='')
    original = open(store.path(pid, 'original.epub'), 'rb').read()
    book = Book.load(original)
    rep = engine.fix(book)
    out = book.to_bytes()
    tmp = store.path(pid, 'fixed.epub.tmp')
    with open(tmp, 'wb') as f:
        f.write(out)
    os.replace(tmp, store.path(pid, 'fixed.epub'))
    diff = compare_text(Book.load(original), Book.load(out))
    msgs = epubcheck.run(store.path(pid, 'fixed.epub'), locale=EPUBCHECK_LOCALE)
    store.write_json(pid, 'fix.json', {
        'changes': [{'rule': r, 'text': t} for r, t in rep.changes],
        'before': _issues_report(rep.before),
        'after': _issues_report(rep.after),
        'text': {'equal': diff.equal, 'length': diff.length, 'summary': diff.summary(),
                 'changes': [{'file': f, 'op': op, 'before': a[:80], 'after': b[:80]}
                             for f, op, a, b in diff.changes[:50]]},
        'epubcheck': _epubcheck_report(msgs),
        'size': len(out),
    })
    store.update(pid, status='fixed')


def is_epub_like(data: bytes) -> bool:
    return data[:2] == b'PK'

