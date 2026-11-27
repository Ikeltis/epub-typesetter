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


def optimize(book: Book, theme: str = 'default', waivers=None, decisions: dict | None = None,
             options: dict | None = None) -> OptimizeReport:
    """豁免只作用于两轮规范修复；重建本身整体重排，不逐处看豁免。
    decisions：确认板上的用户决定（board.py），没有就按识别结果的默认取舍。
    options：按书选项（options.py）：关掉的识别并进决定（确认板逐条决定仍优先），外观追加覆盖样式。"""
    from . import options as opt
    o = opt.clean(options)
    decisions = dict(decisions or {})
    decisions['kinds'] = {**opt.kinds_off(o), **(decisions.get('kinds') or {})}
    decisions['features'] = o['features']
    rep0 = engine.fix(book, waivers=waivers)
    an = analyze(book, decisions)
    rrep = rebuild(book, an, theme, opt.style_css(o))
    book.flush()
    rep1 = engine.fix(book, waivers=waivers)
    return OptimizeReport(rep0, an, rrep, rep1)
