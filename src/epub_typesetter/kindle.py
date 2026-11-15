"""Kindle 格式（MOBI / AZW / AZW3）转 EPUB，作为体检和修复的输入。

拆包用 KindleUnpack（PyPI 包 ``mobi``，GPL-3），按独立程序调用（``mobiunpack`` 命令），
不 import 进本项目——和调用 epubcheck 一样，只交换文件。镜像里装在单独的虚拟环境中。

- AZW3，以及含 KF8 的 AZW/MOBI：KindleUnpack 直接还原出 EPUB，原样使用。
- 只有旧格式（MOBI 6）的：KindleUnpack 只拆出 book.html + content.opf + toc.ncx + 图片，
  由本模块打包成 EPUB 2：在分页符处拆章、把 MOBI 的段落属性换成 CSS、修正跨文件链接。
  其余（升级 EPUB 3、补导航、废弃标记转 CSS 等）交给后面的规范修复和排版重建。
- 加密（DRM）的书和 KFX、Topaz 格式不支持：直接报错，不尝试解密。

转换不保证与 Kindle 上的显示一致，转出的 EPUB 就是之后的「原件」，原上传文件另存一份。
"""
from __future__ import annotations

import glob
import io
import os
import posixpath
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile

from lxml import etree
from lxml import html as lhtml

KINDLE_EXTS = ('mobi', 'azw', 'azw3')
TOOL = os.environ.get('EPUBTS_MOBIUNPACK', 'mobiunpack')
XHTML = 'http://www.w3.org/1999/xhtml'
OPF = 'http://www.idpf.org/2007/opf'
NCX = 'http://www.daisy.org/z3986/2005/ncx/'


class KindleError(Exception):
    """无法转换（加密、格式不支持、拆包失败等），消息直接给用户看。"""


def available() -> bool:
    return shutil.which(TOOL) is not None


def ext_of(filename: str) -> str:
    """文件扩展名（小写，不带点）。"""
    return os.path.splitext(filename or '')[1].lower().lstrip('.')


def is_kindle(data: bytes) -> bool:
    """PalmDB 头里的类型/创建者是 BOOKMOBI（MOBI、AZW、AZW3 都是）。"""
    return data[60:68] == b'BOOKMOBI'


def check(data: bytes) -> None:
    """上传时先做的检查：不是能转的 Kindle 文件就抛 KindleError（消息给用户看）。"""
    if data[:8] == b'\xeaDRMION\xee':
        raise KindleError('这是加密的 KFX 格式（新版 Kindle 书），无法转换')
    if data[:4] == b'CONT' or data[:4] == b'\xe0\x01\x00\xea':
        raise KindleError('这是 KFX 格式（新版 Kindle 书），暂不支持；可以在 Kindle 软件或 Calibre 里先转成 AZW3')
    if data[:3] == b'TPZ':
        raise KindleError('这是 Topaz 格式的 Kindle 书，暂不支持')
    if not is_kindle(data):
        raise KindleError('不是 MOBI / AZW / AZW3 文件')
    if encrypted(data):
        raise KindleError('这本书有 DRM 加密，无法转换（本工具不做解密）')


def encrypted(data: bytes) -> bool:
    """MOBI 头（第 0 条记录）偏移 12 的加密类型：0 未加密，1 旧 Mobipocket 加密，2 Mobipocket DRM。"""
    try:
        (rec0,) = struct.unpack('>L', data[78:82])
        (enc,) = struct.unpack('>H', data[rec0 + 12:rec0 + 14])
    except struct.error:
        raise KindleError('文件头不完整，可能已损坏') from None
    return enc != 0


