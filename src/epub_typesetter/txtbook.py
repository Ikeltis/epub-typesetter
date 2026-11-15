"""纯文本（TXT）转 EPUB，作为体检和修复的输入。

TXT 只有文字，结构靠猜，规则尽量保守，猜不准的交给确认板：
- 编码：BOM → UTF-8 → GB18030（含 GBK、GB2312）/ Big5（两者都能解码时按常用字比例选）。
- 分段：大多数中文 TXT 一行一段（行首全角空格缩进）；空行分段、段内硬换行的（多见于英文）
  把段内各行接起来。
- 标题：「第X卷/部/集」为部，「第X章/回/节/话」、序、楔子、尾声、后记、番外、Chapter N 等为章；
  正文几乎都缩进时，不缩进的短行也算章标题。只认短行、不以句末标点结尾，长句不会被当成标题。
  按标题拆成文件，之后由排版重建和确认板（改级别、不是标题、改文字、删章）接手。
- 书名、作者：取开头的「书名：」「作者：」行，没有就从文件名取（去掉括号里的作者、来源）。
- 只由同一符号组成的分隔行（==== 等）转成 <hr/>；其他文字原样保留，广告行由后面的识别处理。

输出 EPUB 2（XHTML 1.1 + NCX），由之后的规范修复升级为 EPUB 3。
"""
from __future__ import annotations

import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr


class TxtError(Exception):
    """不能当作文本读（二进制文件、空文件等），消息直接给用户看。"""


# ---------- 编码 ----------

_COMMON_SC = set('的一是不了在人有我他这个们中来上大为和国地到以说时要就出会可也你对生能而子那得于着下自之年过发后作里')
_COMMON_TC = set('的一是不了在人有我他這個們中來上大為和國地到以說時要就出會可也你對生能而子那得於著下自之年過發後作裡')


def decode(raw: bytes) -> str:
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8', 'replace')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16', 'replace')
    ctrl = sum(raw.count(bytes([c])) for c in (*range(0, 9), 11, 12, *range(14, 27), *range(28, 32)))
    if ctrl > len(raw) // 100:                              # 没有 BOM 的 UTF-16，或二进制文件
        for enc in ('utf-16-le', 'utf-16-be'):
            try:
                t = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            if sum(c.isprintable() or c in '\r\n\t' for c in t[:2000]) > 0.95 * min(len(t), 2000):
                return t
        raise TxtError('这不像文本文件（含大量二进制字节）')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    cands = []
    for enc, common in (('gb18030', _COMMON_SC), ('big5', _COMMON_TC)):
        try:
            t = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        sample = t[:20000]
        cands.append((sum(c in common for c in sample), enc, t))
    if cands:
        return max(cands)[2]
    return raw.decode('gb18030', 'replace')


# ---------- 分段与标题 ----------

NUM = r'[0-9０-９一二三四五六七八九十百千万零〇两壹贰叁肆伍陆柒捌玖拾佰仟]+'
PART_RE = re.compile(rf'^(第{NUM}(部分|[卷部集篇])|卷{NUM}|[上中下]卷|(volume|book|part)\s+(\d+|[ivxlc]+)\b)(\s|[:：.、]|$)', re.I)
# 「1、」「一、」这类裸序号不算：正文里的列表项很常见，误认的代价大（漏认的可在确认板上补）
CHAPTER_RE = re.compile(rf'^(第{NUM}[章回节話话折幕]|chapter\s+(\d+|[ivxlc]+)\b)', re.I)
SPECIAL_RE = re.compile(r'^(序|序章|序言|自序|前言|引子|引言|楔子|尾声|终章|后记|後記|跋|结语|完本感言|完结感言|作者的话|'
                        r'番外.{0,20}|.{0,20}番外[0-9一二三四五六七八九十]*|prologue|epilogue|preface|afterword)$', re.I)
SENTENCE_END = '。！？；，、…」』”）)!?;,'
SEPARATOR_RE = re.compile(r'^([=\-*_~—＝－＊＿～#·•.。])\1{2,}$')
META_LINE_RE = re.compile(r'^(书名|書名|作者|译者|出版|来源|类别|状态|字数|更新)[：:]\s*(.*)$')
INDENT = ' 　\t '


