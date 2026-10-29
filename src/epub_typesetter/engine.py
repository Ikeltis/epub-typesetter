"""规则引擎：先检测、再修复、再整体复检（规格见 guide/07 §0.2）。

- 每条规则有 ID、严重度、默认修复等级；检测只读，修复只处理等级被允许的问题。
- 规则按 ``order`` 依次执行：每条规则的修复都基于前面规则修复后的状态重新检测，
  因此规则之间不需要互相知道对方改了什么。
- 修复必须幂等：对已修复的书再跑一遍应当零改动（测试会验证）。
- 按书豁免（guide/07 §7）：检测后给命中打「已豁免」标记；全部命中已豁免的问题不修，
  部分豁免的问题只有声明了 ``node_fix`` 的规则才修（修复时避开已豁免的节点），其余整条跳过。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from lxml import etree

from .book import NS, Book

if TYPE_CHECKING:
    from .waivers import WaiverSet

ERROR, WARNING, INFO = 'error', 'warning', 'info'
AUTO, SUGGEST, LLM, MANUAL = 'auto', 'suggest', 'llm', 'manual'


SEV_RANK = {ERROR: 0, WARNING: 1, INFO: 2}


@cache
def rules_meta() -> dict:
    """规则的说明、严重度、修改提示、规范条目（由 scripts/build_rules_meta.py 从 guide/07 生成）。"""
    return json.loads((Path(__file__).with_name('rules_meta.json')).read_text(encoding='utf-8'))


@dataclass
class Hit:
    """问题在文件里的一处命中（guide/07 §6.1）。``el``/``text`` 只在内存里用于豁免匹配，不输出。"""
    xpath: str = ''
    selector: str = ''
    snippet: str = ''
    line: int | None = None
    col: int | None = None
    orig_line: int | None = None
    range: tuple[int, int] | None = None
    waived: bool = False
    waiver_id: str | None = None
    fix: dict | None = None
    el: object = field(default=None, repr=False, compare=False)
    text: str | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        d = {'line': self.line, 'col': self.col, 'orig_line': self.orig_line, 'xpath': self.xpath,
             'selector': self.selector, 'snippet': self.snippet,
             'range': list(self.range) if self.range else None,
             'waived': self.waived, 'waiver_id': self.waiver_id, 'fix': None if self.waived else self.fix}
        if self.range and self.text is not None:     # 供界面「仅此处」生成文字锚点（§7.3 anchor）
            a, b = self.range
            d['anchor'] = {'quote': self.text[a:b], 'prefix': self.text[max(0, a - 8):a],
                           'suffix': self.text[b:b + 8]}
        return d


@dataclass
class Issue:
    rule_id: str
    severity: str
    message: str
    file: str | None = None
    fix_level: str = MANUAL
    data: dict = field(default_factory=dict)
    hits: list[Hit] = field(default_factory=list)
    confidence: float = 1.0
    source: str = 'native'

    @property
    def key(self) -> str:
        return f'{self.rule_id}@{self.file or "-"}'

    @property
    def waived_count(self) -> int:
        return sum(h.waived for h in self.hits)

    @property
    def status(self) -> str:
        """open / waived / partial。没有显式命中的问题按一个隐含命中算。"""
        n = self.waived_count
        if not n:
            return 'open'
        return 'waived' if n == len(self.hits) else 'partial'

    def waived_nodes(self) -> set:
        return {h.el for h in self.hits if h.waived and h.el is not None}

    def to_dict(self) -> dict:
        d = {'rule_id': self.rule_id, 'severity': self.severity, 'message': self.message, 'file': self.file,
             'fix_level': self.fix_level}
        if self.data:
            d['data'] = self.data
        return d


def _sibling_index(el) -> tuple[int, int]:
    same = [c for c in el.getparent() if c.tag == el.tag] if el.getparent() is not None else [el]
    return same.index(el) + 1, len(same)


def _qname(el) -> str:
    q = etree.QName(el)
    if q.namespace in (None, NS['xhtml'], NS['opf'], NS['ncx'], NS['container']):
        return q.localname
    prefix = next((k for k, v in NS.items() if v == q.namespace), None)
    return f'{prefix}:{q.localname}' if prefix else q.localname


def node_xpath(el) -> str:
    """不带命名空间前缀的可读 XPath（同名兄弟只有一个时不写序号）。"""
    parts = []
    while el is not None and isinstance(el.tag, str):
        i, n = _sibling_index(el)
        parts.append(_qname(el) + (f'[{i}]' if n > 1 else ''))
        el = el.getparent()
    return '/' + '/'.join(reversed(parts))


def node_selector(el) -> str:
    """CSS 选择器：优先 #id，其次 class，最后以最近的带 id 祖先为起点加位置序号（guide/07 §6.1）。"""
    def own(e):
        tag = etree.QName(e).localname
        if e.get('id'):
            return f'{tag}#{e.get("id")}', True
        cls = (e.get('class') or '').split()
        return (f'{tag}.' + '.'.join(cls) if cls else tag), False
    s, anchored = own(el)
    if anchored:
        return s
    if '.' not in s:
        i, n = _sibling_index(el)
        if n > 1:
            s += f':nth-of-type({i})'
    anc = el.getparent()
    while anc is not None and isinstance(anc.tag, str):
        if anc.get('id'):
            return f'{own(anc)[0]} {s}'
        if etree.QName(anc).localname == 'body':
            return f'body {s}'
        anc = anc.getparent()
    return s


