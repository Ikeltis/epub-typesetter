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

from ..semantic import (CLUSTER_ROLES, MATTERS, REASSIGNABLE, Analysis, block_keys, cluster_key, figure_images,
                        _local)
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
- 广告、引流：下载站、公众号、扫码、书友群、「更多好书」之类与本书内容无关的推广；
  书本身的拓展阅读、参考链接、出处网址、小说情节里的网址都不算广告，应判不成立（删了会丢正文）。

置信度 0–1；理由用一句中文，30 字以内。'''

KIND_NAMES = {'poem': '诗歌', 'letter': '书信', 'ol': '有序列表', 'item': '中文序号项', 'article': '法规条文',
              's-poem': '诗歌（程序拿不准）', 's-script': '剧本对白', 's-glossary': '术语表（「词：释义」成行文本）',
              's-table': '表格合计行移入表尾', 'junk': '广告、引流页（整页删除）',
              's-ad': '夹在正文里的广告行（删除）'}


SYSTEM_HEADS = '''你是中文图书的结构编辑。下面是一本 EPUB 里程序识别出的全部标题（按书中顺序），每条带编号、所在文件、程序判定的级别；
章一级的标题后面附有该章开头的一两句正文。请检查整本书的标题层级与辅文类型，只列出你认为需要改的条目。

级别：
- part：部、卷、编、篇（下面再分章）
- chapter：章、回，以及独立成章的前言、序、后记、附录等
- section：章内的节
- subsection：节内的小节
- para：其实不是标题（如正文里的短句、图注、诗题被误认作标题）

辅文类型（只给章一级的条目标，正文章节不标）：preface 前言/序/自序/译序、foreword 他人写的序/推荐序、introduction 导言/引言、
prologue 序幕/楔子、epilogue 尾声/结语（属正文）、afterword 后记/跋（属后置部分）、acknowledgments 致谢、appendix 附录、
bibliography 参考文献、glossary 术语表、dedication 献辞、epigraph 题词、copyright 版权页。

要求：
- 层级要连贯：不能没有章就出现节；同一类标题（如所有「第X章」）级别一致；
- 拿不准的不要列；不改写任何标题文字；
- 每条给置信度 0–1 和一句 30 字以内的理由。'''


class HeadChange(BaseModel):
    n: int = Field(description='标题编号')
    kind: Literal['part', 'chapter', 'section', 'subsection', 'para']
    matter: Literal['', 'preface', 'foreword', 'introduction', 'prologue', 'epilogue', 'afterword', 'acknowledgments',
                    'appendix', 'bibliography', 'glossary', 'dedication', 'epigraph', 'copyright'] = ''
    confidence: float = Field(ge=0, le=1)
    reason: str


class HeadReview(BaseModel):
    changes: list[HeadChange]


SYSTEM_ALT = '''你为中文电子书里的插图写替代文字（alt），供视障读者用读屏软件「听」这张图。

