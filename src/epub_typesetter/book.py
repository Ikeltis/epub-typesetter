"""EPUB 文档模型：读取、按需解析、修改、合规打包。

设计要点（见 guide/01）：
- 包内文件统一用「zip 内路径」寻址（如 ``OEBPS/Text/c01.xhtml``），不写死 OEBPS。
- XHTML/OPF/NCX 按需解析并缓存；被修改的文档在保存时重新序列化，未改动的原样写回字节。
- 打包时 mimetype 永远是第一条且不压缩（STR-001）。
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

from lxml import etree

NS = {
    'container': 'urn:oasis:names:tc:opendocument:xmlns:container',
    'opf': 'http://www.idpf.org/2007/opf',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'xhtml': 'http://www.w3.org/1999/xhtml',
    'epub': 'http://www.idpf.org/2007/ops',
    'ncx': 'http://www.daisy.org/z3986/2005/ncx/',
    'svg': 'http://www.w3.org/2000/svg',
    'xlink': 'http://www.w3.org/1999/xlink',
}
XHTML_TYPES = {'application/xhtml+xml'}
MIMETYPE = b'application/epub+zip'


class EpubError(Exception):
    """无法当作 EPUB 读取（缺 container、缺 OPF 等）。"""


@dataclass
class ParseNote:
    """解析时发生的容错，供 SEM-001 报告。"""
    path: str
    message: str


@dataclass
class ManifestItem:
    id: str
    href: str            # OPF 中原样的 href（相对 OPF，可能含 %xx）
    path: str            # 解析后的 zip 内路径
    media_type: str
    properties: set[str] = field(default_factory=set)
    element: etree._Element | None = None


def _strict_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)


def _recover_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, recover=True)


_BARE_AMP = re.compile(rb'&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)')

# XHTML 里常见、但在 XML 中未定义的 HTML 命名实体 → 数字引用
_HTML_ENTITIES = {
    b'nbsp': b'#160', b'ensp': b'#8194', b'emsp': b'#8195', b'thinsp': b'#8201',
    b'copy': b'#169', b'reg': b'#174', b'trade': b'#8482', b'hellip': b'#8230',
    b'mdash': b'#8212', b'ndash': b'#8211', b'lsquo': b'#8216', b'rsquo': b'#8217',
    b'ldquo': b'#8220', b'rdquo': b'#8221', b'middot': b'#183', b'times': b'#215',
    b'divide': b'#247', b'deg': b'#176', b'plusmn': b'#177', b'sup2': b'#178',
    b'sup3': b'#179', b'frac12': b'#189', b'laquo': b'#171', b'raquo': b'#187',
    b'bull': b'#8226', b'zwj': b'#8205', b'zwnj': b'#8204',
}
_XML_ENTITIES = {b'amp', b'lt', b'gt', b'quot', b'apos'}
_NAMED_ENTITY = re.compile(rb'&([A-Za-z][A-Za-z0-9]*);')


def _entity_to_numeric(m):
    name = m.group(1)
    if name in _XML_ENTITIES:
        return m.group(0)
    if name in _HTML_ENTITIES:
        return b'&' + _HTML_ENTITIES[name] + b';'
    return m.group(0)


def has_html_entities(data: bytes) -> bool:
    """是否含 XML 未定义的命名实体（&nbsp; 等）。EPUB 3 的 XHTML 不带 DTD，这些实体非法。"""
    return any(m.group(1) not in _XML_ENTITIES for m in _NAMED_ENTITY.finditer(data))


def repair_xml_bytes(data: bytes) -> bytes:
    """确定性的字节级修复：HTML 命名实体转数字引用、裸 & 转义。"""
    data = _NAMED_ENTITY.sub(_entity_to_numeric, data)
    return _BARE_AMP.sub(b'&amp;', data)


def parse_xml(data: bytes, path: str, notes: list[ParseNote]) -> etree._ElementTree:
    """严格解析；失败则先做确定性修复，再不行用 recover 模式（可能丢内容，记录在案）。

    HTML 命名实体（&nbsp; 等）总是先转成数字引用：否则在 resolve_entities=False 下，
    lxml 会把它们留成「实体引用节点」，后续按文字处理的规则看不到、会误删。
    """
    if has_html_entities(data):
        data = _NAMED_ENTITY.sub(_entity_to_numeric, data)
        notes.append(ParseNote(path, 'HTML 命名实体已转为字符'))
    try:
        return etree.ElementTree(etree.fromstring(data, _strict_parser()))
    except etree.XMLSyntaxError as e:
        first_error = str(e)
    fixed = repair_xml_bytes(data)
    try:
        tree = etree.ElementTree(etree.fromstring(fixed, _strict_parser()))
        notes.append(ParseNote(path, f'修复后可解析（实体/裸 &）：{first_error}'))
        return tree
    except etree.XMLSyntaxError:
        pass
    root = etree.fromstring(fixed, _recover_parser())
    if root is None:
        raise EpubError(f'{path}: 无法解析 XML：{first_error}')
    notes.append(ParseNote(path, f'以容错模式解析，可能有内容丢失：{first_error}'))
    return etree.ElementTree(root)


class Book:
    """一本 EPUB 的可修改表示。"""

    def __init__(self, files: dict[str, bytes], source_name: str = ''):
        self.files: dict[str, bytes] = files
        self.source_name = source_name
        self.parse_notes: list[ParseNote] = []
        self.zip_notes: list[str] = []
        self._trees: dict[str, etree._ElementTree] = {}
        self._dirty: set[str] = set()
        self.opf_path = self._find_opf()

    # ---------- 读取 ----------

    @classmethod
    def load(cls, path_or_bytes) -> 'Book':
        data = path_or_bytes if isinstance(path_or_bytes, bytes) else open(path_or_bytes, 'rb').read()
        name = '' if isinstance(path_or_bytes, bytes) else str(path_or_bytes)
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise EpubError(f'不是有效的 ZIP：{e}') from e
        files: dict[str, bytes] = {}
        notes: list[str] = []
        infos = z.infolist()
        if not infos or infos[0].filename != 'mimetype':
            notes.append('mimetype 不是第一个条目')
        for info in infos:
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                raise EpubError(f'条目已加密（可能有 DRM）：{info.filename}')
            if info.filename == 'mimetype':
                if info.compress_type != zipfile.ZIP_STORED:
                    notes.append('mimetype 被压缩')
                if info.extra:
                    notes.append('mimetype 带 extra field')
            files[info.filename] = z.read(info)
        if files.get('mimetype', b'').strip() != MIMETYPE:
            notes.append('mimetype 内容不正确或缺失')
        book = cls(files, name)
        book.zip_notes = notes
        return book

    def _find_opf(self) -> str:
        raw = self.files.get('META-INF/container.xml')
        if raw is None:
            # 容错：包里只有一个 .opf 时直接用它（STR-003 会重建 container）
            opfs = [p for p in self.files if p.lower().endswith('.opf')]
            if len(opfs) == 1:
                return opfs[0]
            raise EpubError('缺少 META-INF/container.xml')
        tree = parse_xml(raw, 'META-INF/container.xml', self.parse_notes)
        for rf in tree.iter(f'{{{NS["container"]}}}rootfile'):
            if rf.get('media-type', 'application/oebps-package+xml') == 'application/oebps-package+xml':
                full = unquote(rf.get('full-path', ''))
                if full in self.files:
                    return full
        opfs = [p for p in self.files if p.lower().endswith('.opf')]
        if len(opfs) == 1:
            return opfs[0]
        raise EpubError('container.xml 未指向存在的 OPF')

    # ---------- 路径 ----------

    @property
    def opf_dir(self) -> str:
        return posixpath.dirname(self.opf_path)

    @staticmethod
    def resolve(base_path: str, href: str) -> str:
        """把相对 base_path（某个 zip 内文件）的 href 解析为 zip 内路径（去掉 #片段）。"""
        href = unquote(href.split('#', 1)[0])
        if not href:
            return base_path
        return posixpath.normpath(posixpath.join(posixpath.dirname(base_path), href))

    @staticmethod
    def relative(from_path: str, to_path: str) -> str:
        """from_path 文件内引用 to_path 时应写的相对 href（已 %xx 编码）。"""
        rel = posixpath.relpath(to_path, posixpath.dirname(from_path) or '.')
        return quote(rel, safe="/-_.~!$&'()*+,;=:@")

    # ---------- 解析缓存 ----------

    def tree(self, path: str) -> etree._ElementTree:
        if path not in self._trees:
            if path not in self.files:
                raise KeyError(path)
            self._trees[path] = parse_xml(self.files[path], path, self.parse_notes)
        return self._trees[path]

    def mark_dirty(self, path: str) -> None:
        self._dirty.add(path)

    def set_bytes(self, path: str, data: bytes) -> None:
        self.files[path] = data
        self._trees.pop(path, None)
        self._dirty.discard(path)

    def delete(self, path: str) -> None:
        self.files.pop(path, None)
        self._trees.pop(path, None)
        self._dirty.discard(path)

    @property
    def opf(self) -> etree._Element:
        return self.tree(self.opf_path).getroot()

    @property
    def version(self) -> str:
        return self.opf.get('version', '')

    # ---------- manifest / spine ----------

    def manifest(self) -> list[ManifestItem]:
        items = []
        for el in self.opf.iterfind('opf:manifest/opf:item', NS):
            href = el.get('href', '')
            items.append(ManifestItem(
                id=el.get('id', ''), href=href, path=self.resolve(self.opf_path, href),
                media_type=el.get('media-type', ''),
                properties=set((el.get('properties') or '').split()), element=el))
        return items

    def item_by_id(self, item_id: str) -> ManifestItem | None:
        return next((i for i in self.manifest() if i.id == item_id), None)

    def item_by_path(self, path: str) -> ManifestItem | None:
        return next((i for i in self.manifest() if i.path == path), None)

    def spine_items(self) -> list[ManifestItem]:
        by_id = {i.id: i for i in self.manifest()}
        out = []
        for ref in self.opf.iterfind('opf:spine/opf:itemref', NS):
            it = by_id.get(ref.get('idref', ''))
            if it is not None:
                out.append(it)
        return out

    def content_docs(self) -> list[str]:
        """manifest 中所有 XHTML 内容文档（含 nav），按 spine 优先、其余随后。"""
        seen, out = set(), []
        for it in self.spine_items() + self.manifest():
            if it.media_type in XHTML_TYPES and it.path in self.files and it.path not in seen:
                seen.add(it.path)
                out.append(it.path)
        return out

    def add_item(self, path: str, media_type: str, item_id: str | None = None,
                 properties: str | None = None, data: bytes | None = None) -> ManifestItem:
        if data is not None:
            self.files[path] = data
        manifest = self.opf.find('opf:manifest', NS)
        existing = {i.id for i in self.manifest()}
        base = item_id or re.sub(r'[^A-Za-z0-9_.-]', '_', posixpath.basename(path)) or 'item'
        if not re.match(r'[A-Za-z_]', base):
            base = 'x' + base
        new_id, n = base, 1
        while new_id in existing:
            n += 1
            new_id = f'{base}-{n}'
        el = etree.SubElement(manifest, f'{{{NS["opf"]}}}item')
        el.set('id', new_id)
        el.set('href', self.relative(self.opf_path, path))
        el.set('media-type', media_type)
        if properties:
            el.set('properties', properties)
        self.mark_dirty(self.opf_path)
        return self.item_by_id(new_id)

    # ---------- 保存 ----------

    def serialize(self, path: str) -> bytes:
        root = self.tree(path).getroot()
        is_xhtml = root.tag == f'{{{NS["xhtml"]}}}html'
        body = etree.tostring(root, encoding='unicode')
        head = '<?xml version="1.0" encoding="utf-8"?>\n'
        if is_xhtml:
            if self.version.startswith('3'):
                head += '<!DOCTYPE html>\n'
            else:
                head += ('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
                         '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n')
        return (head + body + '\n').encode('utf-8')

    def flush(self) -> None:
        for path in sorted(self._dirty):
            if path in self._trees and path in self.files:
                self.files[path] = self.serialize(path)
        self._dirty.clear()

    def to_bytes(self) -> bytes:
        self.flush()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr(zipfile.ZipInfo('mimetype'), MIMETYPE, compress_type=zipfile.ZIP_STORED)
            order = ['META-INF/container.xml', self.opf_path]
            rest = sorted(p for p in self.files if p not in order and p != 'mimetype')
            for p in order + rest:
                if p in self.files:
                    info = zipfile.ZipInfo(p, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, self.files[p])
        return buf.getvalue()

    def save(self, path: str) -> None:
        with open(path, 'wb') as f:
            f.write(self.to_bytes())
