"""STR：打包、OPF、导航（guide/07 §2.1）。"""
from __future__ import annotations

import posixpath
import re
import uuid

from lxml import etree

from ..book import NS, XHTML_TYPES, Book
from ..engine import AUTO, ERROR, INFO, MANUAL, SUGGEST, WARNING, Rule, register
from ..nav import NCX, ncx_path
from ..upgrade import OPF, _meta, generate_nav, now_utc, upgrade_to_3
from ..xhtml import references, rename_file, unique_path

JUNK = re.compile(r'(^|/)(__MACOSX(/|$)|\.DS_Store$|Thumbs\.db$|desktop\.ini$|\.git/)', re.I)
MODIFIED_RE = re.compile(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')

CONTAINER_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="%s" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''


def sniff(data: bytes) -> str | None:
    """按魔数判断媒体类型（STR-006）。只判断二进制资源与 SVG，其他返回 None。"""
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    if data.startswith(b'wOF2'):
        return 'font/woff2'
    if data.startswith(b'wOFF'):
        return 'font/woff'
    if data.startswith((b'\x00\x01\x00\x00', b'true')):
        return 'font/ttf'
    if data.startswith(b'OTTO'):
        return 'font/otf'
    head = data[:512].lstrip(b'\xef\xbb\xbf \t\r\n')
    if head.startswith((b'<svg', b'<?xml')) and b'<svg' in data[:2048]:
        return 'image/svg+xml'
    return None


EXT = {'image/jpeg': ('.jpg', '.jpeg'), 'image/png': ('.png',), 'image/gif': ('.gif',),
       'image/webp': ('.webp',), 'font/woff2': ('.woff2',), 'font/woff': ('.woff',),
       'font/ttf': ('.ttf',), 'font/otf': ('.otf',), 'image/svg+xml': ('.svg',)}
MEDIA_BY_EXT = {
    '.xhtml': 'application/xhtml+xml', '.html': 'application/xhtml+xml', '.htm': 'application/xhtml+xml',
    '.css': 'text/css', '.ncx': 'application/x-dtbncx+xml', '.js': 'application/javascript',
    '.smil': 'application/smil+xml', '.mp3': 'audio/mpeg', '.mp4': 'video/mp4', '.m4a': 'audio/mp4',
    '.opus': 'audio/opus', '.pls': 'application/pls+xml',
}


@register
class Mimetype(Rule):
    id, title, order = 'STR-001', 'mimetype 规范', 10

    def check(self, book):
        return [self.issue(ERROR, n, 'mimetype', AUTO) for n in book.zip_notes if 'mimetype' in n]

    def fix(self, book, issues):
        book.zip_notes = [n for n in book.zip_notes if 'mimetype' not in n]
        return ['重新打包：mimetype 置首、不压缩、无 extra field']


@register
class ZipHygiene(Rule):
    id, title, order = 'STR-002', 'ZIP 健全/垃圾文件', 11

    def check(self, book):
        out = [self.issue(WARNING, f'垃圾文件：{p}', p, AUTO) for p in book.files if JUNK.search(p)]
        seen = {}
        for p in book.files:
            k = p.casefold()
            if k in seen:
                out.append(self.issue(ERROR, f'仅大小写不同的文件名：{seen[k]} / {p}', p, MANUAL))
            seen[k] = p
        for p in book.files:
            if p.startswith('/') or '..' in p.split('/'):
                out.append(self.issue(ERROR, f'越界路径：{p}', p, MANUAL))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            it = book.item_by_path(i.file)
            if it is not None:
                it.element.getparent().remove(it.element)
                book.mark_dirty(book.opf_path)
            book.delete(i.file)
            log.append(f'删除 {i.file}')
        return log


@register
class Container(Rule):
    id, title, order = 'STR-003', 'container.xml', 12

    def check(self, book):
        raw = book.files.get('META-INF/container.xml')
        if raw is None:
            return [self.issue(ERROR, '缺少 META-INF/container.xml', 'META-INF/container.xml', AUTO)]
        if book.opf_path.encode() not in raw and Book.relative('', book.opf_path).encode() not in raw:
            return [self.issue(ERROR, 'container.xml 未正确指向 OPF', 'META-INF/container.xml', AUTO)]
        return []

    def fix(self, book, issues):
        book.set_bytes('META-INF/container.xml', CONTAINER_XML % Book.relative('', book.opf_path).encode())
        return [f'重建 container.xml → {book.opf_path}']


@register
class PackageMetadata(Rule):
    id, title, order = 'STR-004', 'OPF 必需项与 EPUB 3', 20

    def check(self, book):
        out = []
        opf = book.opf
        if book.version != '3.0':
            out.append(self.issue(ERROR, f'EPUB 版本为 {book.version or "未知"}，应升级到 3.0', book.opf_path, AUTO,
                                  kind='upgrade'))
            return out      # 升级会处理其余元数据问题
        md = opf.find('opf:metadata', NS)
        uid = opf.get('unique-identifier')
        ids = [e for e in md.findall('dc:identifier', NS)]
        if not ids:
            out.append(self.issue(ERROR, '缺少 dc:identifier', book.opf_path, AUTO, kind='identifier'))
        elif not uid or not any(e.get('id') == uid for e in ids):
            out.append(self.issue(ERROR, 'unique-identifier 未指向存在的 dc:identifier', book.opf_path, AUTO,
                                  kind='uid'))
        if md.find('dc:title', NS) is None or not (md.find('dc:title', NS).text or '').strip():
            out.append(self.issue(ERROR, '缺少 dc:title', book.opf_path, SUGGEST, kind='title'))
        if md.find('dc:language', NS) is None:
            out.append(self.issue(ERROR, '缺少 dc:language', book.opf_path, SUGGEST, kind='language'))
        mods = md.findall("opf:meta[@property='dcterms:modified']", NS)
        if len(mods) != 1 or not MODIFIED_RE.match((mods[0].text or '').strip()):
            out.append(self.issue(ERROR, 'dcterms:modified 缺失、重复或格式错误', book.opf_path, AUTO, kind='modified'))
        return out

    def fix(self, book, issues):
        kinds = {i.data.get('kind') for i in issues}
        if 'upgrade' in kinds:
            return upgrade_to_3(book)
        log = []
        md = book.opf.find('opf:metadata', NS)
        if 'identifier' in kinds:
            el = etree.SubElement(md, '{%s}identifier' % NS['dc'])
            el.set('id', 'bookid')
            el.text = f'urn:uuid:{uuid.uuid4()}'
            book.opf.set('unique-identifier', 'bookid')
            log.append(f'生成 dc:identifier {el.text}')
        if 'uid' in kinds:
            first = md.find('dc:identifier', NS)
            if not first.get('id'):
                first.set('id', 'bookid')
            book.opf.set('unique-identifier', first.get('id'))
            log.append(f'unique-identifier 指向 {first.get("id")}')
        if 'modified' in kinds:
            for m in md.findall("opf:meta[@property='dcterms:modified']", NS):
                md.remove(m)
            _meta(md, 'dcterms:modified', now_utc())
            log.append('重写 dcterms:modified')
        book.mark_dirty(book.opf_path)
        return log


@register
class ManifestConsistency(Rule):
    id, title, order = 'STR-005', 'manifest 与包内文件一致', 21

    def check(self, book):
        out = []
        items = book.manifest()
        seen = set()
        for it in items:
            if it.id in seen:
                out.append(self.issue(ERROR, f'manifest id 重复：{it.id}', book.opf_path, MANUAL))
            seen.add(it.id)
            if it.path not in book.files and not it.href.startswith(('http:', 'https:')):
                out.append(self.issue(ERROR, f'manifest 登记的文件不存在：{it.href}', it.path, SUGGEST))
        declared = {it.path for it in items}
        orphans = [p for p in book.files
                   if p not in declared and p != 'mimetype' and not p.startswith('META-INF/') and p != book.opf_path]
        if orphans:
            refs = references(book)
            for p in orphans:
                if p in refs:
                    out.append(self.issue(ERROR, f'被引用但未登记的文件：{p}', p, AUTO))
                else:
                    out.append(self.issue(WARNING, f'未登记且未被引用的孤儿文件：{p}', p, SUGGEST))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            p = i.file
            mt = sniff(book.files[p]) or MEDIA_BY_EXT.get(posixpath.splitext(p)[1].lower())
            if not mt:
                continue
            book.add_item(p, mt)
            log.append(f'补登记 {p}（{mt}）')
        return log


@register
class MediaTypes(Rule):
    id, title, order = 'STR-006', 'media-type 与真实内容一致', 22

    def check(self, book):
        out = []
        for it in book.manifest():
            data = book.files.get(it.path)
            if data is None:
                continue
            real = sniff(data)
            if real is None or real == it.media_type:
                ext = posixpath.splitext(it.path)[1].lower()
                if real and ext not in EXT.get(real, (ext,)):
                    out.append(self.issue(WARNING, f'扩展名与内容不符：{it.href} 实为 {real}', it.path, AUTO, real=real))
                continue
            if it.media_type.startswith(('image/', 'font/', 'application/font', 'application/vnd.ms-opentype',
                                         'application/x-font')):
                out.append(self.issue(ERROR, f'{it.href} 登记为 {it.media_type}，实为 {real}', it.path, AUTO, real=real))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            it = book.item_by_path(i.file)
            real = i.data['real']
            if it.media_type != real:
                it.element.set('media-type', real)
                book.mark_dirty(book.opf_path)
                log.append(f'{it.href}：media-type {it.media_type} → {real}')
            ext = posixpath.splitext(i.file)[1].lower()
            if ext not in EXT[real]:
                new = unique_path(book, posixpath.splitext(i.file)[0] + EXT[real][0])
                rename_file(book, i.file, new)
                log.append(f'改名 {i.file} → {new}（引用已同步）')
        return log


@register
class Spine(Rule):
    id, title, order = 'STR-007', 'spine 完整', 23

    def check(self, book):
        out = []
        spine = book.opf.find('opf:spine', NS)
        if spine is None:
            return [self.issue(ERROR, '缺少 spine', book.opf_path, MANUAL)]
        ids = {i.id for i in book.manifest()}
        seen = set()
        for ref in spine.findall('opf:itemref', NS):
            idref = ref.get('idref')
            if idref not in ids:
                out.append(self.issue(ERROR, f'spine 引用不存在的 id：{idref}', book.opf_path, AUTO, idref=idref))
            elif idref in seen:
                out.append(self.issue(WARNING, f'spine 重复引用：{idref}', book.opf_path, AUTO, idref=idref))
            seen.add(idref)
        if not seen:
            out.append(self.issue(ERROR, 'spine 为空', book.opf_path, MANUAL))
        for it in book.manifest():
            if it.media_type in XHTML_TYPES and it.id not in seen and 'nav' not in it.properties \
                    and it.path in book.files:
                out.append(self.issue(WARNING, f'内容文档不在 spine 中：{it.href}', it.path, SUGGEST))
        return out

    def fix(self, book, issues):
        spine = book.opf.find('opf:spine', NS)
        ids = {i.id for i in book.manifest()}
        seen, log = set(), []
        for ref in list(spine.findall('opf:itemref', NS)):
            idref = ref.get('idref')
            if idref not in ids or idref in seen:
                spine.remove(ref)
                log.append(f'删除 spine 项 {idref}')
            seen.add(idref)
        book.mark_dirty(book.opf_path)
        return log


@register
class NavDocument(Rule):
    id, title, order = 'STR-008', 'nav 文档存在且合规', 80

    def check(self, book):
        if not book.version.startswith('3'):
            return []
        navs = [i for i in book.manifest() if 'nav' in i.properties]
        if not navs:
            return [self.issue(ERROR, '缺少 nav 导航文档', book.opf_path, AUTO)]
        if len(navs) > 1:
            return [self.issue(ERROR, f'有 {len(navs)} 个 nav 文档', book.opf_path, MANUAL)]
        nav = navs[0]
        if nav.path not in book.files:
            return [self.issue(ERROR, f'nav 文档不存在：{nav.href}', nav.path, MANUAL)]
        root = book.tree(nav.path).getroot()
        toc = root.find(f".//{{{NS['xhtml']}}}nav[@{{{NS['epub']}}}type='toc']")
        if toc is None:
            return [self.issue(ERROR, 'nav 文档中没有 epub:type="toc"', nav.path, MANUAL)]
        return []

    def fix(self, book, issues):
        _, log = generate_nav(book)
        return log


@register
class NcxCompat(Rule):
    """P1，但不修会让 epubcheck 报错，所以 M0 就做（guide/07 §1.4）。"""
    id, title, order = 'STR-015', 'NCX/guide 向后兼容', 25

    def check(self, book):
        out = []
        for ref in book.opf.iterfind('opf:guide/opf:reference', NS):
            path = Book.resolve(book.opf_path, ref.get('href', ''))
            it = book.item_by_path(path)
            if it is None or it.media_type not in XHTML_TYPES:
                out.append(self.issue(ERROR, f'guide 指向非内容文档：{ref.get("href")}', book.opf_path, AUTO,
                                      kind='guide', href=ref.get('href')))
        p = ncx_path(book)
        if p:
            root = book.tree(p).getroot()
            if not root.get('version'):
                out.append(self.issue(ERROR, 'NCX 缺少 version 属性', p, AUTO, kind='version'))
            uid_meta = root.find(f"{NCX}head/{NCX}meta[@name='dtb:uid']")
            uid = self._uid(book)
            if uid and uid_meta is not None and (uid_meta.get('content') or '').strip() != uid:
                out.append(self.issue(ERROR, 'NCX dtb:uid 与 OPF 唯一标识不一致', p, AUTO, kind='uid', uid=uid))
        return out

    @staticmethod
    def _uid(book):
        uid = book.opf.get('unique-identifier')
        for e in book.opf.iterfind('opf:metadata/dc:identifier', NS):
            if e.get('id') == uid:
                return (e.text or '').strip()
        return None

    def fix(self, book, issues):
        log = []
        for i in issues:
            kind = i.data['kind']
            if kind == 'guide':
                for ref in book.opf.iterfind('opf:guide/opf:reference', NS):
                    if ref.get('href') == i.data['href']:
                        ref.getparent().remove(ref)
                        book.mark_dirty(book.opf_path)
                        log.append(f'删除指向非内容文档的 guide 项 {i.data["href"]}')
                guide = book.opf.find('opf:guide', NS)
                if guide is not None and len(guide) == 0:
                    guide.getparent().remove(guide)
            elif kind == 'version':
                book.tree(i.file).getroot().set('version', '2005-1')
                book.mark_dirty(i.file)
                log.append('NCX 补 version="2005-1"')
            elif kind == 'uid':
                root = book.tree(i.file).getroot()
                root.find(f"{NCX}head/{NCX}meta[@name='dtb:uid']").set('content', i.data['uid'])
                book.mark_dirty(i.file)
                log.append('NCX dtb:uid 同步为 OPF 唯一标识')
        return log