要求（规范 04 4.11.2）：
- 用一句完整的中文描述画面本身：画了什么、谁、在做什么、图表的主要信息；以句号结尾；一般 15–60 字；
- 不写「图片」「插图」「这张图」之类的开头，不写图在书里的位置；
- 不要照抄图注（图注会被单独读出）；可以补充图注没说的画面内容；
- 图里有文字且是重点（如书影、标语、图表标题）就写出关键文字；
- 纯装饰（花纹、分隔线、章首装饰图）标 decorative=true，alt 留空。
置信度 0–1。'''

MAX_IMAGES = 400
MIN_SIDE = 120


class AltDraft(BaseModel):
    alt: str
    decorative: bool
    confidence: float = Field(ge=0, le=1)


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


def _image_block(data: bytes) -> dict | None:
    """缩到长边 1024 像素的 JPEG（省 token）；太小的（装饰、图片字）不发。"""
    import base64
    import io

    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return None
    if max(im.size) < MIN_SIDE:
        return None
    im = im.convert('RGB')
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=80)
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                                        'data': base64.standard_b64encode(buf.getvalue()).decode()}}


def alt_jobs(book, an: Analysis) -> list[tuple[str, list, dict]]:
    """需要描述的插图：alt 为空、是文件名，或与图注一字不差（04 4.11.2.5、4.11.2.7、4.11.2.8），且不是图片字。
    返回 (图片键, 内容块, 附带信息)。"""
    import re
    from ..rules.a11y import FILENAME_ALT
    blocks = an.blocks
    jobs = []
    same = lambda a, c: re.sub(r'\s', '', a) == re.sub(r'\s', '', c)
    for key, b, img, path in figure_images(book, blocks):
        if 'glyph' in (img.get('class') or ''):
            continue
        cap = next((x.text for x in blocks[b.idx + 1:b.idx + 4] if x.role == 'caption' and x.group == b.idx), '')
        if _local(b.el.tag) == 'figure':
            fc = b.el.find('.//{http://www.w3.org/1999/xhtml}figcaption')
            cap = ''.join(fc.itertext()).strip() if fc is not None else cap
        alt = (img.get('alt') or '').strip()
        if alt and not FILENAME_ALT.search(alt) and not (cap and same(alt, cap)):
            continue                                   # 已有像样的描述
        if path not in book.files or not re.search(r'\.(jpe?g|png|gif|webp)$', path, re.I):
            continue
        image = _image_block(book.files[path])
        if image is None:
            continue
        prev = next((x.text for x in reversed(blocks[max(0, b.idx - 3):b.idx]) if x.doc == b.doc and x.text), '')
        text = (f'图注：{_clip(cap, 120) or "（无）"}\n图前的文字：{_clip(prev, 100) or "（无）"}')
        jobs.append((key, [image, {'type': 'text', 'text': text}],
                     {'path': path, 'caption': cap[:80], 'old_alt': alt[:80]}))
        if len(jobs) >= MAX_IMAGES:
            break
    return jobs


MAX_HEADS = 600


def heads_job(an: Analysis, head_kind: dict) -> tuple[str, list] | None:
    """全部标题一次发给重型模型（层级要通盘看）。返回 (输入文字, 编号 → 块)。"""
    blocks = an.blocks
    heads = [b for b in blocks if b.role == 'heading'][:MAX_HEADS]
    if len(heads) < 2:
        return None
    lines = []
    for n, b in enumerate(heads, 1):
        kind = head_kind.get(b.idx) or 'sub'
        cur = {'part': 'part', 'chapter': 'chapter'}.get(kind) or ('subsection' if b.level >= 3 else 'section')
        line = f'{n}. [{cur}] {_clip(b.text, 40)}  （{b.doc.rsplit("/", 1)[-1]}）'
        if cur in ('chapter', 'part'):
            after = [x for x in blocks[b.idx + 1:b.idx + 4] if x.doc == b.doc and x.role not in ('heading', 'figure')]
            if after:
                line += f'\n    开头：{_clip(after[0].text, 50)}'
        lines.append(line)
    return '\n'.join(lines), heads


def run(llm: LLM, an: Analysis, head_kind: dict, tasks: set[str], progress=None, book=None) -> dict:
    """跑选中的任务，返回 llm.json 的内容。progress(done, total) 用于进度显示。"""
    out = {'clusters': {}, 'items': {}, 'errors': []}
    jobs = []
    if 'clusters' in tasks:
        jobs += [('clusters', k, SYSTEM_CLUSTERS, t, ClusterVerdict) for k, t in cluster_jobs(an, head_kind)]
    if 'structures' in tasks:
        jobs += [('items', k, SYSTEM_STRUCT, t, StructVerdict) for k, t in struct_jobs(an)]
    alt_info = {}
    if 'alts' in tasks and book is not None:
        for key, content, info in alt_jobs(book, an):
            alt_info[key] = info
            jobs.append(('alts', key, SYSTEM_ALT, content, AltDraft))
        out['alts'] = {}
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

    if 'heads' in tasks:                       # 重型模型，单独一次
        job = heads_job(an, head_kind)
        out['heads'] = {}
        if job is not None:
            text, heads = job
            keys = block_keys(an.blocks)
            try:
                r = llm.ask('heavy', SYSTEM_HEADS, text, HeadReview, max_tokens=32000)
            except ContentBlocked:
                r = None
            except LLMError as e:
                out['errors'].append(str(e))
                r = None
            for ch in (r.changes if r else []):
                if 1 <= ch.n <= len(heads):
                    out['heads'][keys[heads[ch.n - 1].idx]] = ch.model_dump(exclude={'n'})
    with ThreadPoolExecutor(max_workers=max(1, llm.settings.max_workers)) as pool:
        for bucket, key, v, err in pool.map(one, jobs):
            if err:
                if err not in out['errors']:
                    out['errors'].append(err)
                continue
            if v is not None:
                out[bucket][key] = v.model_dump()
                if bucket == 'alts':
                    from ..board import clean_alt
                    out[bucket][key].update(alt_info[key], alt='' if v.decorative else clean_alt(v.alt))
    out['usage'] = llm.usage.to_dict()
    out['models'] = {'light': llm.settings.model_light, 'heavy': llm.settings.model_heavy}
    return out
