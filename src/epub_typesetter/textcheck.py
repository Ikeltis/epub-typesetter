"""「可见文字不变」校验（guide/07 §4.1 验收口径）。

按 spine 顺序取每个内容文档 body 的文字，去掉所有空白与不可见字符后比较。
空白、缩进、空段、零宽字符的清理不算改动；其余任何字的增删都会被报告。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .book import NS, Book

_INVISIBLE = re.compile(r'[\s\u3000\u00a0\u200b-\u200d\u2060\ufeff\x00-\x1f\x7f-\x9f]+')


def doc_texts(book: Book) -> list[tuple[str, str]]:
    """按 spine 顺序返回 [(路径, 去空白后的可见文字)]。"""
    out = []
    for it in book.spine_items():
        if it.path not in book.files or it.media_type != 'application/xhtml+xml':
            continue
        root = book.tree(it.path).getroot()
        # 不依赖命名空间找 body：修复前的文档可能缺 XHTML 命名空间
        body = next((e for e in root.iter() if isinstance(e.tag, str)
                     and e.tag.rsplit('}', 1)[-1] == 'body'), root)
        out.append((it.path, _INVISIBLE.sub('', ''.join(body.itertext()))))
    return out


def visible_text(book: Book) -> str:
    return ''.join(t for _, t in doc_texts(book))


@dataclass
class TextDiff:
    equal: bool
    length: int
    changes: list[tuple[str, str, str, str]]   # (文件, 操作, 原文片段, 新文片段)

    def summary(self) -> str:
        if self.equal:
            return f'{self.length} 字'
        shown = '；'.join(f'{f.rsplit("/", 1)[-1]} {op}「{a[:20]}」→「{b[:20]}」'
                         for f, op, a, b in self.changes[:5])
        return f'{len(self.changes)} 处差异：{shown}'


def _diff(path: str, a: str, b: str) -> list[tuple[str, str, str, str]]:
    # 先去掉公共前后缀，只对中间不同的部分做字符级比对，避免长文本上的平方级耗时
    i = 0
    n = min(len(a), len(b))
    while i < n and a[i] == b[i]:
        i += 1
    j = 0
    while j < n - i and a[-1 - j] == b[-1 - j]:
        j += 1
    ma, mb = a[i:len(a) - j], b[i:len(b) - j]
    if len(ma) + len(mb) > 20000:
        return [(path, 'replace', ma[:40], mb[:40])]
    sm = difflib.SequenceMatcher(None, ma, mb, autojunk=False)
    return [(path, op, ma[i1:i2], mb[j1:j2]) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != 'equal']


def compare_text(before: Book, after: Book) -> TextDiff:
    da, db = doc_texts(before), doc_texts(after)
    total = sum(len(t) for _, t in da)
    if [t for _, t in da] == [t for _, t in db]:
        return TextDiff(True, total, [])
    changes = []
    if [p for p, _ in da] != [p for p, _ in db]:
        changes.append(('spine', 'replace', ' '.join(p for p, _ in da)[:40], ' '.join(p for p, _ in db)[:40]))
    for (pa, ta), (pb, tb) in zip(da, db):
        if ta != tb:
            changes += _diff(pa, ta, tb)
    return TextDiff(False, total, changes)
