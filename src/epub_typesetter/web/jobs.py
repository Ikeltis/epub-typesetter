"""后台任务：体检与修复（epubcheck 一本书要几秒到几十秒，不能阻塞请求）。"""
from __future__ import annotations

import os
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .. import engine, epubcheck
from ..book import NS, Book, EpubError
from ..pipeline import optimize
from ..rebuild import REMOVED_ROLES
from ..textcheck import compare_blocks, compare_text
from . import store

EPUBCHECK_LOCALE = os.environ.get('EPUBTS_EPUBCHECK_LOCALE', 'zh-TW')
MAX_MESSAGES = 300
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get('EPUBTS_WORKERS', '2')))


def submit(fn, pid: str, *args) -> None:
    _pool.submit(_guard, fn, pid, *args)


def _guard(fn, pid, *args):
    try:
        fn(pid, *args)
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


ROLE_NAMES = {'h1': '一级标题', 'h2': '二级标题', 'h3': '三级标题', 'para': '正文段落', 'figure': '插图',
              'caption': '图注', 'source': '资料来源', 'bullet': '列表项', 'note': '注释', 'note-head': '注释小标题',
              'toc': '书内目录页', 'junk': '广告/引流', 'meta': '版权信息', 'quote': '引文', 'right': '右对齐短行',
              'center': '居中短行', 'keep': '表格等原样保留'}


def fix(pid: str, mode: str = 'basic') -> None:
    """mode='basic'：只做规范修复（M0，不改版面）；mode='rebuild'：语义分析+排版重建（M2）。"""
    store.update(pid, status='fixing', message='')
    original = open(store.path(pid, 'original.epub'), 'rb').read()
    book = Book.load(original)
    result = {'mode': mode}
    if mode == 'rebuild':
        orep = optimize(book)
        rep = engine.FixReport(orep.fix.changes + orep.refix.changes, orep.fix.before, orep.refix.after)
        out = book.to_bytes()
        bc = compare_blocks(orep.analysis.blocks, REMOVED_ROLES, Book.load(out))
        result['text'] = {'equal': bc.ok, 'length': bc.chars_before, 'summary': bc.summary(),
                          'changes': [{'file': '', 'op': role, 'before': t[:80], 'after': ''}
                                      for role, t in bc.missing[:50]]}
        counts = orep.analysis.counts()
        result['rebuild'] = {
            'roles': [{'role': r, 'name': ROLE_NAMES.get(r, r), 'count': n} for r, n in counts.most_common()],
            'files': len(orep.rebuild.chapters), 'notes': orep.rebuild.notes,
            'vertical': orep.analysis.vertical,
            'removed': [{'role': r, 'name': ROLE_NAMES.get(r, r), 'text': t[:120]} for r, t in orep.rebuild.removed[:300]],
            'removed_total': len(orep.rebuild.removed),
        }
    else:
        rep = engine.fix(book)
        out = book.to_bytes()
        diff = compare_text(Book.load(original), Book.load(out))
        result['text'] = {'equal': diff.equal, 'length': diff.length, 'summary': diff.summary(),
                          'changes': [{'file': f, 'op': op, 'before': a[:80], 'after': b[:80]}
                                      for f, op, a, b in diff.changes[:50]]}
    tmp = store.path(pid, 'fixed.epub.tmp')
    with open(tmp, 'wb') as f:
        f.write(out)
    os.replace(tmp, store.path(pid, 'fixed.epub'))
    msgs = epubcheck.run(store.path(pid, 'fixed.epub'), locale=EPUBCHECK_LOCALE)
    result.update({
        'changes': [{'rule': r, 'text': t} for r, t in rep.changes],
        'before': _issues_report(rep.before),
        'after': _issues_report(rep.after),
        'epubcheck': _epubcheck_report(msgs),
        'size': len(out),
    })
    store.write_json(pid, 'fix.json', result)
    store.update(pid, status='fixed')


def is_epub_like(data: bytes) -> bool:
    return data[:2] == b'PK'

