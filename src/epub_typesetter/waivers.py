"""按书豁免（guide/07 §7）：旁路 JSON 文件的读取、自检（STR-024）与匹配。

豁免不改变检测结果，只给命中打「已豁免」标记；引擎据此跳过对应的自动修复。
定位只用 CSS 选择器、XPath 或文字锚点，不用行号（我们会重新序列化文件，行号随时变化）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import cssselect

from .book import Book
from .engine import ERROR, INFO, MANUAL, WARNING, Hit, Issue, rules_meta

FORMAT_VERSION = 1
SUFFIX = '.typeset-ignore.json'
TOP_KEYS = {'version', 'book', 'renames', 'ignore'}
ENTRY_KEYS = {'id', 'rule', 'file', 'where', 'reason'}
WHERE_KEYS = {'selector', 'xpath', 'anchor'}
ANCHOR_KEYS = {'quote', 'prefix', 'suffix'}
LINE_KEYS = {'line', 'col', 'lines', 'line_no', 'orig_line'}
RULE_RE = re.compile(r'^(?:(?:STR|SEM|STY|TYP|TXT|RES|A11Y)-(?:\d{3}|\*)|EPUBCHECK-[A-Z]{3}-\d{3}[a-z]?)$')
POSITIONAL = re.compile(r':nth-|:first-child|:last-child|\[\d+\]')


class WaiverFileError(ValueError):
    """豁免文件整体无效（JSON 无法解析、版本不支持、未知字段）：命令行退出码 2。"""


def default_path(epub_path: str) -> str:
    return f'{epub_path}{SUFFIX}'


@dataclass
class Waiver:
    id: str
    rule: str
    reason: str
    file: str | None = None
    where: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    hits: int = 0
    pos: int = 1 << 30            # 在文件 ignore 数组里的位置（新加的排最后）

    def to_json(self) -> dict:
        d = {'id': self.id, 'rule': self.rule}
        if self.file:
            d['file'] = self.file
        if self.where:
            d['where'] = self.where
        d['reason'] = self.reason
        return d


def glob_re(pattern: str) -> re.Pattern:
    """shell 风格通配，匹配完整路径：`*`、`?` 不跨目录，`**` 跨目录。"""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
            continue
        if pattern.startswith('**', i):
            out.append('.*')
            i += 2
            continue
        out.append('[^/]*' if c == '*' else '[^/]' if c == '?' else re.escape(c))
        i += 1
    return re.compile(''.join(out) + r'\Z')


class _LocalNameTranslator(cssselect.GenericTranslator):
    """按元素本地名匹配，免得用户在选择器里写命名空间（XHTML 元素都带命名空间）。"""

    def xpath_element(self, selector):
        xp = super().xpath_element(selector)
        if xp.element != '*' and selector.namespace is None:
            # 名字测试写进步骤本身（而不是 add_condition），:nth-of-type 的兄弟计数才能沿用
            xp.element = f"*[local-name() = '{xp.element}']"
        return xp


_CSS = _LocalNameTranslator()


def _norm_xpath(xp: str) -> str:
    return re.sub(r'\[1\]', '', xp.strip().rstrip('/'))


class WaiverSet:
    def __init__(self, entries: list[Waiver] | None = None, book: dict | None = None,
                 renames: dict | None = None, problems: list[tuple[str, str, dict]] | None = None):
        self.entries = entries or []
        self.book = book or {}
        self.renames: dict[str, str | list[str]] = renames or {}
        self.problems = problems or []          # 载入时发现的自检问题：(严重度, 说明, 原条目)
        self.invalid: list[tuple[int, object]] = []  # 无效或重复的原条目（位置, 原文）：写回时原样保留
        self._sel_cache: dict[tuple[int, str, str], set] = {}

    # ---------- 读写 ----------

    @classmethod
    def load(cls, src: str | Path | dict | None) -> 'WaiverSet':
        """读入豁免文件（路径或已解析的 dict）；文件不存在即无豁免。整体无效时抛 WaiverFileError。"""
        if src is None:
            return cls()
        if not isinstance(src, dict):
            p = Path(src)
            if not p.exists():
                return cls()
            try:
                src = json.loads(p.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise WaiverFileError(f'豁免文件不是合法的 JSON：{e}') from None
        return cls.from_dict(src)

    @classmethod
    def from_dict(cls, d: dict) -> 'WaiverSet':
        if not isinstance(d, dict):
            raise WaiverFileError('豁免文件顶层必须是对象')
        if d.get('version') != FORMAT_VERSION:
            raise WaiverFileError(f'不支持的豁免文件版本：{d.get("version")!r}（应为 {FORMAT_VERSION}）')
        unknown = set(d) - TOP_KEYS
        if unknown:
            raise WaiverFileError(f'豁免文件含未知字段：{", ".join(sorted(unknown))}')
        if not isinstance(d.get('ignore', []), list):
            raise WaiverFileError('ignore 必须是数组')
        ws = cls(book=d.get('book') or {}, renames=d.get('renames') or {})
        raws = d.get('ignore', [])
        used_ids = {e.get('id') for e in raws if isinstance(e, dict) and e.get('id')}
        seen: list[dict] = []
        for pos, raw in enumerate(raws):
            problem = ws._check_entry(raw, seen)
            if problem:
                ws.problems.append((problem[0], problem[1], raw if isinstance(raw, dict) else {'entry': raw}))
                ws.invalid.append((pos, raw))
                continue
            wid = raw.get('id')
            if not wid:                                     # 缺省 id 按序补 w-001…，写回时落盘
                wid = next(f'w-{k:03d}' for k in range(1, 10000) if f'w-{k:03d}' not in used_ids)
                used_ids.add(wid)
            w = Waiver(wid, str(raw['rule']).strip().upper(), str(raw['reason']).strip(),
                       raw.get('file') or None, dict(raw.get('where') or {}), raw)
            w.pos = pos
            ws.entries.append(w)
        return ws

    @staticmethod
    def _check_entry(raw, seen: list) -> tuple[str, str] | None:
        """单条豁免的格式检查（guide/07 §7.6），返回 (严重度, 说明)；合格返回 None。"""
        if not isinstance(raw, dict):
            return ERROR, '豁免条目不是对象，已忽略'
        canon = {k: v for k, v in raw.items() if k != 'id'}
        if canon in seen:
            return WARNING, '与前面的条目完全相同，只保留第一条'
        seen.append(canon)
        where = raw.get('where') or {}
        bad = LINE_KEYS & (set(raw) | (set(where) if isinstance(where, dict) else set()))
        if bad:
            return ERROR, f'含行号字段 {", ".join(sorted(bad))}，该条无效；请改用 selector 或 anchor'
        unknown = set(raw) - ENTRY_KEYS
        if not isinstance(where, dict):
            unknown.add('where')
        else:
            unknown |= {f'where.{k}' for k in set(where) - WHERE_KEYS}
            anc = where.get('anchor')
            if 'anchor' in where and (not isinstance(anc, dict) or not anc.get('quote') or set(anc) - ANCHOR_KEYS):
                unknown.add('where.anchor')
        if unknown:
            return ERROR, f'字段无效：{", ".join(sorted(unknown))}，该条无效'
        if not str(raw.get('reason') or '').strip():
            return ERROR, '缺少理由（reason），该条无效'
        rule = str(raw.get('rule') or '').strip().upper()
        if not RULE_RE.match(rule) or ('*' not in rule and not rule.startswith('EPUBCHECK-')
                                       and rule not in rules_meta()['rules']):
            return WARNING, f'规则编号不存在：{rule or "（空）"}，该条无效'
        if where.get('selector'):
            try:
                _CSS.css_to_xpath(where['selector'])
            except cssselect.SelectorError as e:
                return ERROR, f'选择器无法解析：{e}，该条无效'
        return None

    def to_dict(self, renames: dict | None = None) -> dict:
        d = {'version': FORMAT_VERSION}
        if self.book:
            d['book'] = self.book
        r = self.renames if renames is None else renames
        if r:
            d['renames'] = r
        # 有效条目与无效条目按原顺序写回（无效条目原样保留，等用户修改）
        items = [(w.pos, i, w.to_json()) for i, w in enumerate(self.entries)]
        items += [(pos, -1, raw) for pos, raw in self.invalid]
        d['ignore'] = [x for _, _, x in sorted(items, key=lambda t: (t[0], t[1]))]
        return d

    def save(self, path: str | Path, renames: dict | None = None) -> None:
        Path(path).write_text(json.dumps(self.to_dict(renames), ensure_ascii=False, indent=2) + '\n',
                              encoding='utf-8')

    @staticmethod
    def renames_of(book: Book, previous: dict | None = None) -> dict:
        """把本次处理的改名链（Book.origins）合进已有的 renames：原路径 → 当前路径（拆分时为列表）。"""
        out: dict[str, set[str]] = {}
        for cur, olds in book.origins.items():
            for o in olds:
                out.setdefault(o, set()).add(cur)
        for o, cur in (previous or {}).items():                  # 上一轮记录的原路径，接到本轮的新路径上
            curs = [cur] if isinstance(cur, str) else list(cur)
            for c in curs:
                out.setdefault(o, set()).update(out.get(c, {c}))
        return {o: (sorted(c)[0] if len(c) == 1 else sorted(c)) for o, c in sorted(out.items())
                if c != {o}}

    def add(self, rule: str, reason: str, file: str | None = None, where: dict | None = None) -> Waiver:
        raw = {'rule': rule, 'reason': reason}
        if file:
            raw['file'] = file
        if where:
            raw['where'] = where
        problem = self._check_entry(raw, [{k: v for k, v in w.raw.items() if k != 'id'} for w in self.entries])
        if problem:
            raise ValueError(problem[1])
        ids = {w.id for w in self.entries} | {r.get('id') for _, r in self.invalid if isinstance(r, dict)}
        wid = next(f'w-{k:03d}' for k in range(1, 10000) if f'w-{k:03d}' not in ids)
        w = Waiver(wid, rule.strip().upper(), reason.strip(), file or None, dict(where or {}), raw)
        self.entries.append(w)
        return w

    def remove(self, wid: str) -> bool:
        before = len(self.entries)
        self.entries = [w for w in self.entries if w.id != wid]
        return len(self.entries) != before

    # ---------- 匹配 ----------

    def reset_counts(self) -> None:
        for w in self.entries:
            w.hits = 0
        self._sel_cache.clear()

    def _paths(self, book: Book, path: str) -> set[str]:
        """文件的候选路径：当前路径、原输入路径、renames 里记录的历史路径（§7.4）。"""
        cands = set(book.history(path))
        changed = True
        while changed:
            changed = False
            for old, cur in self.renames.items():
                curs = {cur} if isinstance(cur, str) else set(cur)
                if curs & cands and old not in cands:
                    cands.add(old)
                    changed = True
        return cands

    def _file_ok(self, w: Waiver, book: Book, path: str | None) -> bool:
        if not w.file or w.file in ('*', '**'):
            return True
        if path is None:
            return False
        rx = glob_re(w.file)
        return any(rx.match(p) for p in self._paths(book, path))

    def _selected(self, book: Book, path: str, selector: str) -> set:
        key = (id(book), path, selector)
        if key not in self._sel_cache:
            root = book.tree(path).getroot()
            self._sel_cache[key] = set(root.xpath(_CSS.css_to_xpath(selector, prefix='descendant-or-self::')))
        return self._sel_cache[key]

    def _where_ok(self, w: Waiver, book: Book, path: str | None, hit: Hit | None) -> bool:
        if not w.where:
            return True
        if hit is None or hit.el is None or path is None:
            return False                                    # 全书级、无节点的命中只看规则与文件
        if 'selector' in w.where:
            sel = self._selected(book, path, w.where['selector'])
            el = hit.el
            while el is not None and el not in sel:
                el = el.getparent()
            if el is None:
                return False
        if 'xpath' in w.where:
            want, got = _norm_xpath(w.where['xpath']), _norm_xpath(hit.xpath)
            if got != want and not got.startswith(want + '/'):
                return False
        if 'anchor' in w.where and not _anchor_ok(w.where['anchor'], hit):
            return False
        return True

    def apply(self, issues: list[Issue], book: Book) -> None:
        """给命中打豁免标记。没有显式命中的问题补一个隐含命中，使「全部豁免」可判定。"""
        if not self.entries:
            return
        for iss in issues:
            cands = [w for w in self.entries if _rule_ok(w.rule, iss.rule_id) and self._file_ok(w, book, iss.file)]
            if not cands:
                continue
            if not iss.hits:
                iss.hits.append(Hit())
            for h in iss.hits:
                for w in cands:
                    if self._where_ok(w, book, iss.file, h if h.el is not None else None):
                        h.waived, h.waiver_id = True, w.id
                        w.hits += 1
                        break

    # ---------- 自检（STR-024） ----------

    def self_check(self, book: Book, issues: list[Issue], usage: bool = True) -> list[Issue]:
        """豁免文件自身的问题。usage=False 时不报「未命中」「文件不存在」（例如对原书体检、而豁免是针对输出写的）。"""
        meta = rules_meta()['rules'].get('STR-024', {})
        found: list[tuple[str, str, dict]] = list(self.problems)
        ident = (self.book or {}).get('identifier')
        if ident:
            from .book import NS
            ids = [(e.text or '').strip() for e in book.opf.iterfind('opf:metadata/dc:identifier', NS)]
            if ident not in ids:
                found.append((WARNING, f'豁免文件的 book.identifier 与当前书不符：{ident}', {'book': self.book}))
        for w in self.entries:
            if w.where and any(o is not w and o.rule == w.rule and not o.where and (o.file or None) == (w.file or None)
                               for o in self.entries):
                found.append((WARNING, f'{w.id} 冗余：同规则已有不带定位的豁免', w.raw))
            if not w.file or w.file in ('*', '**'):
                if not w.where:
                    found.append((INFO, f'{w.id} 范围是全书，请确认确实要整本豁免 {w.rule}', w.raw))
            if any(POSITIONAL.search(str(w.where.get(k) or '')) for k in ('selector', 'xpath')):
                found.append((INFO, f'{w.id} 的定位含位置序号，重排后容易漂移，建议改用 #id、类名或文字锚点', w.raw))
            if w.rule.startswith('EPUBCHECK-'):
                found.append((INFO, f'{w.id} 豁免的是 epubcheck 消息，epubcheck 仍会照报，不能算零错误', w.raw))
            if not usage:
                continue
            if w.file and w.file not in ('*', '**'):
                rx = glob_re(w.file)
                if not any(rx.match(p) for f in book.files for p in self._paths(book, f)):
                    found.append((INFO, f'{w.id} 的文件模式 {w.file} 对不上任何现存文件', w.raw))
                    continue
            if not w.hits:
                found.append((INFO, f'{w.id} 没有命中任何问题，可以删除', w.raw))
        if not found:
            return []
        sev = min((s for s, _, _ in found), key=lambda s: {ERROR: 0, WARNING: 1, INFO: 2}[s])
        msgs = [m for _, m, _ in found]
        hits = [Hit(snippet=f'{m}  {json.dumps(raw, ensure_ascii=False)}') for _, m, raw in found]
        return [Issue('STR-024', sev, f'豁免文件有 {len(found)} 处需要处理：' + '；'.join(msgs[:3])
                      + ('…' if len(msgs) > 3 else ''), None, MANUAL,
                      {'hint': meta.get('hint', '')}, hits)]


def _rule_ok(pattern: str, rule_id: str) -> bool:
    if pattern.endswith('-*'):
        return rule_id.startswith(pattern[:-1])
    return pattern == rule_id


def _anchor_ok(anchor: dict, hit: Hit) -> bool:
    """在命中元素的文字里找 quote（空白不折叠），用 prefix/suffix 消歧；与命中区间重叠才算。"""
    text = hit.text if hit.text is not None else ''.join(hit.el.itertext())
    q, pre, suf = anchor['quote'], anchor.get('prefix') or '', anchor.get('suffix') or ''
    start = 0
    while (i := text.find(q, start)) >= 0:
        start = i + 1
        if pre and text[max(0, i - len(pre)):i] != pre:
            continue
        if suf and text[i + len(q):i + len(q) + len(suf)] != suf:
            continue
        if hit.range is None or (i < hit.range[1] and hit.range[0] < i + len(q)):
            return True
    return False