@dataclass
class Para:
    text: str
    indented: bool
    kind: str = 'p'           # p / part / chapter / hr


@dataclass
class Section:
    title: Para | None
    paras: list[Para] = field(default_factory=list)


def paragraphs(text: str) -> list[Para]:
    """一行一段，或空行分段（段内各行接起来）。"""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    nonblank = [ln for ln in lines if ln.strip()]
    if not nonblank:
        return []
    blank = len(lines) - len(nonblank)
    # 空行分段：空行多（大致每段一个），且多数行不以句末标点结尾（硬换行）
    unterminated = sum(1 for ln in nonblank if ln.rstrip()[-1:] not in SENTENCE_END) / len(nonblank)
    hard_wrapped = blank >= len(nonblank) * 0.3 and unterminated > 0.5
    out: list[Para] = []
    if not hard_wrapped:
        for ln in lines:
            if ln.strip():
                out.append(Para(ln.strip(INDENT + '﻿'), ln[:1] in INDENT))
        return out
    buf: list[str] = []

    def flush():
        if buf:
            joined = buf[0].strip()
            for nxt in buf[1:]:
                nxt = nxt.strip()
                latin = joined[-1:].isascii() and nxt[:1].isascii()
                joined += (' ' if latin else '') + nxt
            out.append(Para(joined, buf[0][:1] in INDENT))
            buf.clear()
    for ln in lines:
        if ln.strip():
            # 硬换行的段落里，标题、分隔行往往单独一行：遇到就先断开
            s = ln.strip(INDENT)
            if buf and (_heading_kind(s) or SEPARATOR_RE.match(s)):
                flush()
                out.append(Para(s, ln[:1] in INDENT))
                continue
            buf.append(ln)
        else:
            flush()
    flush()
    return out


def _heading_kind(s: str) -> str | None:
    """明确的标题写法：返回 part / chapter；否则 None。"""
    if len(s) > 40 or s[-1:] in '。，；、':
        return None
    if PART_RE.match(s):
        return 'part'
    if CHAPTER_RE.match(s):
        return 'chapter'
    if SPECIAL_RE.match(s.rstrip('：:')):
        return 'chapter'
    return None


def classify(paras: list[Para]) -> None:
    """标出部、章标题与分隔行。正文几乎都缩进时，不缩进的短行也算章标题。"""
    body = [p for p in paras if not _heading_kind(p.text)]
    mostly_indented = bool(body) and sum(p.indented for p in body) >= 0.9 * len(body)
    for p in paras:
        if SEPARATOR_RE.match(p.text):
            p.kind = 'hr'
            continue
        k = _heading_kind(p.text)
        if k:
            p.kind = k
        elif (mostly_indented and not p.indented and len(p.text) <= 20 and p.text[-1:] not in SENTENCE_END
              and not META_LINE_RE.match(p.text) and '://' not in p.text):
            p.kind = 'chapter'
    # 编号的章标题如果只出现一两次，多半是正文里提到的（「第三章里说……」已被长度挡掉，这里挡短句）
    numbered = [p for p in paras if p.kind == 'chapter' and CHAPTER_RE.match(p.text)]
    if 0 < len(numbered) <= 1 and len(paras) > 200:
        for p in numbered:
            p.kind = 'p'


def sections(paras: list[Para]) -> list[Section]:
    out = [Section(None)]
    for p in paras:
        if p.kind in ('part', 'chapter'):
            out.append(Section(p))
        else:
            out[-1].paras.append(p)
    if out[0].title is None and not out[0].paras:
        out.pop(0)
    return out


# ---------- 书名、作者 ----------

def _from_filename(filename: str) -> tuple[str, str]:
    stem = re.sub(r'\.txt$', '', filename or '', flags=re.I).strip()
    m = re.match(r'^《(.+?)》', stem)
    if m:
        title = m.group(1)
    else:
        title = re.split(r'\s*[(（\[【]', stem)[0].strip() or stem
    author = ''
    m = re.search(r'作者[：:]\s*([^\s()（）]+)', stem) or re.search(r'[(（]([^)）]{1,20})[)）]', stem)
    if m and not re.search(r'\.(com|net|org|sk)|library|完结|精校|全本', m.group(1), re.I):
        author = m.group(1).strip()
    return title, author


