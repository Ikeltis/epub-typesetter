"""批量验收（guide/07 §4.1）：修复前后 epubcheck、可见文字、幂等。

用法（开发容器内）: python scripts/acceptance.py testdata/epub_in -o testdata/epub_out
"""
import argparse
import glob
import json
import os
import time
from collections import Counter

from epub_typesetter import engine, epubcheck, layoutcheck
from epub_typesetter.book import Book
from epub_typesetter.pipeline import optimize
from epub_typesetter.rebuild import REMOVED_ROLES
from epub_typesetter.textcheck import compare_blocks, compare_text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('indir')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--only', default='')
    ap.add_argument('--m2', action='store_true', help='跑完整优化（语义分析+重建），按块校验文字')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows, after_ids = [], Counter()
    for path in sorted(glob.glob(os.path.join(a.indir, '*.epub'))):
        name = os.path.basename(path)
        if a.only and a.only not in name:
            continue
        t0 = time.time()
        original = open(path, 'rb').read()
        book = Book.load(original)
        if a.m2:
            orep = optimize(book)
            rep = orep.refix
            out = book.to_bytes()
            bc = compare_blocks(orep.analysis.blocks, REMOVED_ROLES, Book.load(out))
            diff = type('D', (), {'equal': bc.ok, 'summary': bc.summary})()
            layout = None                          # 拆章后逐文件比版面不成立，靠按块校验 + 抽样截图
            extra = dict(roles=dict(orep.analysis.counts()), files=len(orep.rebuild.chapters),
                         removed=len(orep.rebuild.removed))
        else:
            rep = engine.fix(book)
            out = book.to_bytes()
            diff = compare_text(Book.load(original), Book.load(out))
            layout = layoutcheck.compare_layout(original, out) if layoutcheck.available() else None
            extra = {}
        open(os.path.join(a.out, name), 'wb').write(out)
        again = engine.fix(Book.load(out))
        before_msgs, after_msgs = epubcheck.run(path), epubcheck.run_bytes(out)
        for m in after_msgs or []:
            if m.severity in ('ERROR', 'FATAL'):
                after_ids[(m.id, m.message[:90])] += max(1, len(m.locations))
        row = dict(book=name[:24], err_before=epubcheck.blocking(before_msgs), err_after=epubcheck.blocking(after_msgs),
                   changes=len(rep.changes), issues_after=len(rep.after), idempotent=not again.changes,
                   text_equal=diff.equal, text_diff='' if diff.equal else diff.summary()[:120],
                   layout_ok=None if layout is None else layout.ok,
                   layout='' if layout is None or layout.ok else layout.summary()[:160],
                   secs=round(time.time() - t0, 1), **extra)
        if again.changes:
            row['again'] = [f'{r}:{l[:60]}' for r, l in again.changes[:3]]
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    print('\n== 修复后仍存在的 epubcheck ERROR/FATAL ==')
    for (i, msg), n in after_ids.most_common():
        print(f'{n:5}  {i}  {msg}')
    tot = lambda k: sum(r[k] for r in rows)  # noqa: E731
    print(f'\n合计 {len(rows)} 本：error {tot("err_before")} → {tot("err_after")}；'
          f'幂等 {sum(r["idempotent"] for r in rows)}/{len(rows)}；文字一致 {sum(r["text_equal"] for r in rows)}/{len(rows)}；'
          f'版面正常 {sum(bool(r["layout_ok"]) for r in rows)}/{len(rows)}')


if __name__ == '__main__':
    main()
