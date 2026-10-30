"""完整优化流程：M0 规范修复 → 语义分析 → 重建 → 再规范化。"""
from __future__ import annotations

from dataclasses import dataclass

from . import engine
from .book import Book
from .rebuild import RebuildReport, rebuild
from .semantic import Analysis, analyze


@dataclass
class OptimizeReport:
    fix: engine.FixReport
    analysis: Analysis
    rebuild: RebuildReport
    refix: engine.FixReport


def optimize(book: Book, theme: str = 'default', waivers=None, decisions: dict | None = None) -> OptimizeReport:
    """豁免只作用于两轮规范修复；重建本身整体重排，不逐处看豁免。
    decisions：确认板上的用户决定（board.py），没有就按识别结果的默认取舍。"""
    rep0 = engine.fix(book, waivers=waivers)
    an = analyze(book, decisions)
    rrep = rebuild(book, an, theme)
    book.flush()
    rep1 = engine.fix(book, waivers=waivers)
    return OptimizeReport(rep0, an, rrep, rep1)
