"""检查报告（guide/07 §6）：一条问题 = 同一规则 × 同一文件，多处命中放进 hits。

引擎内部、命令行、网页共用这一份数据；文字说明、修改提示、规范条目取自 rules_meta.json。
"""
from __future__ import annotations

import re

from . import __version__
from .book import NS, Book
from .engine import AUTO, ERROR, INFO, SEV_RANK, WARNING, Hit, Issue, rules_meta

REPORT_VERSION = 1


def _natural(s: str | None):
    if s is None:
        return (0, [])
    return (1, [(0, int(t), '') if t.isdigit() else (1, 0, t) for t in re.split(r'(\d+)', s) if t])


def _merge(group: list[Issue]) -> Issue:
    """同规则同文件的多条（如 A11Y-001 的「缺 alt」和「alt 是文件名」）合并为一条。"""
    if len(group) == 1:
        return group[0]
    first = min(group, key=lambda i: SEV_RANK[i.severity])
    msgs = list(dict.fromkeys(i.message for i in group))
    return Issue(first.rule_id, first.severity, '；'.join(msgs), first.file, first.fix_level,
                 {k: v for i in group for k, v in i.data.items()}, [h for i in group for h in i.hits],
                 min(i.confidence for i in group), first.source)


def issue_dict(iss: Issue, waivers=None, status: str | None = None) -> dict:
    meta = rules_meta()['rules'].get(iss.rule_id, {})
    hits = iss.hits or [Hit()]
    wids = list(dict.fromkeys(h.waiver_id for h in hits if h.waiver_id))
    reasons = {w.id: w.reason for w in (waivers.entries if waivers else [])}
    n_waived = sum(h.waived for h in hits)
    if status is None:
        status = 'open' if not n_waived else 'waived' if n_waived == len(hits) else 'partial'
    hits = sorted(hits, key=lambda h: (h.line is None, h.line or 0))
    return {
        'key': iss.key, 'rule_id': iss.rule_id, 'severity': iss.severity, 'message': iss.message,
        'title': meta.get('title', ''), 'hint': iss.data.get('hint') or meta.get('hint', ''),
        'spec': meta.get('spec', []), 'fix_level': iss.fix_level, 'source': iss.source,
        'confidence': iss.confidence, 'file': iss.file, 'status': status,
        'hit_count': len(hits), 'waived_count': n_waived,
        'waivers': [{'id': w, 'reason': reasons.get(w, '')} for w in wids],
        'hits': [h.to_dict() for h in hits],
    }


def build(issues: list[Issue], book: Book | None = None, waivers=None, path: str = '',
          skipped: list[str] | None = None) -> dict:
    groups: dict[str, list[Issue]] = {}
    for i in issues:
        groups.setdefault(i.key, []).append(i)
    merged = sorted((_merge(g) for g in groups.values()), key=lambda i: (_natural(i.file), i.rule_id))
    skipped = set(skipped or [])
    items = []
    for iss in merged:
        d = issue_dict(iss, waivers)
        if iss.key in skipped and d['status'] == 'partial':
            d['status'] = 'skipped'
        items.append(d)
    summary = {ERROR: 0, WARNING: 0, INFO: 0, 'waived': 0, 'auto_fixable': 0}
    for d in items:
        if d['status'] == 'waived':
            summary['waived'] += 1
            continue
        summary[d['severity']] += 1
        if d['fix_level'] == AUTO:
            summary['auto_fixable'] += 1
    rep = {
        'report_version': REPORT_VERSION,
        'engine': {'version': __version__, 'rules_spec': f'07@{rules_meta()["spec_version"]}'},
        'summary': summary,
        'issues': items,
    }
    if book is not None:
        ident = book.opf.find('opf:metadata/dc:identifier', NS)
        rep['book'] = {'path': path or book.source_name,
                       'identifier': (ident.text or '').strip() if ident is not None else '',
                       'epub_version': book.version, 'documents': len(book.content_docs())}
    return rep


def exit_code(rep: dict) -> int:
    """0 = 没有未豁免的 error；1 = 有（guide/07 §6.3）。"""
    return 1 if rep['summary'][ERROR] else 0


# ---------- 命令行文本 ----------

COLORS = {ERROR: '31', WARNING: '33', INFO: '34', 'waived': '90'}


def format_text(rep: dict, hits: int | None = 5, color: bool = False, show_waived: bool = True,
                min_severity: str = INFO) -> str:
    def paint(s, kind):
        return f'\033[{COLORS[kind]}m{s}\033[0m' if color else s

    out = []
    b = rep.get('book')
    if b:
        out.append(f'{b["path"]}（EPUB {b["epub_version"]}，{b["documents"]} 个内容文档）')
    cur = object()
    limit = SEV_RANK[min_severity]
    for d in rep['issues']:
        if SEV_RANK[d['severity']] > limit:
            continue
        if d['status'] == 'waived' and not show_waived:
            continue
        if d['file'] != cur:
            cur = d['file']
            out += ['', d['file'] or '（全书）']
        n, nw = d['hit_count'], d['waived_count']
        msg = d['message']
        if nw and d['status'] != 'waived':
            msg += f'（其中 {nw} 处已豁免）'
        if d['status'] == 'waived':
            out.append('  ' + paint(f'已豁免   {d["rule_id"]}  {msg}', 'waived'))
            for w in d['waivers']:
                out.append('    ' + paint(f'理由：{w["reason"]}（{w["id"]}）', 'waived'))
            continue
        tag = '  [未修：部分豁免]' if d['status'] == 'skipped' else ''
        out.append(f'  {paint(f"{d["severity"]:8}", d["severity"])} {d["rule_id"]}  {msg}  [{d["fix_level"]}]{tag}')
        if d['hint']:
            out.append(f'    提示：{d["hint"]}')
        if d['spec']:
            out.append(f'    规范：{"、".join(d["spec"])}')
        shown = [h for h in d['hits'] if (h['xpath'] or h['snippet']) and (show_waived or not h['waived'])]
        cut = shown if hits is None else shown[:hits]
        reasons = {w['id']: w['reason'] for w in d['waivers']}
        for h in cut:
            loc = (f'{h["line"]}:{h["col"]}' if h['col'] else str(h['line'])) if h['line'] else h['xpath']
            line = f'      {loc:<8}{h["snippet"]}'
            if h['waived']:
                line = paint(f'{line}   已豁免（{h["waiver_id"]}：{reasons.get(h["waiver_id"], "")}）', 'waived')
            out.append(line)
        if len(shown) > len(cut):
            out.append(f'      …另 {len(shown) - len(cut)} 处，--hits all 查看')
    s = rep['summary']
    open_n = s[ERROR] + s[WARNING] + s[INFO]
    out += ['', f'共 {open_n} 条未豁免问题：error {s[ERROR]}，warning {s[WARNING]}，info {s[INFO]}；'
                f'另有 {s["waived"]} 条已豁免；{s["auto_fixable"]} 条可自动修复。']
    return '\n'.join(out).lstrip('\n')
