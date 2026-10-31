"""成组结构识别（M2，guide/04 §4.7–4.11、4.13、4.19 的「识别信号」）。

在 semantic.analyze 判完单块角色之后运行，给块打上 unit（组号）与 part（组内角色）：

  诗歌 poem        A：原书已标诗（class 含 poem/stanza/verse，或 z3998:poem 等）；
                   B：规整五言、七言，合计 ≥4 句，前有引出语（以冒号结尾）或诗题；
                   其余规整句只记建议（C）。
  书信 letter      称谓 + 祝颂语/署名/日期中至少一项（B）。
  列表 ol          阿拉伯数字序号段连续 ≥3 且序号连续（B）；dl 原样恢复为定义列表。
  项、条文         中文序号段（（一）、一、、①）→ p.item；「第X条」→ p.article（A）。
  插图/表格目录    标题命中且 ≥3 条（A）。
  表题、表注       紧贴表格的「表X…」「注：」段。
  术语表           原书 dl 在术语表标题下 → dl.glossary；「词：释义」成行文本只建议。
  剧本对白         只建议（C，04 §4.9 识别信号）。
  广告             整页广告（semantic 第 7 步判定）列为结构，默认删除、可逐页保留；
                   夹在正文里的零散广告行只建议（C）。

置信度只有 A、B 自动改写；C 写进 Analysis.suggestions，由报告展示、用户确认。

确认板（board.py）：每个结构与建议有稳定的 key（类别 + 文件 + 首块文字摘要 + 序号），
用户的取舍在 apply_decisions 里落地——拒绝的结构还原成原角色，接受的建议按模板改写。
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from .book import NS, Book
from .rules.text import indent_width
from .xhtml import X

EPUB_TYPE = '{%s}type' % NS['epub']
PUNCT = '，。？！；、：'
_WS = ' \u3000\u00a0\u2002\u2003'
_QUOTES = '“”‘’「」『』"\''
_NOTE_TAIL = re.compile(r'(\[\d{1,3}\]|［\d{1,3}］|〔\d{1,3}〕|[①-⑳]|\d{1,3})+$')
POEM_HINT = re.compile(r'poem|stanza|verse|shige|shici|\bshi\b|\bci\b|gatha', re.I)
INTRO_END = re.compile(r'[：:]\s*$')

SALUTATION = re.compile(r'^[^，。！？；\s]{1,16}[：:]$')
ADDRESS = re.compile(r'^(亲爱的|尊敬的|敬爱的)|先生|兄|弟|姊|姐|妹|君|女士|夫人|小姐|同志|老师|教授|吾儿|儿|爸|妈|父亲|母亲|'
                     r'大人|院长|校长|足下|左右|赐鉴|钧鉴|台鉴|惠鉴|大鉴|雅鉴|如晤|见字|吾爱|宝贝|阁下|诸位|同学')
VALEDICTION = re.compile(r'^(此致|专此|匆此|即颂|顺颂|并颂|敬颂|此布|谨此|肃此|草此|余容|祝你|祝您|祝)')
CLOSING = re.compile(r'^(敬礼|道安|日安|时祺|近安|大安|台安|文安|研安|教安|著安|春安|夏安|秋安|冬安|俪安|近祺|旅安|'
                     r'健康|平安|快乐|顺利|安好)[！!。]?$')
SIGN_WORD = re.compile(r'(谨上|敬上|顿首|拜上|手书|手启|启上|谨启|谨颂|敬启|上$|启$|拜$)')
DATE = re.compile(r'^(\d{4}年)?\d{1,2}月\d{1,2}日$|^([〇一二三四五六七八九十零]+年)?[一二三四五六七八九十]+月[一二三四五六七八九十廿卅]+日$')
SPEECH = re.compile(r'说|道|问|曰|笑|喊|叫|答|写|告诉|表示|指出|认为|如下|是')
POSTSCRIPT = re.compile(r'^(又及|再启|再及|追启|再者|附[：:]|附言|P\.?\s?S)')

OL_NUM = re.compile(r'^(\d{1,3})[.．、)）](?!\d)\s*')
CN_ITEM = re.compile(r'^(（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|[一二三四五六七八九十]+、|[①-⑳])')
ARTICLE = re.compile(r'^(第[0-9零〇一二三四五六七八九十百千]+条)[ \t　]*')
LOI_TITLE = re.compile(r'^(插图|图片|图版|彩图|图)(目录|目次|索引|一览)$')
LOT_TITLE = re.compile(r'^(表格|表)(目录|目次|索引|一览)$')
GLOSSARY_TITLE = re.compile(r'^(术语表|名词解释|词汇表|译名对照表?|人名对照表?|名词对照表?|术语)$')
TABLE_CAPTION = re.compile(r'^(表|table)\s*[\d一二三四五六七八九十]', re.I)
TABLE_NOTE = re.compile(r'^注[：:]')
DIALOGUE = re.compile(r'^([^，。！？：:\s（(“”「」]{1,6})[：:　]\S')
STAGE = re.compile(r'[（(〔［].+[）)〕］]')
TERM_LINE = re.compile(r'^([^，。！？：:\s]{1,12})[：:—]+\S')

PLAIN = ('para', 'quote', 'center', 'right')
LISTABLE = ('para', 'quote')                 # 引文里的序号段同样成列表


def _vtext(b) -> str:
    """块的期望文字：已去掉配上的注号（semantic 第 5 步设的 verify），否则原文。"""
    return b.verify if b.verify is not None else b.text


def _ref_labels(ctx, el) -> list[str]:
    return [''.join(a.itertext()) for a in el.iter(X + 'a') if id(a) in ctx.ref_ids]


def _local(el) -> str:
    return el.tag.rsplit('}', 1)[-1] if isinstance(el.tag, str) else ''


def _clean(t: str) -> str:
    return re.sub(r'[\s　]', '', t).strip(_QUOTES)


def classical_len(t: str) -> int:
    """规整诗句：去掉引号、注号后按标点切成分句，各分句同为 5 或 7 字，1–4 个分句。返回分句字数，否则 0。"""
    t = _NOTE_TAIL.sub('', _clean(t))
    clauses = [c for c in re.split('[，。？！；：]', t) if c]     # 诗句里不用顿号；带顿号的多半是散文
    if '、' in t or not clauses or len(clauses) > 4 or not re.search('[，。？！；]$', t):
        return 0
    lens = {len(c) for c in clauses}
    if len(lens) != 1 or lens.pop() not in (5, 7):
        return 0
    if not all(re.fullmatch(r'[㐀-鿿豈-﫿]+', c) for c in clauses):
        return 0
    return len(clauses[0])


def clause_count(t: str) -> int:
    return len([c for c in re.split(f'[{PUNCT}]', _NOTE_TAIL.sub('', _clean(t))) if c])


def br_lines(el) -> list[str]:
    """块内按 <br/> 切出的各行文字（空行用空串表示，节界）。"""
    lines, cur = [], [el.text or '']
    for d in el.iterdescendants():
        if not isinstance(d.tag, str):
            continue
        if d.tag == X + 'br':
            lines.append(''.join(cur))
            cur = []
        elif d.text:
            cur.append(d.text)
        if d.tail:
            cur.append(d.tail)
    lines.append(''.join(cur))
    return [re.sub(r'[ \t\r\n]+', ' ', x).strip(' ') for x in lines]


def _hint(el) -> bool:
    cur, k = el, 0
    while cur is not None and k < 3 and isinstance(cur.tag, str):
        if POEM_HINT.search(cur.get('class') or '') or re.search(r'z3998:(poem|verse|song|hymn)', cur.get(EPUB_TYPE) or ''):
            return True
        cur, k = cur.getparent(), k + 1
    return False


class _Ctx:
    def __init__(self, book: Book, an):
        self.book, self.an, self.blocks = book, an, an.blocks
        self.next_unit = 0
        self._main: dict[str, tuple[str, float]] = {}
        self._keys: Counter = Counter()
        self.orig = {b.idx: b.role for b in an.blocks}       # 识别前的角色：用户拒绝某个结构时还原
        self.ref_ids = {id(a) for refs in an.noterefs.values() for a in refs}

    def key(self, kind: str, b) -> str:
        """稳定键：同一本原书每次分析都一样，确认板的决定靠它对上。"""
        base = f'{kind}:{b.doc}:{hashlib.sha1(b.text.encode()).hexdigest()[:8]}'
        self._keys[base] += 1
        return base if self._keys[base] == 1 else f'{base}#{self._keys[base]}'

    def unit(self, kind: str, first=None, **info) -> int:
        u = self.next_unit
        self.next_unit += 1
        self.an.units[u] = {'kind': kind, 'key': self.key(kind, first) if first is not None else f'{kind}:{u}', **info}
        return u

    def suggest(self, kind: str, b, text: str, blocks: list | None = None, **data) -> None:
        """C 级建议。给了 blocks 的可以在确认板上勾选执行，否则只是提示。"""
        self.an.suggestions.append({'kind': kind, 'doc': b.doc, 'text': text, 'key': self.key(f's-{kind}', b),
                                    'actionable': blocks is not None,
                                    'blocks': [x.idx for x in blocks or []], **data})

    def main_class(self, doc: str) -> str:
        if doc not in self._main:
            cls = Counter(b.el.get('class') or '' for b in self.blocks if b.doc == doc and b.role == 'para')
            ind = Counter(b.indent for b in self.blocks if b.doc == doc and b.role == 'para')
            self._main[doc] = (cls.most_common(1)[0][0] if cls else '', ind.most_common(1)[0][0] if ind else 0)
        return self._main[doc][0]

    def main_indent(self, doc: str) -> float:
        self.main_class(doc)
        return self._main[doc][1]

    def nxt(self, b, k=1):
        j = b.idx + k
        return self.blocks[j] if 0 <= j < len(self.blocks) and self.blocks[j].doc == b.doc else None


# ---------- 诗歌 ----------

def _poem_lines(b) -> list[tuple[str, float]]:
    """一块里的诗行 (文字, 缩进字宽)：有 <br/> 按 br 切，否则整块一行。空串表示节界。"""
    if b.el.find('.//' + X + 'br') is None:
        return [(b.text.strip(_WS), b.indent)]
    out = []
    for ln in br_lines(b.el):
        m = re.match(r'^[\u3000\u00a0\u2002\u2003]+', ln)
        w = indent_width(m.group(0)) if m else 0
        out.append((ln.strip(_WS), w))
    while out and not out[-1][0]:
        out.pop()
    while out and not out[0][0]:
        out.pop(0)
    return out


def _poem_title(ctx, first) -> tuple:
    """诗前的诗题、作者块（可无）。"""
    title = author = None
    prev = ctx.nxt(first, -1)
    if prev is not None and prev.role in PLAIN and prev.unit < 0 and len(prev.text) <= 8 \
            and re.fullmatch(r'[〔［\[(（]?[一-鿿]{0,3}[〕］\])）]?[一-鿿·]{2,5}', prev.text) \
            and (prev.align in ('center', 'right') or prev.size < 3):
        author, prev = prev, ctx.nxt(prev, -1)
    if prev is not None and prev.role in PLAIN and prev.unit < 0 and len(prev.text) <= 16 \
            and not re.search(r'[，。！？；：:]', prev.text) \
            and (prev.align == 'center' or prev.bold or re.fullmatch(r'《[^》]+》|（[一二三四五六七八九十]+）|其[一二三四五六七八九十]+',
                                                                    prev.text)):
        title = prev
    if title is None:
        author = None          # 只有作者行、没有诗题：多半是正文短行，不认
    return title, author


def detect_poems(ctx: _Ctx) -> None:
    blocks = ctx.blocks
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.role not in PLAIN or b.unit >= 0:
            i += 1
            continue
        hinted = _hint(b.el)
        lines = _poem_lines(b)
        L = {classical_len(t) for t, _ in lines if t} if lines else set()
        if not hinted and (len(L) != 1 or 0 in L):
            i += 1
            continue
        # 连续的诗行块：同一文件、同为原书标诗，或同字数规整句
        run = [b]
        j = i + 1
        while j < len(blocks):
            c = blocks[j]
            if c.doc != b.doc or c.role not in PLAIN or c.unit >= 0:
                break
            cl = _poem_lines(c)
            if hinted:
                if not _hint(c.el):
                    break
            else:
                cL = {classical_len(t) for t, _ in cl if t}
                if cL != L:
                    break
            run.append(c)
            j += 1
        n_clauses = sum(clause_count(t) for c in run for t, _ in _poem_lines(c) if t)
        title, author = _poem_title(ctx, run[0])
        prev = ctx.nxt(run[0], -1) if title is None else ctx.nxt(title, -1)
        while prev is not None and prev.role in ('figure', 'caption', 'source'):   # 引出语与诗之间夹了插图
            prev = ctx.nxt(prev, -1)
        intro = prev is not None and (bool(INTRO_END.search(prev.text)) or prev.role == 'poem')
        # 原书给诗行单独的样式：类名不同于本文件正文的主流类名，或缩进比正文深
        styled = all((c.el.get('class') or '') != ctx.main_class(c.doc) for c in run) or \
            all(c.indent > ctx.main_indent(c.doc) for c in run)
        if hinted:
            level = 'A'
        elif n_clauses >= 4 and (intro or title is not None or styled):
            level = 'B'
        else:
            if n_clauses >= 4:
                ctx.suggest('poem', b, f'疑似诗歌（规整{next(iter(L))}言，前无引出语或诗题）：{b.text[:30]}', run,
                            title=title.idx if title is not None else None)
            i = j
            continue
        make_poem(ctx, run, title, author, level, hinted)
        i = j


def make_poem(ctx: _Ctx, run: list, title, author, level: str, hinted: bool = False) -> int:
    """把一串诗行块（及可选的诗题、作者、出处）定为一首诗（04 §4.7）。"""
    all_lines = [(t, w) for c in run for t, w in _poem_lines(c)]
    texts = [t for t, _ in all_lines if t]
    base = min((w for t, w in all_lines if t), default=0)
    indents = [min(3, int(-(-(w - base) // 2))) if t else 0 for t, w in all_lines]
    lens = [len(_clean(t)) for t in texts]
    cls = ' '.join((c.el.get('class') or '') for c in run).lower()
    if any(indents) or 'left' in cls:
        layout = 'poem-left'
    elif 'center' in cls or (len(texts) >= 2 and max(lens) - min(lens) <= 1 and max(lens) <= 20):
        layout = 'poem-center'
    else:
        layout = 'poem-left'
    whole = title is not None or hinted or len(texts) >= 4
    attribution = None
    after = ctx.nxt(run[-1])
    if after is not None and after.role in PLAIN and after.unit < 0 and len(after.text) <= 40 \
            and re.match(r'^[—－-]{1,2}', after.text):
        attribution = after
    u = ctx.unit('poem', run[0], level=level, layout=layout, type='z3998:poem' if whole else 'z3998:verse',
                 container='div' if title is not None else 'blockquote', lines=len(texts))
    k = 0
    for c in run:
        c.role, c.unit, c.part = 'poem', u, 'lines'
        n = len(_poem_lines(c))
        c.attrs['indents'] = indents[k:k + n]
        c.reason = f'诗歌（{level}）'
        if n > 1 or c.el.find('.//' + X + 'br') is not None:   # 按 br 拆行后，行首缩进空格去掉
            v = ''.join(t for t, _ in _poem_lines(c))
            for lab in _ref_labels(ctx, c.el):               # 配上的注号会换成新编号
                i = v.rfind(lab)
                v = v[:i] + v[i + len(lab):] if i >= 0 else v
            c.verify = v
        k += n
    for blk, part in ((title, 'title'), (author, 'author'), (attribution, 'attribution')):
        if blk is not None:
            blk.role, blk.unit, blk.part, blk.reason = 'poem', u, part, f'诗歌的{part}'
    return u


# ---------- 书信 ----------

def _salutation(b) -> bool:
    return b.role in PLAIN and b.unit < 0 and bool(SALUTATION.match(b.text)) and bool(ADDRESS.search(b.text)) \
        and not SPEECH.search(b.text)


def detect_letters(ctx: _Ctx) -> None:
    blocks = ctx.blocks
    para_cls = Counter((b.doc, b.el.get('class') or '') for b in blocks if b.role == 'para')
    for b in blocks:
        if not _salutation(b):
            continue
        # 多行称谓：紧挨在前的无标点短行（「骝先先生院长」「企孙、毅侯两兄」「赐鉴：」）
        head = [b]
        p = ctx.nxt(b, -1)
        while p is not None and p.role in PLAIN and p.unit < 0 and len(p.text) <= 12 \
                and not re.search(r'[，。！？；：:]', p.text) and len(head) < 3:
            head.insert(0, p)
            p = ctx.nxt(p, -1)
        if len(head) > 1 and not ADDRESS.search(''.join(x.text for x in head[:-1])):
            head = [b]
        # 往后找信尾：祝颂语、署名、日期
        tail: dict[int, str] = {}
        body: list = []
        c = ctx.nxt(b)
        steps = 0
        last_val = None
        while c is not None and steps < 40 and c.role not in ('heading',) and c.unit < 0:
            t = c.text
            if len(t) <= 14 and VALEDICTION.match(t):
                tail[c.idx], last_val = 'valediction', c
            elif last_val is not None and c.idx == last_val.idx + 1 and len(t) <= 8 and \
                    (CLOSING.match(t) or not re.search(r'[，。；]', t)):
                tail[c.idx] = 'closing'
            elif len(t) <= 14 and DATE.match(t.replace(' ', '')):
                tail[c.idx] = 'date'
            elif len(t) <= 24 and (SIGN_WORD.search(t) or c.align == 'right' or c.role == 'right') \
                    and not re.search(r'[。！？]$', t):
                tail[c.idx] = 'signature'
            elif tail:
                break                                  # 信尾之后又是正文：信结束
            elif c.role in PLAIN:
                body.append(c)
            else:
                break
            c = ctx.nxt(c)
            steps += 1
        if not tail or not body or not ({'valediction', 'signature', 'date'} & set(tail.values())):
            continue
        end = blocks[max(tail)]
        # 附言：信尾之后以「又及」等开头，或与信正文同一个原书类名（且不是本文件正文的主流类名）
        body_cls = Counter(x.el.get('class') or '' for x in body).most_common(1)[0][0]
        main_cls = max(((n, k[1]) for k, n in para_cls.items() if k[0] == b.doc), default=(0, ''))[1]
        ps = []
        c = ctx.nxt(end)
        while c is not None and c.role in PLAIN and c.unit < 0 and len(ps) < 5:
            if POSTSCRIPT.match(c.text) or (body_cls and body_cls != main_cls and (c.el.get('class') or '') == body_cls):
                ps.append(c)
                c = ctx.nxt(c)
            else:
                break
        u = ctx.unit('letter', head[0], level='B')
        for x in head:
            x.role, x.unit, x.part = 'letter', u, 'salutation' if x is b else 'salutation-pre'
        for x in body:
            x.role, x.unit, x.part = 'letter', u, 'body'
        for idx, part in tail.items():
            blocks[idx].role, blocks[idx].unit, blocks[idx].part = 'letter', u, part
        for x in blocks[b.idx + 1:end.idx]:          # 信尾之间夹的正文（如「此致」与署名之间）
            if x.unit < 0:
                x.role, x.unit, x.part = 'letter', u, 'body'
        for x in ps:
            x.role, x.unit, x.part = 'letter', u, 'postscript'
        for x in [*head, *body, *ps] + [blocks[k] for k in tail]:
            x.reason = f'书信（{x.part}）'


# ---------- 列表、项、条文 ----------

def _num_in_link(b) -> bool:
    a = b.el.find('.//' + X + 'a')
    return a is not None and OL_NUM.match(''.join(a.itertext()).strip() + ' ') is not None and \
        ''.join(b.el.itertext()).lstrip().startswith(''.join(a.itertext()).strip())


def detect_lists(ctx: _Ctx) -> None:
    blocks = ctx.blocks
    i = 0
    while i < len(blocks):
        b = blocks[i]
        m = OL_NUM.match(b.text) if b.role in LISTABLE and b.unit < 0 else None
        if not m or _num_in_link(b):
            i += 1
            continue
        run, nums = [b], [int(m.group(1))]
        j = i + 1
        while j < len(blocks):
            c = blocks[j]
            mc = OL_NUM.match(c.text) if c.doc == b.doc and c.role in LISTABLE and c.unit < 0 else None
            if not mc or int(mc.group(1)) != nums[-1] + 1 or _num_in_link(c):
                break
            run.append(c)
            nums.append(int(mc.group(1)))
            j += 1
        if len(run) >= 3:
            u = ctx.unit('ol', run[0], level='B', start=nums[0])
            for c in run:
                c.role, c.unit, c.part, c.reason = 'ol', u, 'li', '阿拉伯数字序号段'
                c.verify = OL_NUM.sub('', _vtext(c).strip(), count=1)
        i = j
    # 中文序号项：同组连续 ≥2 段；悬挂宽度取组内最长序号（04 4.10.2.2）
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if not (b.role in LISTABLE and b.unit < 0 and CN_ITEM.match(b.text)):
            i += 1
            continue
        run = [b]
        j = i + 1
        while j < len(blocks) and blocks[j].doc == b.doc and blocks[j].role in LISTABLE and blocks[j].unit < 0 \
                and CN_ITEM.match(blocks[j].text):
            run.append(blocks[j])
            j += 1
        if len(run) >= 2:
            n = max(2 if len(CN_ITEM.match(c.text).group(1)) <= 2 else min(4, len(CN_ITEM.match(c.text).group(1)))
                    for c in run)
            u = ctx.unit('item', run[0], level='A')
            for c in run:
                c.role, c.unit, c.reason, c.attrs['hang'] = 'item', u, '中文序号项', n
        i = j
    # 条文：一个文件里「第X条」≥2 段
    per_doc = Counter(b.doc for b in blocks if b.role == 'para' and ARTICLE.match(b.text))
    units: dict[str, int] = {}
    for b in blocks:
        if b.role == 'para' and per_doc[b.doc] >= 2 and ARTICLE.match(b.text):
            if b.doc not in units:
                units[b.doc] = ctx.unit('article', b, level='A')
            b.role, b.unit, b.reason = 'article', units[b.doc], '法规条文'
            b.verify = ARTICLE.sub(lambda m: m.group(1) + '　', _vtext(b).strip(), count=1)


def detect_dl(ctx: _Ctx) -> None:
    """原书的 dl：dt/dd 被拆成了单块，按同一个 dl 父元素重新成组（04 4.10.3.8）。"""
    groups: dict = {}
    for b in ctx.blocks:
        if _local(b.el) in ('dt', 'dd') and b.unit < 0 and b.role in PLAIN + ('heading',):
            groups.setdefault(b.el.getparent(), []).append(b)
    for dl, members in groups.items():
        u = ctx.unit('dl', members[0], level='A', glossary=False)
        for b in members:
            b.role, b.unit, b.part, b.reason = 'dl', u, _local(b.el), '原有定义列表'


# ---------- 插图目录、表格目录、表题表注、术语表 ----------

def detect_lists_of(ctx: _Ctx) -> None:
    from .semantic import _link_only
    blocks = ctx.blocks
    for b in blocks:
        key = _clean(b.text)
        kind = 'loi' if LOI_TITLE.match(key) else 'lot' if LOT_TITLE.match(key) else None
        if kind is None or b.unit >= 0 or len(key) > 8:
            continue
        entries = []
        c = ctx.nxt(b)
        while c is not None and c.role != 'heading' and c.unit < 0 and len(c.text) <= 80 and \
                (_link_only(c.el) or re.search(r'\d+\s*$', c.text) or kind == 'loi' and c.role in PLAIN):
            entries.append(c)
            c = ctx.nxt(c)
        if len(entries) < 3:
            continue
        u = ctx.unit(kind, b, level='A', title=b.text)
        b.role, b.unit, b.part, b.reason = 'loi-head', u, 'head', '插图目录标题' if kind == 'loi' else '表格目录标题'
        for e in entries:
            e.role, e.unit, e.part, e.reason, e.verify = 'loi-entry', u, 'entry', '目录条目', ''
    figures = [b for b in blocks if b.role == 'figure']
    if len(figures) >= 5 and not any(u['kind'] == 'loi' for u in ctx.an.units.values()):
        ctx.suggest('loi', figures[0], f'全书有 {len(figures)} 张块级插图，原书没有插图目录；按规范不自动新建（04 4.11.4.2）')


def detect_tables(ctx: _Ctx) -> None:
    for b in ctx.blocks:
        if b.role != 'keep':
            continue
        tables = [b.el] if _local(b.el) == 'table' else list(b.el.iter(X + 'table'))
        if not tables:
            continue
        prev = ctx.nxt(b, -1)
        if prev is not None and prev.role in PLAIN and prev.unit < 0 and len(prev.text) <= 60 and \
                TABLE_CAPTION.match(prev.text) and tables[0].find(X + 'caption') is None:
            prev.role, prev.group, prev.reason = 'table-caption', b.idx, '表格上方的表题'
        after = ctx.nxt(b)
        if after is not None and after.role in PLAIN and after.unit < 0 and TABLE_NOTE.match(after.text):
            after.role, after.group, after.reason = 'table-note', b.idx, '表格下方的表注'
        rows = tables[0].findall('.//' + X + 'tr')
        if rows:
            first = ''.join(rows[-1].itertext()).strip()
            if re.match(r'^(合计|总计|共计|Total)', first, re.I):
                ctx.suggest('table', b, f'表格末行「{first[:20]}」是合计行，可移入 tfoot（04 4.13.1.4，需确认）', [b])


def detect_glossary(ctx: _Ctx) -> None:
    blocks = ctx.blocks
    for b in blocks:
        if b.role != 'heading' or not GLOSSARY_TITLE.match(_clean(b.text)):
            continue
        c, lines = ctx.nxt(b), []
        while c is not None and c.role != 'heading':
            if c.role == 'dl':
                ctx.an.units[c.unit]['glossary'] = True
            elif c.role == 'para' and c.unit < 0 and TERM_LINE.match(c.text):
                lines.append(c)
            c = ctx.nxt(c)
        b.attrs['glossary'] = True
        if len(lines) >= 5:
            ctx.suggest('glossary', b, f'术语表「{b.text}」是 {len(lines)} 行「词：释义」文本，可转为 dl.glossary'
                                       f'（04 4.19.1.8，需确认）', lines)


def detect_script(ctx: _Ctx) -> None:
    """剧本、问答体只建议（04 §4.9 识别信号：全为 C 级）。"""
    per_doc: dict[str, list] = {}
    for b in ctx.blocks:
        if b.role in ('para', 'quote'):
            per_doc.setdefault(b.doc, []).append(b)
    for doc, paras in per_doc.items():
        if len(paras) < 10:
            continue
        names = Counter(m.group(1) for b in paras if (m := DIALOGUE.match(b.text)))
        hits = sum(n for name, n in names.items() if n >= 3)
        if hits >= 0.7 * len(paras):
            top = '、'.join(n for n, _ in names.most_common(3))
            cast = [n for n, k in names.items() if k >= 3]
            members = [b for b in paras if (m := DIALOGUE.match(b.text)) and m.group(1) in cast or STAGE.fullmatch(b.text)]
            ctx.suggest('script', paras[0], f'{hits}/{len(paras)} 段是「角色名：台词」（{top}…），疑似剧本或问答体；'
                                            f'确认后按 04 §4.9 写法 B 改写', members, cast=cast)


# ---------- 用户取舍（确认板） ----------

def _decided(decisions: dict, kind: str, key: str, default: bool) -> bool:
    items, kinds = decisions.get('items') or {}, decisions.get('kinds') or {}
    if key in items:
        return bool(items[key])
    return bool(kinds.get(kind, default))


def _revert(ctx: _Ctx, u: int) -> None:
    mem = [b for b in ctx.blocks if b.unit == u]
    ctx.an.units[u].update(lines=[b.text[:60] for b in mem[:4]], count=len(mem), doc=mem[0].doc if mem else '')
    for b in ctx.blocks:
        if b.unit == u:
            b.role, b.unit, b.part, b.verify = ctx.orig[b.idx], -1, '', None
            b.attrs.pop('indents', None)
            b.attrs.pop('hang', None)
            b.reason = '用户确认：不按结构改写'
    ctx.an.units[u]['rejected'] = True


def _free(ctx: _Ctx, idxs: list[int]) -> list:
    """建议涉及的块里，仍未被别的结构占用的。"""
    return [ctx.blocks[i] for i in idxs if ctx.blocks[i].unit < 0 and ctx.blocks[i].role in PLAIN]


def apply_decisions(ctx: _Ctx, decisions: dict) -> None:
    for u, info in list(ctx.an.units.items()):
        if not _decided(decisions, info['kind'], info['key'], True):
            _revert(ctx, u)
    for sg in ctx.an.suggestions:
        if not sg['actionable'] or not _decided(decisions, 's-' + sg['kind'], sg['key'], False):
            continue
        sg['applied'] = True
        blocks = _free(ctx, sg['blocks'])
        if sg['kind'] == 'poem' and blocks:
            title = ctx.blocks[sg['title']] if sg.get('title') is not None else None
            make_poem(ctx, blocks, title, None, 'C')
        elif sg['kind'] == 'ad' and blocks:
            for b in blocks:
                b.role, b.reason = 'junk', '用户确认：夹在正文里的广告'
        elif sg['kind'] == 'table':
            ctx.blocks[sg['blocks'][0]].attrs['tfoot'] = True
        elif sg['kind'] == 'glossary' and blocks:
            u = ctx.unit('gloss', blocks[0], level='C')
            for b in blocks:
                m = TERM_LINE.match(b.text)
                term = m.group(1)
                b.role, b.unit, b.part, b.attrs['term'] = 'gloss', u, 'line', term
                b.verify = term + re.sub(r'^[：:—]+', '', _vtext(b).strip()[len(term):])
        elif sg['kind'] == 'script' and blocks:
            u = ctx.unit('script', blocks[0], level='C', cast=sg.get('cast', []))
            for b in blocks:
                m = DIALOGUE.match(b.text)
                if m and m.group(1) in sg.get('cast', []):
                    name = m.group(1)
                    b.role, b.unit, b.attrs['persona'] = 'dialogue', u, name
                    b.verify = name + '：' + _vtext(b).strip()[len(name) + 1:]
                else:
                    b.role, b.unit = 'stage', u


# ---------- 广告 ----------

# 夹在正文里的广告行：比整页判定更严，必须是短行且含明确的引流用语；只给建议，勾选才删
AD_LINE = re.compile(r'公众号|微信号|微信搜索|扫码|扫一扫|关注(我们|本号)|更多(好书|电子书|精彩|资源)|'
                     r'电子书(搜索|下载|打包)|免费(下载|电子书)|书友群|交流群|QQ群|加群|'
                     r'本书由.{0,12}(整理|制作|分享|提供)|下载站|读累了')


def detect_junk_pages(ctx: _Ctx) -> None:
    """整页广告：每页一个结构（kind=junk），默认删除；用户拒绝时还原成原来的角色。"""
    pages: dict[str, list] = {}
    for b in ctx.blocks:
        if b.role == 'junk' and 'pre_junk' in b.attrs:
            pages.setdefault(b.doc, []).append(b)
    for doc, bs in pages.items():
        u = ctx.unit('junk', bs[0], level='B')
        for b in bs:
            b.unit, b.part = u, 'junk'
            ctx.orig[b.idx] = b.attrs['pre_junk']


def detect_ad_lines(ctx: _Ctx) -> None:
    """版权页上出版社自己印的微博、公众号是出版信息，不算广告，跳过。"""
    from .semantic import COPYRIGHT_TITLES
    n = 0
    section = ''
    for b in ctx.blocks:
        if b.role == 'heading':
            section = _clean(b.text)
            continue
        if section.startswith(COPYRIGHT_TITLES) or b.role == 'meta':
            continue
        if b.role not in ('para', 'center', 'right') or b.unit >= 0 or len(b.text) > 60:
            continue
        if not AD_LINE.search(b.text) or re.search('[“”「」]', b.text):     # 带引号的多半是对话、引文
            continue
        ctx.suggest('ad', b, f'疑似夹在正文里的广告：{b.text[:40]}', [b])
        n += 1
        if n >= 50:
            break


def detect(book: Book, an, decisions: dict | None = None) -> None:
    ctx = _Ctx(book, an)
    detect_dl(ctx)
    detect_lists_of(ctx)
    detect_poems(ctx)
    detect_letters(ctx)
    detect_lists(ctx)
    detect_tables(ctx)
    detect_glossary(ctx)
    detect_script(ctx)
    detect_junk_pages(ctx)
    detect_ad_lines(ctx)
    apply_decisions(ctx, decisions or {})
