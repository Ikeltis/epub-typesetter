"""M2 诊断：列出某本书重建后找不到的内容块（含源码与重建后附近文字）和 epubcheck 错误。

用法: python scripts/debug_m2.py testdata/epub_in/XX.epub [最多显示几条]
"""
import collections
import sys

from lxml import etree

from epub_typesetter import epubcheck
from epub_typesetter.book import Book
from epub_typesetter.pipeline import optimize
from epub_typesetter.rebuild import REMOVED_ROLES
from epub_typesetter.textcheck import _INVISIBLE, _after_text, compare_blocks

path = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3
b = Book.load(path)
r = optimize(b)
data = b.to_bytes()
out = Book.load(data)
c = compare_blocks(r.analysis.blocks, REMOVED_ROLES, out)
print('块校验：', c.summary())
text = _after_text(out)
for role, t in c.missing[:limit]:
    blk = next(x for x in r.analysis.blocks if x.text == t)
    print(f'\n--- 缺失 {role}（来自 {blk.doc}）')
    print('源码：', etree.tostring(blk.el, encoding='unicode', with_tail=False)[:600])
    key = _INVISIBLE.sub('', t)[:8]
    i = text.find(key)
    print('重建后：', text[i:i + 150] if i >= 0 else '（开头 8 个字都找不到）')
msgs = epubcheck.run_bytes(data) or []
errs = collections.Counter()
ex = {}
for m in msgs:
    if m.severity in ('ERROR', 'FATAL'):
        k = (m.id, m.message[:100])
        errs[k] += max(1, len(m.locations))
        ex.setdefault(k, m.locations[:2])
print('\nepubcheck 错误：')
for k, n in errs.most_common(10):
    print(f'{n:4} {k[0]} {k[1]} {ex[k]}')
