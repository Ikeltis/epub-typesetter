"""表格结构规范化（guide/04 §4.13），重建与规则 SEM-013 共用。"""
from __future__ import annotations

import re

from lxml import etree

from .xhtml import X

SECTIONS = (X + 'thead', X + 'tbody', X + 'tfoot')
NUMERIC = re.compile(r'^[+\-−–]?[¥$€£]?[\d,，.．]+\s*[%％万亿千元]?$|^[—–-]$')
PRESENTATIONAL = ('style', 'width', 'height', 'bgcolor', 'border', 'cellpadding', 'cellspacing', 'align', 'valign',
                  'frame', 'rules', 'summary', 'class')


def bare_rows(t: etree._Element) -> list:
    return [c for c in t if c.tag == X + 'tr']


def wrap_bare_rows(t: etree._Element) -> int:
    """table 的直接子元素 tr 包进 tbody（连续的一段包一个），返回包了几行（04 4.13.1.1）。"""
    n = 0
    group = None
    for c in list(t):
        if c.tag == X + 'tr':
            if group is None:
                group = etree.Element(X + 'tbody')
                c.addprevious(group)
            group.append(c)          # append 会把 c 从 table 移走，tail 跟着走
            n += 1
        elif isinstance(c.tag, str):
            group = None
    return n


def thead_td_to_th(t: etree._Element) -> int:
    n = 0
    for thead in t.iter(X + 'thead'):
        for td in thead.iter(X + 'td'):
            td.tag = X + 'th'
            td.set('scope', 'col')
            n += 1
    return n


def promote_header(t: etree._Element) -> bool:
    """全表没有 th、首行像表头（每格非空、短、不是数字）时，首行提升为 thead 的 th（04 4.13.1.2）。"""
    if t.find('.//' + X + 'th') is not None or t.find(X + 'thead') is not None:
        return False
    rows = t.findall('.//' + X + 'tr')
    if len(rows) < 2:
        return False
    cells = [c for c in rows[0] if c.tag in (X + 'td', X + 'th')]
    texts = [''.join(c.itertext()).strip() for c in cells]
    if len(cells) < 2 or not all(texts) or any(len(x) > 16 or NUMERIC.match(x) for x in texts) \
            or any(c.find('.//' + X + 'img') is not None for c in cells):
        return False
    body = rows[0].getparent()
    thead = etree.Element(X + 'thead')
    t.insert(_section_pos(t), thead)
    thead.append(rows[0])
    for c in cells:
        c.tag = X + 'th'
        c.set('scope', 'col')
    if body is not t and body.tag == X + 'tbody' and not len(body):
        t.remove(body)
    return True


def _section_pos(t) -> int:
    """thead 的位置：caption、colgroup 之后。"""
    k = 0
    for i, c in enumerate(t):
        if c.tag in (X + 'caption', X + 'colgroup', X + 'col'):
            k = i + 1
    return k


def mark_numeric_columns(t: etree._Element) -> int:
    """数字占多数（≥2/3）的列，td 加 num 类（04 4.13.1.7）。"""
    rows = [r for s in t.iter(X + 'tbody') for r in s.findall(X + 'tr')]
    cols: dict[int, list] = {}
    for r in rows:
        k = 0
        for c in r:
            if c.tag not in (X + 'td', X + 'th'):
                continue
            cols.setdefault(k, []).append(c)
            k += int(c.get('colspan') or 1) if (c.get('colspan') or '1').isdigit() else 1
    n = 0
    for cells in cols.values():
        texts = [''.join(c.itertext()).strip() for c in cells if c.tag == X + 'td']
        filled = [x for x in texts if x]
        if len(filled) >= 2 and sum(bool(NUMERIC.match(x)) for x in filled) * 3 >= 2 * len(filled):
            for c in cells:
                if c.tag == X + 'td':
                    cls = (c.get('class') or '').split()
                    if 'num' not in cls:
                        c.set('class', ' '.join(cls + ['num']))
                        n += 1
    return n


def column_count(t: etree._Element) -> int:
    return max((sum(int(c.get('colspan')) if (c.get('colspan') or '').isdigit() else 1
                    for c in r if c.tag in (X + 'td', X + 'th')) for r in t.iter(X + 'tr')), default=0)


def clean_presentation(t: etree._Element) -> None:
    """去掉表现型属性与内联样式，外观交给主题（num 类保留）。"""
    for el in t.iter():
        if not isinstance(el.tag, str):
            continue
        keep_num = 'num' in (el.get('class') or '').split()
        for k in PRESENTATIONAL:
            el.attrib.pop(k, None)
        if keep_num:
            el.set('class', 'num')


def rebuild_table(t: etree._Element) -> list[str]:
    """重建时的完整规范化，返回做了什么（写进重建日志）。"""
    log = []
    clean_presentation(t)
    if wrap_bare_rows(t):
        log.append('裸 tr 包进 tbody')
    if thead_td_to_th(t):
        log.append('thead 内 td 改 th')
    if promote_header(t):
        log.append('首行提升为表头')
    mark_numeric_columns(t)
    ncol = column_count(t)
    cls = ['compact'] if ncol > 6 else ['table-narrow'] if ncol == 2 else []
    if cls:
        t.set('class', ' '.join(cls))
    return log
