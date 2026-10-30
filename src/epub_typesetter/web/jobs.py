"""后台任务：体检与修复（epubcheck 一本书要几秒到几十秒，不能阻塞请求）。"""
from __future__ import annotations

import os
import traceback
from concurrent.futures import ThreadPoolExecutor

from .. import engine, epubcheck, report
from ..book import NS, Book, EpubError
from ..pipeline import optimize
from ..rebuild import REMOVED_ROLES
from ..textcheck import compare_blocks, compare_text
from ..waivers import WaiverFileError, WaiverSet
from . import store

EPUBCHECK_LOCALE = os.environ.get('EPUBTS_EPUBCHECK_LOCALE', 'zh-TW')
MAX_MESSAGES = 300
BUSY = ('queued', 'auditing', 'fixing')
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


MAX_HITS = 50       # 网页每条问题最多带的命中数（完整列表用命令行看）


def load_waivers(pid: str, renames: bool = False) -> WaiverSet:
    """读取本书的豁免；格式坏了不让整个页面报错，按「无豁免 + 一条 STR-024」处理。"""
    try:
        ws = WaiverSet.load(store.path(pid, 'waivers.json'))
    except WaiverFileError as e:
        ws = WaiverSet(problems=[('error', str(e), {})])
    if renames:
        ws.renames = store.read_json(pid, 'fixed.renames.json') or {}
    return ws


def _issues_report(issues, book=None, ws=None, skipped=None) -> dict:
    rep = report.build(issues, book, ws, skipped=skipped)
    for d in rep['issues']:
        if len(d['hits']) > MAX_HITS:
            d['hits_truncated'] = len(d['hits']) - MAX_HITS
            d['hits'] = d['hits'][:MAX_HITS]
    rep['total'] = sum(rep['summary'][k] for k in ('error', 'warning', 'info'))
    return rep


def _original_issues(pid: str, book: Book | None = None) -> dict:
    """原书的问题报告。已有输出时，豁免多半是对着输出写的，原书上不报「未命中」。"""
    book = book or Book.load(store.path(pid, 'original.epub'))
    ws = load_waivers(pid)
    issues = engine.audit(book, waivers=ws, self_check=not os.path.exists(store.path(pid, 'fixed.epub')))
    return _issues_report(issues, book, ws)


def audit(pid: str) -> None:
    store.update(pid, status='auditing', message='')
    book = Book.load(store.path(pid, 'original.epub'))
    info = _book_info(book)
    store.update(pid, title=info['title'], author=info['author'], version=info['version'])
    issues = _original_issues(pid, book)
    msgs = epubcheck.run(store.path(pid, 'original.epub'), locale=EPUBCHECK_LOCALE)
    store.write_json(pid, 'audit.json', {'book': info, 'issues': issues,
                                         'parse_notes': [n.message for n in book.parse_notes][:50],
                                         'epubcheck': _epubcheck_report(msgs)})
    store.update(pid, status='ready')


def rescore(pid: str) -> None:
    """豁免变更后只重算本工具的问题报告（不重跑 epubcheck、不重新修复），几秒内完成。"""
    a = store.read_json(pid, 'audit.json')
    if a is not None:
        a['issues'] = _original_issues(pid)
        store.write_json(pid, 'audit.json', a)
    f = store.read_json(pid, 'fix.json')
    if f is not None and os.path.exists(store.path(pid, 'fixed.epub')):
        book = Book.load(store.path(pid, 'fixed.epub'))
        ws = load_waivers(pid, renames=True)
        f['after'] = _issues_report(engine.audit(book, waivers=ws), book, ws)
        f['waivers_changed'] = True          # 输出文件是按旧豁免修的，提示用户重新修复
        store.write_json(pid, 'fix.json', f)


ROLE_NAMES = {'h1': '一级标题', 'h2': '二级标题', 'h3': '三级标题', 'para': '正文段落', 'figure': '插图',
              'caption': '图注', 'source': '资料来源', 'bullet': '列表项', 'note': '注释', 'note-head': '注释小标题',
              'toc': '书内目录页', 'junk': '广告/引流', 'meta': '版权信息', 'quote': '引文', 'right': '右对齐短行',
              'center': '居中短行', 'keep': '表格等原样保留', 'poem': '诗歌', 'letter': '书信', 'ol': '有序列表项',
              'dl': '定义列表', 'item': '序号项', 'article': '条文', 'loi-head': '插图/表格目录标题',
              'loi-entry': '插图/表格目录条目', 'table-caption': '表题', 'table-note': '表注', 'note-cont': '注释续段',
              'heading-merged': '已并入标题', 'h4': '四级标题', 'h5': '五级标题', 'h6': '六级标题'}
SUGGEST_NAMES = {'poem': '诗歌', 'letter': '书信', 'loi': '插图目录', 'lot': '表格目录', 'table': '表格',
                 'glossary': '术语表', 'script': '剧本对白'}


def fix(pid: str, mode: str = 'basic') -> None:
    """mode='basic'：只做规范修复（M0，不改版面）；mode='rebuild'：语义分析+排版重建（M2）。"""
    store.update(pid, status='fixing', message='')
    original = open(store.path(pid, 'original.epub'), 'rb').read()
    book = Book.load(original)
    ws = load_waivers(pid)
    result = {'mode': mode}
    if mode == 'rebuild':
        orep = optimize(book, waivers=ws)
        rep = engine.FixReport(orep.fix.changes + orep.refix.changes, orep.fix.before, orep.refix.after,
                               orep.fix.skipped + orep.refix.skipped)
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
            'structures': [{'name': k, 'level': lv, 'count': n}
                           for (k, lv), n in sorted(orep.rebuild.structures.items(), key=lambda x: -x[1])],
            'suggestions': [{'kind': x['kind'], 'name': SUGGEST_NAMES.get(x['kind'], x['kind']), 'text': x['text']}
                            for x in orep.rebuild.suggestions[:200]],
            'suggestions_total': len(orep.rebuild.suggestions),
        }
    else:
        rep = engine.fix(book, waivers=ws)
        out = book.to_bytes()
        diff = compare_text(Book.load(original), Book.load(out))
        result['text'] = {'equal': diff.equal, 'length': diff.length, 'summary': diff.summary(),
                          'changes': [{'file': f, 'op': op, 'before': a[:80], 'after': b[:80]}
                                      for f, op, a, b in diff.changes[:50]]}
    tmp = store.path(pid, 'fixed.epub.tmp')
    with open(tmp, 'wb') as f:
        f.write(out)
    os.replace(tmp, store.path(pid, 'fixed.epub'))
    store.write_json(pid, 'fixed.renames.json', WaiverSet.renames_of(book))
    msgs = epubcheck.run(store.path(pid, 'fixed.epub'), locale=EPUBCHECK_LOCALE)
    result.update({
        'changes': [{'rule': r, 'text': t} for r, t in rep.changes],
        'before': _issues_report(rep.before, None, ws),
        'after': _issues_report(rep.after, book, ws, rep.skipped),
        'epubcheck': _epubcheck_report(msgs),
        'size': len(out),
    })
    store.write_json(pid, 'fix.json', result)
    store.update(pid, status='fixed')


def is_epub_like(data: bytes) -> bool:
    return data[:2] == b'PK'