def to_epub(data: bytes, ext: str = 'azw3', timeout: int = 300) -> bytes:
    """把 Kindle 文件转成 EPUB 字节。"""
    check(data)
    if not available():
        raise KindleError('服务器没有安装 KindleUnpack（mobiunpack），无法转换 Kindle 格式')
    with tempfile.TemporaryDirectory(prefix='kindle-') as td:
        src = os.path.join(td, f'in.{ext if ext in KINDLE_EXTS else "azw3"}')
        out = os.path.join(td, 'out')
        with open(src, 'wb') as f:
            f.write(data)
        try:
            p = subprocess.run([TOOL, '--epub_version=A', src, out], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise KindleError(f'转换超时（超过 {timeout} 秒）') from None
        epubs = glob.glob(os.path.join(out, 'mobi8', '*.epub'))
        if epubs:                                  # KF8：KindleUnpack 已还原为 EPUB
            with open(epubs[0], 'rb') as f:
                return tidy(f.read())
        if os.path.exists(os.path.join(out, 'mobi7', 'book.html')):
            return tidy(pack_mobi7(os.path.join(out, 'mobi7')))
        tail = (p.stderr or p.stdout or b'').decode('utf-8', 'replace').strip().splitlines()[-1:]
        raise KindleError('转换失败' + (f'：{tail[0]}' if tail else ''))


def tidy(epub: bytes) -> bytes:
    """清掉 KindleUnpack 输出里 EPUB 不允许、本工具的规则又不管的东西：
    OPF 里的空 <tours>、spine 的 page-map 属性（Adobe 扩展）、空的 dc 元数据，导航里没有文字的条目。"""
    from .book import NS, Book
    book = Book.load(epub)
    opf = book.opf
    for t in opf.findall('opf:tours', NS):
        opf.remove(t)
    spine = opf.find('opf:spine', NS)
    if spine is not None:
        spine.attrib.pop('page-map', None)
    md = opf.find('opf:metadata', NS)
    for el in list(md if md is not None else []):
        if isinstance(el.tag, str) and el.tag.startswith(f'{{{NS["dc"]}}}') and not (el.text or '').strip() and not len(el):
            md.remove(el)
    book.mark_dirty(book.opf_path)
    for it in book.manifest():
        if 'nav' not in it.properties or it.path not in book.files:
            continue
        root = book.tree(it.path).getroot()
        for a in list(root.iter(f'{{{NS["xhtml"]}}}a')):
            if ''.join(a.itertext()).strip():
                continue
            li = a.getparent()
            sub = li.find(f'{{{NS["xhtml"]}}}ol') if li is not None else None
            if li is not None and etree.QName(li).localname == 'li' and sub is None:
                li.getparent().remove(li)                     # 没有文字也没有下级：整条去掉
            else:
                a.text = (sub.findtext(f'.//{{{NS["xhtml"]}}}a') or '').strip() if sub is not None else ''
                a.text = a.text or '（无标题）'
        book.mark_dirty(it.path)
    return book.to_bytes()


# ---------- 旧格式（MOBI 6）打包 ----------

PB = 'epubts-pagebreak'                          # 分页符的占位（解析前替换，拆章时识别）
_INVALID_XML = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]')
_ATTR_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_.\-]*$')
_LENGTH = re.compile(r'^\s*(-?\d+(?:\.\d+)?)\s*(em|pt|px|%)?\s*$', re.I)
DOCTYPE = '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
MEDIA = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif',
         '.bmp': 'image/bmp', '.svg': 'image/svg+xml', '.webp': 'image/webp'}


def _length(v: str | None) -> str | None:
    """MOBI 段落尺寸：带单位原样，不带单位按像素；0 视为没有。"""
    m = _LENGTH.match(v or '')
    if not m or float(m.group(1)) == 0:
        return None
    return m.group(1) + (m.group(2) or 'px').lower()


def _mobi_paragraph_css(el) -> None:
    """MOBI 的 <p width> 是首行缩进、<p height> 是段前空白（Kindle 照此显示，浏览器忽略）。
    换成 CSS 保住原书版面；之后的 SEM-015 会把这类属性删掉，所以必须在这里先转。"""
    css = []
    for attr, prop in (('width', 'text-indent'), ('height', 'margin-top')):
        v = el.attrib.pop(attr, None)
        d = _length(v)
        if d:
            css.append(f'{prop}: {d}')
    if css:
        cur = (el.get('style') or '').strip().rstrip(';')
        el.set('style', '; '.join(([cur] if cur else []) + css))


