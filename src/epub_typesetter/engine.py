"""规则引擎：先检测、再修复、再整体复检（规格见 guide/07 §0.2）。

- 每条规则有 ID、严重度、默认修复等级；检测只读，修复只处理等级被允许的问题。
- 规则按 ``order`` 依次执行：每条规则的修复都基于前面规则修复后的状态重新检测，
  因此规则之间不需要互相知道对方改了什么。
- 修复必须幂等：对已修复的书再跑一遍应当零改动（测试会验证）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .book import Book

ERROR, WARNING, INFO = 'error', 'warning', 'info'
AUTO, SUGGEST, LLM, MANUAL = 'auto', 'suggest', 'llm', 'manual'


@dataclass
class Issue:
    rule_id: str
    severity: str
    message: str
    file: str | None = None
    fix_level: str = MANUAL
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d['data']:
            d.pop('data')
        return d


class Rule:
    id: str = ''
    title: str = ''
    order: int = 0

    def check(self, book: Book) -> list[Issue]:
        raise NotImplementedError

    def fix(self, book: Book, issues: list[Issue]) -> list[str]:
        """修复给定问题，返回人类可读的修改记录。默认不修。"""
        return []

    def issue(self, severity: str, message: str, file: str | None = None,
              fix_level: str = MANUAL, **data) -> Issue:
        return Issue(self.id, severity, message, file, fix_level, data)


REGISTRY: list[Rule] = []


def register(cls: type[Rule]) -> type[Rule]:
    assert cls.id and not any(r.id == cls.id for r in REGISTRY), cls
    REGISTRY.append(cls())
    REGISTRY.sort(key=lambda r: (r.order, r.id))
    return cls


def all_rules() -> list[Rule]:
    from . import rules  # noqa: F401  导入即注册
    return list(REGISTRY)


def select(ids: list[str] | None = None) -> list[Rule]:
    rs = all_rules()
    if not ids:
        return rs
    wanted = {i.upper() for i in ids}
    return [r for r in rs if r.id in wanted or r.id.split('-')[0] in wanted]


def audit(book: Book, rules: list[Rule] | None = None) -> list[Issue]:
    out: list[Issue] = []
    for r in rules or all_rules():
        out.extend(r.check(book))
    return out


@dataclass
class FixReport:
    changes: list[tuple[str, str]] = field(default_factory=list)   # (rule_id, 说明)
    before: list[Issue] = field(default_factory=list)
    after: list[Issue] = field(default_factory=list)


def fix(book: Book, levels: set[str] = frozenset({AUTO}),
        rules: list[Rule] | None = None) -> FixReport:
    rules = rules or all_rules()
    rep = FixReport(before=audit(book, rules))
    for r in rules:
        # 一条规则的修复可能暴露同一规则的新问题（如补了命名空间才看得出缺 head），
        # 所以反复「检测→修复」直到稳定，最多 3 轮
        for _ in range(3):
            todo = [i for i in r.check(book) if i.fix_level in levels]
            if not todo:
                break
            lines = r.fix(book, todo)
            rep.changes.extend((r.id, line) for line in lines)
            if not lines:
                break
    book.flush()
    rep.after = audit(book, rules)
    return rep