SNIP = 120


def snippet_of(el, rng: tuple[int, int] | None = None, text: str | None = None) -> str:
    if rng and text is not None:
        a, b = rng
        lo, hi = max(0, a - 20), min(len(text), b + 20)
        return ('…' if lo else '') + text[lo:hi] + ('…' if hi < len(text) else '')
    tag = etree.QName(el).localname
    attrs = ''.join(f' {etree.QName(k).localname}="{v}"' for k, v in el.attrib.items())
    inner = re.sub(r'\s+', ' ', ''.join(el.itertext())).strip()
    s = f'<{tag}{attrs}>{inner}'
    return s if len(s) <= SNIP else s[:SNIP - 1] + '…'


class Rule:
    id: str = ''
    title: str = ''
    order: int = 0
    node_fix = False      # 修复能避开 issue.waived_nodes()，部分豁免时仍可修

    @property
    def meta(self) -> dict:
        return rules_meta()['rules'].get(self.id, {})

    def check(self, book: Book) -> list[Issue]:
        raise NotImplementedError

    def fix(self, book: Book, issues: list[Issue]) -> list[str]:
        """修复给定问题，返回人类可读的修改记录。默认不修。"""
        return []

    def issue(self, severity: str, message: str, file: str | None = None,
              fix_level: str = MANUAL, **data) -> Issue:
        hits = data.pop('hits', None) or []
        return Issue(self.id, severity, message, file, fix_level, data, hits)

    @staticmethod
    def hit(el, rng: tuple[int, int] | None = None, text: str | None = None, fix: dict | None = None) -> Hit:
        """由命中节点生成 Hit；文本类命中另给所在元素的文字和命中区间。"""
        line = el.sourceline if el.sourceline else None
        return Hit(xpath=node_xpath(el), selector=node_selector(el), snippet=snippet_of(el, rng, text),
                   line=line, orig_line=line, range=rng, fix=fix, el=el, text=text)


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


def _check(r: Rule, book: Book, waivers: WaiverSet | None) -> list[Issue]:
    issues = r.check(book)
    if waivers is not None:
        waivers.apply(issues, book)
    return issues


def audit(book: Book, rules: list[Rule] | None = None, waivers: WaiverSet | None = None,
          self_check: bool = True) -> list[Issue]:
    """检测全书。给了豁免时同时标记已豁免的命中，并附上豁免文件自检（STR-024）的结果。"""
    out: list[Issue] = []
    if waivers is not None:
        waivers.reset_counts()
    for r in rules or all_rules():
        out.extend(_check(r, book, waivers))
    if waivers is not None:
        out.extend(waivers.self_check(book, out, usage=self_check))
    return out


@dataclass
class FixReport:
    changes: list[tuple[str, str]] = field(default_factory=list)   # (rule_id, 说明)
    before: list[Issue] = field(default_factory=list)
    after: list[Issue] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)              # 因部分豁免而整条未修的问题 key


def fix(book: Book, levels: set[str] = frozenset({AUTO}),
        rules: list[Rule] | None = None, waivers: WaiverSet | None = None) -> FixReport:
    rules = rules or all_rules()
    rep = FixReport(before=audit(book, rules, waivers))
    for r in rules:
        # 一条规则的修复可能暴露同一规则的新问题（如补了命名空间才看得出缺 head），
        # 所以反复「检测→修复」直到稳定，最多 3 轮
        for _ in range(3):
            todo = []
            for i in _check(r, book, waivers):
                if i.fix_level not in levels or i.status == 'waived':
                    continue
                if i.status == 'partial' and not r.node_fix:
                    if i.key not in rep.skipped:
                        rep.skipped.append(i.key)
                    continue
                todo.append(i)
            if not todo:
                break
            lines = r.fix(book, todo)
            rep.changes.extend((r.id, line) for line in lines)
            if not lines:
                break
    book.flush()
    rep.after = audit(book, rules, waivers)
    return rep