def _clean(s: str | None) -> str | None:
    return _INVALID_XML.sub('', s) if s else s


def _to_xhtml(el):
    """lxml.html 元素 → XHTML 命名空间的 XML 元素（丢掉 XML 里不合法的属性名和字符）。"""
    out = etree.Element(f'{{{XHTML}}}{el.tag.lower()}')
    for k, v in el.attrib.items():
        if _ATTR_NAME.match(k) and k.lower() != 'xmlns':
            out.set(k.lower(), _clean(v) or '')
    out.text = _clean(el.text)
    for ch in el:
        if not isinstance(ch.tag, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', ch.tag):
            # 注释、处理指令、名字不合法的标签：只留其中文字
            text = '' if not isinstance(ch.tag, str) else ''.join(ch.itertext())
            text = _clean(text + (ch.tail or ''))
            if len(out):
                out[-1].tail = (out[-1].tail or '') + text
            else:
                out.text = (out.text or '') + text
            continue
        out.append(_to_xhtml(ch))
        out[-1].tail = _clean(ch.tail)
    return out


def _parts(body) -> list[list]:
    """在 body 直接子级的分页符处拆开；嵌在别处的分页符只删除。空白的部分丢掉。"""
    for pb in list(body.iter(PB)):
        if pb.getparent() is not body:
            pb.drop_tag()
    parts, cur = [], []
    if (body.text or '').strip():
        p = lhtml.Element('p')
        p.text = body.text
        cur.append(p)
    for ch in body:
        if not isinstance(ch.tag, str):                # 注释等：只留其后的文字
            if (ch.tail or '').strip():
                p = lhtml.Element('p')
                p.text = ch.tail
                cur.append(p)
            continue
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', ch.tag) and ch.tag != PB:
            ch.tag = 'div'                             # 名字在 XML 里不合法的块，当普通 div
        if ch.tag == PB:
            parts.append(cur)
            cur = []
            if (ch.tail or '').strip():
                p = lhtml.Element('p')
                p.text = ch.tail
                cur.append(p)
            continue
        cur.append(ch)
    parts.append(cur)

    def has_content(chs):
        return any(''.join(c.itertext()).strip() or c.tag == 'img' or c.find('.//img') is not None
                   or c.find('.//svg') is not None for c in chs)
    return [p for p in parts if has_content(p)] or [[]]


def _decode(raw: bytes) -> str:
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:2048])
    enc = m.group(1).decode('ascii') if m else 'utf-8'
    try:
        return raw.decode(enc, 'replace')
    except LookupError:
        return raw.decode('utf-8', 'replace')


