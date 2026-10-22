"""命令行入口（M0 用于测试与批量验收；正式界面是网页）。

    python -m epub_typesetter audit book.epub [--json] [--epubcheck]
    python -m epub_typesetter fix book.epub -o out.epub [--rules STR,SEM-003] [--epubcheck]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from . import engine, epubcheck
from .book import Book, EpubError
from .textcheck import compare_text


def _print_issues(issues, as_json):
    if as_json:
        print(json.dumps([i.to_dict() for i in issues], ensure_ascii=False, indent=1))
        return
    by_rule = Counter((i.rule_id, i.severity) for i in issues)
    for (rid, sev), n in sorted(by_rule.items()):
        sample = next(i for i in issues if i.rule_id == rid)
        print(f'{rid:9} {sev:7} ×{n:<5} {sample.message}')
    print(f'共 {len(issues)} 个问题')


def cmd_audit(a):
    book = Book.load(a.epub)
    issues = engine.audit(book, engine.select(a.rules))
    _print_issues(issues, a.json)
    if a.epubcheck:
        print('epubcheck:', json.dumps(epubcheck.summarize(epubcheck.run(a.epub)), ensure_ascii=False))


def cmd_fix(a):
    original = open(a.epub, 'rb').read()
    book = Book.load(original)
    rep = engine.fix(book, rules=engine.select(a.rules))
    out = book.to_bytes()
    with open(a.output, 'wb') as f:
        f.write(out)
    for rid, line in rep.changes:
        print(f'[{rid}] {line}')
    print(f'修改 {len(rep.changes)} 处；问题 {len(rep.before)} → {len(rep.after)}')
    diff = compare_text(Book.load(original), Book.load(out))
    print(f'可见文字：{"一致" if diff.equal else "有差异"}（{diff.summary()}）')
    if a.epubcheck:
        b0, b1 = epubcheck.run_bytes(original), epubcheck.run_bytes(out)
        print(f'epubcheck error+fatal：{epubcheck.blocking(b0)} → {epubcheck.blocking(b1)}')
        print('修复后：', json.dumps(epubcheck.summarize(b1), ensure_ascii=False))


def main(argv=None):
    p = argparse.ArgumentParser(prog='epub_typesetter')
    sub = p.add_subparsers(dest='cmd', required=True)
    pa = sub.add_parser('audit', help='体检，只读')
    pa.add_argument('epub')
    pa.add_argument('--json', action='store_true')
    pa.add_argument('--epubcheck', action='store_true')
    pa.add_argument('--rules', type=lambda s: s.split(','))
    pa.set_defaults(func=cmd_audit)
    pf = sub.add_parser('fix', help='应用 auto 级修复')
    pf.add_argument('epub')
    pf.add_argument('-o', '--output', required=True)
    pf.add_argument('--epubcheck', action='store_true')
    pf.add_argument('--rules', type=lambda s: s.split(','))
    pf.set_defaults(func=cmd_fix)
    a = p.parse_args(argv)
    try:
        a.func(a)
    except EpubError as e:
        print(f'错误：{e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
