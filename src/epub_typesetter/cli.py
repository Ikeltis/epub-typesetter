"""命令行入口（用于测试与批量验收；正式界面是网页）。

    python -m epub_typesetter check book.epub [--format text|json] [--waivers 路径] [--epubcheck]
    python -m epub_typesetter fix book.epub -o out.epub [--rules STR,SEM-003] [--epubcheck]

`audit` 是 `check` 的旧名。豁免文件默认取 `<书>.epub.typeset-ignore.json`（guide/07 §7）。
退出码：0 = 没有未豁免的 error；1 = 有；2 = 用法错误、无法读取或豁免文件格式错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import engine, epubcheck, report
from .book import Book, EpubError
from .textcheck import compare_text
from .waivers import WaiverFileError, WaiverSet, default_path, glob_re


def _waivers(a) -> tuple[WaiverSet | None, str | None]:
    if a.no_waivers:
        return None, None
    path = a.waivers or default_path(a.epub)
    if a.waivers and not os.path.exists(path):
        raise WaiverFileError(f'找不到豁免文件：{path}')
    ws = WaiverSet.load(path)
    if a.unwaive:
        drop = {r.strip().upper() for r in a.unwaive}
        ws.entries = [w for w in ws.entries if w.rule not in drop]
    return ws, path if os.path.exists(path) else None


def _filter(rep: dict, a) -> dict:
    if a.file:
        rx = glob_re(a.file)
        rep['issues'] = [d for d in rep['issues'] if d['file'] and rx.match(d['file'])]
    return rep


def cmd_check(a):
    book = Book.load(a.epub)
    ws, _ = _waivers(a)
    issues = engine.audit(book, engine.select(a.rules), ws)
    rep = _filter(report.build(issues, book, ws, os.path.basename(a.epub)), a)
    if a.format == 'json':
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(report.format_text(rep, None if a.hits == 'all' else int(a.hits),
                                 color=sys.stdout.isatty() and not a.no_color,
                                 show_waived=not a.hide_waived, min_severity=a.min_severity))
    if a.epubcheck:
        print('epubcheck:', json.dumps(epubcheck.summarize(epubcheck.run(a.epub)), ensure_ascii=False))
    return report.exit_code(rep)


def cmd_fix(a):
    original = open(a.epub, 'rb').read()
    book = Book.load(original)
    ws, _ = _waivers(a)
    rep = engine.fix(book, rules=engine.select(a.rules), waivers=ws)
    out = book.to_bytes()
    with open(a.output, 'wb') as f:
        f.write(out)
    if ws is not None and ws.entries:          # 新书旁写出豁免文件：条目原样，只更新 renames（§7.2）
        ws.save(default_path(a.output), WaiverSet.renames_of(book, ws.renames))
    for rid, line in rep.changes:
        print(f'[{rid}] {line}')
    after = report.build(rep.after, book, ws, os.path.basename(a.output), rep.skipped)
    print(f'修改 {len(rep.changes)} 处；问题 {len(report.build(rep.before)["issues"])} → {len(after["issues"])}'
          + (f'；因部分豁免未修 {len(rep.skipped)} 条' if rep.skipped else ''))
    diff = compare_text(Book.load(original), Book.load(out))
    print(f'可见文字：{"一致" if diff.equal else "有差异"}（{diff.summary()}）')
    if a.epubcheck:
        b0, b1 = epubcheck.run_bytes(original), epubcheck.run_bytes(out)
        print(f'epubcheck error+fatal：{epubcheck.blocking(b0)} → {epubcheck.blocking(b1)}')
        print('修复后：', json.dumps(epubcheck.summarize(b1), ensure_ascii=False))
    return 0


def _common(p):
    p.add_argument('epub')
    p.add_argument('--epubcheck', action='store_true')
    p.add_argument('--rules', type=lambda s: s.split(','), help='只跑这些规则或类别，如 STR,SEM-003')
    p.add_argument('--waivers', help='豁免文件路径（默认 <书>.epub.typeset-ignore.json）')
    p.add_argument('--no-waivers', action='store_true', help='本次忽略全部豁免')
    p.add_argument('--unwaive', type=lambda s: s.split(','), help='本次让这些规则的豁免失效，如 TXT-003,STR-005')


def main(argv=None):
    p = argparse.ArgumentParser(prog='epub_typesetter')
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('check', 'audit'):
        pa = sub.add_parser(name, help='体检，只读' if name == 'check' else '同 check（旧名）')
        _common(pa)
        pa.add_argument('--format', choices=('text', 'json'), default='text')
        pa.add_argument('--json', dest='format', action='store_const', const='json', help='同 --format json')
        pa.add_argument('--hits', default='5', help='每条问题列出的命中数，或 all')
        pa.add_argument('--min-severity', choices=('error', 'warning', 'info'), default='info')
        pa.add_argument('--file', help='只看这些文件（通配，** 跨目录）')
        pa.add_argument('--hide-waived', action='store_true')
        pa.add_argument('--no-color', action='store_true')
        pa.set_defaults(func=cmd_check)
    pf = sub.add_parser('fix', help='应用 auto 级修复')
    _common(pf)
    pf.add_argument('-o', '--output', required=True)
    pf.set_defaults(func=cmd_fix)
    a = p.parse_args(argv)
    try:
        return a.func(a)
    except (EpubError, WaiverFileError) as e:
        print(f'错误：{e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