def pack_mobi7(d: str) -> bytes:
    """把 KindleUnpack 拆出的旧格式目录（book.html、content.opf、toc.ncx、Images/）打包成 EPUB 2。"""
    text = _decode(open(os.path.join(d, 'book.html'), 'rb').read())
    text = re.sub(r'<guide\b.*?</guide>', '', text, flags=re.S | re.I)                 # 头里的旧式 guide
    text = re.sub(r'<mbp:pagebreak\b[^>]*>(\s*</mbp:pagebreak>)?', f'<{PB}></{PB}>', text, flags=re.I)
    text = re.sub(r'</?mbp:[^>]*>', '', text, flags=re.I)                               # 其他 mbp: 标签只留内容
    doc = lhtml.document_fromstring(text)
    body = doc.find('body')
    if body is None:
        raise KindleError('转换失败：拆出的正文为空')
    for el in body.iter('p', 'div'):
        _mobi_paragraph_css(el)

    opf = etree.parse(os.path.join(d, 'content.opf'), etree.XMLParser(remove_comments=True))
    title = opf.findtext(f'.//{{http://purl.org/dc/elements/1.1/}}title') or ''
    parts = _parts(body)
    names = [f'part{i:04d}.xhtml' for i in range(1, len(parts) + 1)]
    where = {}                                     # id → 所在文件
    for name, chs in zip(names, parts):
        for c in chs:
            for e in c.iter():
                if isinstance(e.tag, str) and e.get('id'):
                    where.setdefault(e.get('id'), name)

    def target(href: str, here: str | None) -> str:
        """book.html#x 或 #x → 拆分后的文件。找不到锚点时指向第一个文件。"""
        path, _, frag = href.partition('#')
        if path not in ('', 'book.html'):
            return href
        f = where.get(frag, names[0] if path else here)
        if f == here and not path:
            return href
        return f + (f'#{frag}' if frag in where else '')

    files: dict[str, bytes] = {}
    for name, chs in zip(names, parts):
        root = etree.Element(f'{{{XHTML}}}html', nsmap={None: XHTML})
        head = etree.SubElement(root, f'{{{XHTML}}}head')
        etree.SubElement(head, f'{{{XHTML}}}title').text = _clean(title)
        xb = etree.SubElement(root, f'{{{XHTML}}}body')
        for c in chs:
            x = _to_xhtml(c)
            x.tail = _clean(c.tail)
            xb.append(x)
        for a in xb.iter(f'{{{XHTML}}}a'):
            if a.get('href') and (a.get('href').startswith('#') or a.get('href').startswith('book.html')):
                a.set('href', target(a.get('href'), name))
        body_xml = etree.tostring(root, encoding='unicode')
        files[f'OEBPS/{name}'] = f'<?xml version="1.0" encoding="utf-8"?>\n{DOCTYPE}\n{body_xml}\n'.encode('utf-8')

    # OPF：原清单里的 book.html 换成拆出的各文件，spine 同步；guide 链接改到新文件；去掉 tours
    pk = opf.getroot()
    manifest = pk.find(f'{{{OPF}}}manifest')
    spine = pk.find(f'{{{OPF}}}spine')
    old_id = None
    for it in list(manifest):
        if it.get('href') == 'book.html':
            old_id = it.get('id')
            manifest.remove(it)
    for i, name in enumerate(names):
        it = etree.Element(f'{{{OPF}}}item', id=f'part{i + 1:04d}', href=name, attrib={'media-type': 'application/xhtml+xml'})
        manifest.insert(i, it)
    refs = [r for r in spine if r.get('idref') == old_id] if old_id else []
    pos = spine.index(refs[0]) if refs else 0
    for r in refs:
        spine.remove(r)
    for i in range(len(names)):
        spine.insert(pos + i, etree.Element(f'{{{OPF}}}itemref', idref=f'part{i + 1:04d}'))
    for t in pk.findall(f'{{{OPF}}}tours'):
        pk.remove(t)
    for r in pk.iterfind(f'{{{OPF}}}guide/{{{OPF}}}reference'):
        r.set('href', target(r.get('href', ''), None))
    listed = {it.get('href') for it in manifest}
    for p in sorted(glob.glob(os.path.join(d, 'Images', '*'))):     # 清单漏列的图片也带上
        href = 'Images/' + os.path.basename(p)
        mt = MEDIA.get(os.path.splitext(p)[1].lower())
        if href not in listed and mt:
            etree.SubElement(manifest, f'{{{OPF}}}item', id=f'img-{len(listed)}', href=href, attrib={'media-type': mt})
            listed.add(href)
    files['OEBPS/content.opf'] = etree.tostring(opf, xml_declaration=True, encoding='utf-8')

    ncx_path = os.path.join(d, 'toc.ncx')
    if os.path.exists(ncx_path):
        ncx = etree.parse(ncx_path)
        for c in ncx.iter(f'{{{NCX}}}content'):
            c.set('src', target(c.get('src', ''), None))
        files['OEBPS/toc.ncx'] = etree.tostring(ncx, xml_declaration=True, encoding='utf-8')
    for it in manifest:
        href = it.get('href', '')
        p = os.path.join(d, *href.split('/'))
        if f'OEBPS/{href}' not in files and os.path.isfile(p):
            files[f'OEBPS/{posixpath.normpath(href)}'] = open(p, 'rb').read()

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
