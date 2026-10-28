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


def optimize(book: Book, theme: str = 'default') -> OptimizeReport:
    rep0 = engine.fix(book)
    an = analyze(book)
    rrep = rebuild(book, an, theme)
    book.flush()
    rep1 = engine.fix(book)
    return OptimizeReport(rep0, an, rrep, rep1)
