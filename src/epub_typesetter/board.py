"""语义确认板（软件设计建议 §4、§6；M2）。

重建一次后，把「程序替用户做了哪些判断」整理成卡片，用户改完再按决定重建：

  clusters     段落样式簇：原样式相同的段落一组，可整组改角色（正文、引文、居中、右对齐、章标题、节标题、删除）
  structures   识别出的结构（诗歌、书信、列表……）：按类别分组，可逐条或整类不接受
  suggestions  C 级建议：默认不执行，勾选后按模板改写；不能执行的只作提示

用户的决定存成 decisions：
  {"version": 1, "clusters": {簇键: 角色}, "kinds": {类别: 是否接受}, "items": {结构或建议的键: 是否接受}}
建议的类别在 kinds/items 里以「s-」开头（如 s-poem），与已识别的结构区分。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .semantic import CLUSTER_ROLES, REASSIGNABLE, Analysis, cluster_key

DECISIONS_VERSION = 1
ROLE_LABELS = {'para': '正文', 'quote': '引文', 'center': '居中短行', 'right': '右对齐', 'chapter': '章标题',
               'section': '节标题', 'junk': '删除', 'meta': '版权信息'}
KIND_LABELS = {'poem': '诗歌', 'letter': '书信', 'ol': '有序列表', 'dl': '定义列表', 'item': '序号项',
               'article': '条文', 'loi': '插图目录', 'lot': '表格目录',
               's-poem': '疑似诗歌', 's-script': '剧本对白', 's-glossary': '术语表成行文本', 's-table': '表格合计行',
               's-loi': '插图目录', 'gloss': '术语表条目', 'script': '剧本'}
MAX_SAMPLES = 3
MAX_ITEMS = 2000


def empty() -> dict:
    return {'version': DECISIONS_VERSION, 'clusters': {}, 'kinds': {}, 'items': {}}


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return empty()
    d = json.loads(p.read_text(encoding='utf-8'))
    out = empty()
    for k in ('clusters', 'kinds', 'items'):
        if isinstance(d.get(k), dict):
            out[k] = d[k]
    return out


def clean(d: dict) -> dict:
    """校验用户提交的决定：只留认识的角色与布尔值。"""
    out = empty()
    for k, v in (d.get('clusters') or {}).items():
        if isinstance(k, str) and v in CLUSTER_ROLES:
            out['clusters'][k] = v
    for part in ('kinds', 'items'):
        for k, v in (d.get(part) or {}).items():
            if isinstance(k, str) and isinstance(v, bool):
                out[part][k] = v
    return out


def _role_of(b, head_kind: dict) -> str:
    if b.role == 'heading':
        return 'chapter' if head_kind.get(b.idx) in ('chapter', 'part') else 'section'
    return b.role


def build(an: Analysis, head_kind: dict, decisions: dict | None = None) -> dict:
    decisions = decisions or empty()
    blocks = an.blocks

    # 1) 段落样式簇：只收用户能整组改角色的块
    groups: dict[str, list] = defaultdict(list)
    for b in blocks:
        if b.role in REASSIGNABLE or b.attrs.get('force'):
            groups[cluster_key(b)].append(b)
    body_key = max(groups, key=lambda k: sum(len(b.text) for b in groups[k]), default=None)
    clusters = []
    for key, bs in groups.items():
        roles = Counter(_role_of(b, head_kind) for b in bs)
        tag, cls, size, bold, align, indent = key.split('|')
        style = [f'<{tag}>' + (f'.{cls.split()[0]}' if cls else ''), f'字号{size[1:]}级']
        style += ['粗体'] if bold else []
        style += [{'center': '居中', 'right': '右对齐', 'left': '左对齐', 'justify': '两端对齐'}.get(align, align)] if align else []
        style += [f'缩进{indent[1:]}字'] if indent != 'i0' else []
        clusters.append({
            'key': key, 'style': ' · '.join(style), 'count': len(bs), 'body': key == body_key,
            'role': roles.most_common(1)[0][0], 'roles': dict(roles),
            'decided': decisions['clusters'].get(key),
            'samples': [{'text': b.text[:80], 'doc': b.doc.rsplit('/', 1)[-1]} for b in bs[:MAX_SAMPLES]],
        })
    # 正文簇最先，其余按数量；只有一两段的杂簇放后面
    clusters.sort(key=lambda c: (not c['body'], -c['count']))

    # 2) 识别出的结构（用户接受的 C 级建议生成的结构不另列，由建议那一条代表）
    members: dict[int, list] = defaultdict(list)
    for b in blocks:
        if b.unit >= 0:
            members[b.unit].append(b)
    kinds: dict[str, dict] = {}
    for u, info in an.units.items():
        if info.get('level') == 'C':
            continue
        kind = info['kind']
        k = kinds.setdefault(kind, {'kind': kind, 'label': KIND_LABELS.get(kind, kind), 'levels': Counter(),
                                    'decided': decisions['kinds'].get(kind), 'items': []})
        k['levels'][info.get('level', 'B')] += 1
        bs = members.get(u) or []
        if len(k['items']) < MAX_ITEMS:
            k['items'].append({
                'key': info['key'], 'level': info.get('level', 'B'), 'accepted': not info.get('rejected'),
                'decided': decisions['items'].get(info['key']),
                'doc': (bs[0].doc if bs else info.get('doc', '')).rsplit('/', 1)[-1],
                'lines': [b.text[:60] for b in bs[:4]] if bs else info.get('lines', []),   # 被拒绝的已还原，用存下的样例
                'count': len(bs) or info.get('count', 0),
            })
    for k in kinds.values():
        k['levels'] = dict(k['levels'])
        k['total'] = sum(k['levels'].values())

    # 3) C 级建议
    sugg = []
    for sg in an.suggestions:
        kind = 's-' + sg['kind']
        sugg.append({
            'key': sg.get('key'), 'kind': kind, 'label': KIND_LABELS.get(kind, sg['kind']), 'text': sg['text'],
            'doc': sg['doc'].rsplit('/', 1)[-1], 'actionable': sg.get('actionable', False),
            'applied': bool(sg.get('applied')),
            'decided': decisions['items'].get(sg.get('key')) if sg.get('key') else None,
            'lines': [blocks[i].text[:60] for i in sg.get('blocks', [])[:4]],
        })
    return {'clusters': clusters, 'roles': [{'value': r, 'label': ROLE_LABELS[r]} for r in CLUSTER_ROLES],
            'structures': sorted(kinds.values(), key=lambda k: -k['total']), 'suggestions': sugg}
