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


# ---------- 重建后的「按块」校验 ----------

_NOTE_MARK = re.compile(r'\[\d{1,3}\]|\uff3b\d{1,3}\uff3d|[\u2460-\u2473]|〔\d{1,3}〕')   # [1]、［1］、①–⑳、〔1〕
_BULLET = re.compile(r'^[●•◆◇■□▪▫○◎※►▶➢✓✔]')


def _after_text(book: Book) -> str:
    """重建后全书文字：跳过新生成的注号与回链（它们的编号会变）。"""
    parts = []
    for it in book.spine_items():
        if it.path not in book.files or it.media_type != 'application/xhtml+xml':
            continue
        root = book.tree(it.path).getroot()

        def walk(el):
            cls = (el.get('class') or '').split() if isinstance(el.tag, str) else []
            if 'noteref' in cls or 'backlink' in cls:
                if el.tail:
                    parts.append(el.tail)
                return
            if isinstance(el.tag, str) and el.text:
                parts.append(el.text)
            for ch in el:
                walk(ch)
            if el.tail:
                parts.append(el.tail)
        body = next((e for e in root.iter() if isinstance(e.tag, str) and e.tag.endswith('}body')), root)
        walk(body)
    # 与重建前的块文字用同一套归一化：没配上注释的注号会保留原样，两边都要去掉
    return _NOTE_MARK.sub('', _INVISIBLE.sub('', ''.join(parts)))


@dataclass
class BlockCheck:
    total: int
    missing: list[tuple[str, str]]          # (角色, 文字)
    removed: int
    chars_before: int = 0                   # 应保留块的字数
    chars_after: int = 0                    # 重建后全书字数

    @property
    def duplicated(self) -> bool:
        # 重建只删不增：字数明显变多说明有内容被重复输出（逐块子串匹配查不出重复）
        return self.chars_after > self.chars_before * 1.005 + 20

    @property
    def ok(self) -> bool:
        return not self.missing and not self.duplicated

    def summary(self) -> str:
        if self.ok:
            return f'{self.total} 个内容块全部保留（另有意删除 {self.removed} 块）'
        parts = []
        if self.missing:
            parts.append(f'{len(self.missing)} 个内容块找不到：' +
                         '；'.join(f'{r}「{t[:20]}」' for r, t in self.missing[:5]))
        if self.duplicated:
            parts.append(f'字数 {self.chars_before} → {self.chars_after}，疑似内容重复')
        return '；'.join(parts)


def compare_blocks(blocks, removed_roles: set[str], after: Book) -> BlockCheck:
    """blocks：重建前的语义块；有意删除的角色不检查，其余每块的文字都必须出现在重建后的书里。"""
    text = _after_text(after)
    missing, total, removed, chars = [], 0, 0, 0
    for b in blocks:
        if b.role in removed_roles:
            removed += 1
            continue
        src = b.text if getattr(b, 'verify', None) is None else b.verify   # 重建有意改写的块按期望文字核对
        t = _INVISIBLE.sub('', _NOTE_MARK.sub('', _BULLET.sub('', src.strip())))
        if not t:
            continue
        total += 1
        chars += len(t)
        if t not in text:
            missing.append((b.role, b.text))
    # 图片没有文字，按块核对不出丢失：另数一遍图片（有意删除的块里的不算）
    media = lambda el: sum(1 for d in el.iter() if isinstance(d.tag, str) and d.tag.rsplit('}', 1)[-1] in ('img', 'image'))
    imgs_before = sum(media(b.el) for b in blocks if b.role not in removed_roles)
    imgs_after = 0
    for it in after.spine_items():
        if it.path in after.files and it.media_type == 'application/xhtml+xml':
            root = after.tree(it.path).getroot()
            imgs_after += sum(media(e) for e in root.iter() if isinstance(e.tag, str) and e.tag.endswith('}body'))
    if imgs_after < imgs_before:
        missing.append(('图片', f'重建前 {imgs_before} 张，重建后只有 {imgs_after} 张'))
    return BlockCheck(total, missing, removed, chars, len(text))
