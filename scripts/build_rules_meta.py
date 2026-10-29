"""从 guide/07_质检清单.md 提取每条规则的元数据，生成 src/epub_typesetter/rules_meta.json。

规则的说明、严重度、修复等级、规范条目、修改提示只在规范里写一次；引擎运行时从这里读。
改规则请先改 guide/07，再运行：python3 scripts/build_rules_meta.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
G07 = (ROOT / 'guide/07_质检清单.md').read_text(encoding='utf-8')
ROW = re.compile(r'^\| ((?:STR|SEM|STY|TYP|TXT|RES|A11Y)-\d{3}) ·(P\d) \|(.*)\|\s*$')


def cells(rest: str) -> list[str]:
    # 按未转义的 | 切分（单元格里的 \| 是内容）
    return [c.strip().replace('\\|', '|') for c in re.split(r'(?<!\\)\|', rest)]


def spec_list(s: str) -> list[str]:
    s = s.strip()
    if not s or s in ('—', '-'):
        return []
    out = []
    for part in re.split(r'[；;]', s):
        part = part.strip()
        m = re.match(r'^(0\d)\s*(.*)$', part)
        if not m:
            if part:
                out.append(part)
            continue
        doc, refs = m.group(1), m.group(2)
        for r in re.split(r'[、，,]', refs):
            r = r.strip()
            if r:
                out.append(f'{doc} {r}')
    return out


def short_title(desc: str) -> str:
    """说明的第一句（到第一个「：」或「；」），去掉 Markdown 记号，作为简短标题。"""
    t = re.split(r'[：；]', desc, maxsplit=1)[0]
    t = re.sub(r'`([^`]*)`', r'\1', t).replace('**', '')
    return t[:40]


meta: dict[str, dict] = {}
for line in G07.splitlines():
    m = ROW.match(line)
    if not m:
        continue
    rid, prio, rest = m.groups()
    c = cells(rest)
    if len(c) < 4:
        continue
    desc, sev, fix, spec = c[0], c[1], c[2], c[3]
    meta[rid] = {'priority': prio, 'title': short_title(desc), 'description': desc,
                 'severity': sev, 'fix_level': fix, 'spec': spec_list(spec), 'hint': ''}

for m in re.finditer(r'^\*\*((?:STR|SEM|STY|TYP|TXT|RES|A11Y)-\d{3})\*\*\n(.*?)(?=^\*\*[A-Z0-9]+-\d{3}\*\*|^#|\Z)',
                     G07, re.M | re.S):
    rid, body = m.group(1), m.group(2)
    h = re.search(r'^- 修改提示[：:](.*)$', body, re.M)
    if rid in meta and h:
        meta[rid]['hint'] = h.group(1).strip()

ver = re.search(r'版本 (\d+\.\d+\.\d+)', G07)
out = {'spec_version': ver.group(1) if ver else '', 'rules': meta}
dst = ROOT / 'src/epub_typesetter/rules_meta.json'
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
missing = [k for k, v in meta.items() if not v['hint']]
print(f'{len(meta)} 条规则，缺修改提示 {len(missing)} 条 {missing[:5]}')