def metadata(paras: list[Para], filename: str) -> tuple[str, str]:
    title, author = '', ''
    for p in paras[:30]:
        m = META_LINE_RE.match(p.text)
        if m and m.group(1) in ('书名', '書名') and not title:
            title = m.group(2).strip().strip('《》')
        elif m and m.group(1) == '作者' and not author:
            author = m.group(2).strip()
    ft, fa = _from_filename(filename)
    return title or ft or '未命名', author or fa


# ---------- 打包 ----------

DOCTYPE = '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
_INVALID_XML = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]')


def _x(s: str) -> str:
    return escape(_INVALID_XML.sub('', s))


def _xhtml(title: str, body: str) -> bytes:
    return (f'<?xml version="1.0" encoding="utf-8"?>\n{DOCTYPE}\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{_x(title)}</title></head>\n'
            f'<body>\n{body}</body></html>\n').encode('utf-8')


def to_epub(raw: bytes, filename: str = '') -> bytes:
    text = decode(raw)
    paras = paragraphs(text)
    if not paras:
        raise TxtError('文件里没有文字')
    classify(paras)
    title, author = metadata(paras, filename)
    secs = sections(paras)

    files: dict[str, bytes] = {}
    toc = []                                            # (文件, 标题, 层级)
    names = []
    for i, sec in enumerate(secs, 1):
        name = f'Text/part{i:04d}.xhtml'
        names.append(name)
        parts = []
        if sec.title is not None:
            tag = 'h1' if sec.title.kind == 'part' else 'h2'
            parts.append(f'<{tag}>{_x(sec.title.text)}</{tag}>\n')
            toc.append((name, sec.title.text, 1 if sec.title.kind == 'part' else 2))
        for p in sec.paras:
            parts.append('<hr/>\n' if p.kind == 'hr' else f'<p>{_x(p.text)}</p>\n')
        files[f'OEBPS/{name}'] = _xhtml(sec.title.text if sec.title else title, ''.join(parts))

    # 没有「部」时章节都是一级
    if not any(lv == 1 for _, _, lv in toc):
        toc = [(n, t, 1) for n, t, _ in toc]
    uid = f'urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, "txt:" + str(len(raw)) + title + author)}'
    manifest = ''.join(f'<item id="p{i:04d}" href="{n}" media-type="application/xhtml+xml"/>'
                       for i, n in enumerate(names, 1))
    spine = ''.join(f'<itemref idref="p{i:04d}"/>' for i in range(1, len(names) + 1))
    creator = f'<dc:creator>{_x(author)}</dc:creator>' if author else ''
    files['OEBPS/content.opf'] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
        f'<dc:title>{_x(title)}</dc:title>{creator}<dc:language>zh</dc:language>'
        f'<dc:identifier id="uid">{uid}</dc:identifier></metadata>'
        f'<manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>{manifest}</manifest>'
        f'<spine toc="ncx">{spine}</spine></package>').encode('utf-8')

    # NCX：部下面挂章
    nav, open_part, n = [], False, 0
    for name, t, lv in toc:
        n += 1
        point = f'<navPoint id="n{n}" playOrder="{n}"><navLabel><text>{_x(t)}</text></navLabel><content src="{name}"/>'
        if lv == 1:
            if open_part:
                nav.append('</navPoint>')
            nav.append(point)
            open_part = any(l2 == 2 for _, _, l2 in toc)
            if not open_part:
                nav.append('</navPoint>')
        else:
            nav.append(point + '</navPoint>')
    if open_part:
        nav.append('</navPoint>')
    files['OEBPS/toc.ncx'] = (
        '<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{_x(title)}</text></docTitle>'
        f'<navMap>{"".join(nav)}</navMap></ncx>').encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(zipfile.ZipInfo('mimetype'), b'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml',
                   '<?xml version="1.0" encoding="utf-8"?>\n'
                   '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>', compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()
