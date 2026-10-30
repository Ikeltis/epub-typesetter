"""大模型判断任务。每个任务只发判断所需的片段，结果写进确认板供用户采纳，不直接改书。

    clusters    段落样式簇的角色（light）：每组若干样例 + 前后文 + 原样式摘要
    structures  已识别的 B 级结构（诗歌、书信、列表…）是否成立（light）
    suggestions C 级建议是否该执行（light）

结果格式（存为项目目录下的 llm.json）：
    {"clusters": {簇键: {"role", "confidence", "reason"}}, "items": {结构或建议键: {"accept", "confidence", "reason"}},
     "usage": {...}, "errors": [...]}
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, Field

from ..semantic import CLUSTER_ROLES, REASSIGNABLE, Analysis, cluster_key
from .client import LLM, ContentBlocked, LLMError

SAMPLES = 8
CLIP = 150

ROLE_TEXT = '''角色（只能选一个）：
- para：正文段落
- quote：引文（大段引用他人文字、文件、书信摘录等，通常原书用缩进或不同字体区分）
- center：居中短行（如分隔用的短句、落款以外的独立短行）
- right：右对齐短行（如署名、日期）
- chapter：章一级标题（「第一章」、独立成章的序言、后记等的标题）
- section：章内的节、小节标题
- meta：版权页的「键：值」信息（书名、作者、出版社、ISBN 等）
- junk：广告、引流、与本书内容无关的文字（「扫码关注」「更多好书」等），会被删除
- other：以上都不是（如注释、图注、诗歌、表格内容），保持程序原判'''

SYSTEM_CLUSTERS = f'''你是中文电子书排版编辑，帮助判断一本 EPUB 里「同一种原书样式」的一组段落在语义上是什么。

程序已经按原书样式（元素、类名、字号、粗体、对齐、缩进）把段落分了组，并给出了它的猜测。你会看到这一组的若干样例（含前后文）、原样式摘要和程序的猜测。
只根据样例的内容和样式判断这一组整体是什么角色；不要改写任何文字。拿不准时给较低的置信度。

{ROLE_TEXT}

置信度 0–1：0.9 以上表示几乎确定；0.6 以下表示只是倾向。理由用一句中文，30 字以内，说出关键依据。'''

SYSTEM_STRUCT = '''你是中文电子书排版编辑。程序在一本 EPUB 里识别出一处特殊结构（诗歌、书信、有序列表、剧本对白、术语表等），
你要判断这处识别是否成立，即这些段落是否真的应该按该结构排版。不要改写任何文字。

判断要点：
- 诗歌：整首或节选的诗、词、曲、歌词，按行排列；散文里偶然出现的整齐句子不算。
- 书信：有称谓、正文、祝颂语或署名的信件；小说对话里带冒号的称呼不算。
- 有序列表：连续编号的条目；注释编号、年份开头的段落不算。
- 剧本对白：「角色名：台词」的戏剧或问答体；访谈中偶尔的问答不算。
- 术语表：「词条：释义」的词汇解释。
- 表格合计行：最后一行是合计、总计。

置信度 0–1；理由用一句中文，30 字以内。'''

KIND_NAMES = {'poem': '诗歌', 'letter': '书信', 'ol': '有序列表', 'item': '中文序号项', 'article': '法规条文',
              's-poem': '诗歌（程序拿不准）', 's-script': '剧本对白', 's-glossary': '术语表（「词：释义」成行文本）',
              's-table': '表格合计行移入表尾'}


class ClusterVerdict(BaseModel):
    role: Literal['para', 'quote', 'center', 'right', 'chapter', 'section', 'meta', 'junk', 'other']
    confidence: float = Field(ge=0, le=1)
    reason: str


class StructVerdict(BaseModel):
    accept: bool
    confidence: float = Field(ge=0, le=1)
    reason: str


def _clip(t: str, n: int = CLIP) -> str:
    return t if len(t) <= n else t[:n] + '…'


def _context(blocks, b) -> str:
    prev = blocks[b.idx - 1] if b.idx > 0 and blocks[b.idx - 1].doc == b.doc else None
    nxt = blocks[b.idx + 1] if b.idx + 1 < len(blocks) and blocks[b.idx + 1].doc == b.doc else None
    lines = []
    if prev is not None:
        lines.append(f'  前文：{_clip(prev.text, 60)}')
    lines.append(f'  【本段】{_clip(b.text)}')
    if nxt is not None:
        lines.append(f'  后文：{_clip(nxt.text, 60)}')
    return '\n'.join(lines)


def _spread(items: list, n: int) -> list:
    """均匀取 n 个样例（不只取开头几个）。"""
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def cluster_jobs(an: Analysis, head_kind: dict) -> list[tuple[str, str]]:
    groups: dict[str, list] = defaultdict(list)
    for b in an.blocks:
        if b.role in REASSIGNABLE or b.attrs.get('force'):
            groups[cluster_key(b)].append(b)
    if not groups:
        return []
    body = max(groups, key=lambda k: sum(len(b.text) for b in groups[k]))
    body_samples = '\n'.join(f'  {_clip(b.text, 60)}' for b in _spread(groups[body], 2))
    jobs = []
    for key, bs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if key == body or len(bs) < 2 and bs[0].role != 'heading':
            continue
        tag, cls, size, bold, align, indent = key.split('|')
        cur = bs[0].role if bs[0].role != 'heading' else (
            'chapter' if head_kind.get(bs[0].idx) in ('chapter', 'part') else 'section')
        style = f'元素 <{tag}>，类名「{cls or "无"}」，字号 {size[1:]} 级（正文为 3），' \
                f'{"粗体，" if bold else ""}{"对齐 " + align + "，" if align else ""}段首缩进 {indent[1:]} 字'
        text = (f'原样式：{style}\n这一组共 {len(bs)} 段，程序猜测：{cur}\n'
                f'作为对照，本书正文段落的样例：\n{body_samples}\n\n这一组的样例：\n'
                + '\n\n'.join(_context(an.blocks, b) for b in _spread(bs, SAMPLES)))
        jobs.append((key, text))
        if len(jobs) >= 80:
            break
    return jobs


def struct_jobs(an: Analysis) -> list[tuple[str, str]]:
    blocks = an.blocks
    members: dict[int, list] = defaultdict(list)
    for b in blocks:
        if b.unit >= 0:
            members[b.unit].append(b)
    jobs = []
    for u, info in an.units.items():
        if info.get('level') != 'B' or info.get('rejected') or info['kind'] not in KIND_NAMES:
            continue
        bs = members.get(u) or []
        if not bs:
            continue
        before = blocks[bs[0].idx - 1] if bs[0].idx > 0 else None
        after = blocks[bs[-1].idx + 1] if bs[-1].idx + 1 < len(blocks) else None
        body = '\n'.join(f'  {_clip(b.text)}' for b in bs[:12]) + (f'\n  …（共 {len(bs)} 段）' if len(bs) > 12 else '')
        text = (f'程序识别为：{KIND_NAMES[info["kind"]]}\n'
                f'前文：{_clip(before.text, 80) if before else "（无）"}\n这些段落：\n{body}\n'
                f'后文：{_clip(after.text, 80) if after else "（无）"}')
        jobs.append((info['key'], text))
    for sg in an.suggestions:
        kind = 's-' + sg['kind']
        if not sg.get('actionable') or kind not in KIND_NAMES:
            continue
        idxs = sg.get('blocks', [])
        bs = [blocks[i] for i in idxs[:12]]
        before = blocks[idxs[0] - 1] if idxs and idxs[0] > 0 else None
        body = '\n'.join(f'  {_clip(b.text)}' for b in bs) + (f'\n  …（共 {len(idxs)} 段）' if len(idxs) > 12 else '')
        text = (f'程序建议按「{KIND_NAMES[kind]}」处理，但把握不够：{sg["text"]}\n'
                f'前文：{_clip(before.text, 80) if before else "（无）"}\n涉及的段落：\n{body}')
        jobs.append((sg['key'], text))
    return jobs


def run(llm: LLM, an: Analysis, head_kind: dict, tasks: set[str], progress=None) -> dict:
    """跑选中的任务，返回 llm.json 的内容。progress(done, total) 用于进度显示。"""
    out = {'clusters': {}, 'items': {}, 'errors': []}
    jobs = []
    if 'clusters' in tasks:
        jobs += [('clusters', k, SYSTEM_CLUSTERS, t, ClusterVerdict) for k, t in cluster_jobs(an, head_kind)]
    if 'structures' in tasks:
        jobs += [('items', k, SYSTEM_STRUCT, t, StructVerdict) for k, t in struct_jobs(an)]
    done = [0]

    def one(job):
        bucket, key, system, text, schema = job
        try:
            v = llm.ask('light', system, text, schema, max_tokens=4000)
        except ContentBlocked:
            return bucket, key, None, None          # 只跳过这一条，数量记在 usage.blocked
        except LLMError as e:
            return bucket, key, None, str(e)
        finally:
            done[0] += 1
            if progress:
                progress(done[0], len(jobs))
        return bucket, key, v, None

    with ThreadPoolExecutor(max_workers=max(1, llm.settings.max_workers)) as pool:
        for bucket, key, v, err in pool.map(one, jobs):
            if err:
                if err not in out['errors']:
                    out['errors'].append(err)
                continue
            if v is not None:
                out[bucket][key] = v.model_dump()
    out['usage'] = llm.usage.to_dict()
    out['models'] = {'light': llm.settings.model_light, 'heavy': llm.settings.model_heavy}
    return out
