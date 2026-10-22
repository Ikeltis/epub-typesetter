"""EPUB 2 → EPUB 3 升级（guide/00「版本选择」、guide/01）。

只做「规范层」的确定性转换，不碰排版：
- package@version=3.0；OPF 2 的 opf:role / opf:file-as / opf:scheme / opf:event 改为 EPUB 3 写法；
- 补 dcterms:modified；封面 meta → manifest properties="cover-image"；
- 旧 media-type 归一（字体、text/html）；按内容计算 manifest properties（svg/mathml/scripted/remote-resources）；
- 生成 nav.xhtml（优先由 NCX 转换，保持原目录结构；没有 NCX 再按标题生成），guide → landmarks；
- 保留 NCX 与 guide 作向后兼容；所有内容文档改用 HTML5 DOCTYPE 重新序列化。
"""
from __future__ import annotations

from datetime import datetime, timezone

from lxml import etree

from .book import NS, XHTML_TYPES, Book
from .nav import build_nav, default_nav_path, entries_from_headings, entries_from_ncx
from .xhtml import X, is_external

OPF = '{%s}' % NS['opf']
DC = '{%s}' % NS['dc']

MEDIA_TYPE_FIX = {
    'application/x-font-ttf': 'font/ttf',
    'application/x-font-truetype': 'font/ttf',
    'application/font-sfnt': 'font/ttf',
    'application/x-font-otf': 'font/otf',
    'application/x-font-opentype': 'font/otf',
    'application/vnd.ms-opentype': 'font/otf',
    'application/font-woff': 'font/woff',
    'application/x-font-woff': 'font/woff',
    'text/html': 'application/xhtml+xml',
}
LANDMARK_FROM_GUIDE = {'cover': 'cover', 'toc': 'toc', 'text': 'bodymatter', 'start': 'bodymatter',
                       'preface': 'preface', 'foreword': 'foreword', 'copyright-page': 'copyright-page',
                       'title-page': 'titlepage', 'colophon': 'colophon', 'bibliography': 'bibliography',
                       'glossary': 'glossary', 'index': 'index', 'acknowledgements': 'acknowledgments',
                       'dedication': 'dedication', 'epigraph': 'epigraph', 'loi': 'loi', 'lot': 'lot',
                       'notes': 'endnotes'}
LANDMARK_LABEL = {'cover': '封面', 'toc': '目录', 'bodymatter': '正文', 'titlepage': '书名页',
                  'copyright-page': '版权页', 'preface': '前言', 'foreword': '序', 'colophon': '版本记录',
                  'bibliography': '参考文献', 'glossary': '术语表', 'index': '索引',
                  'acknowledgments': '致谢', 'dedication': '献辞', 'epigraph': '题记', 'loi': '插图目录',
                  'lot': '表格目录', 'endnotes': '注释'}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def book_language(book: Book) -> str:
    el = book.opf.find('opf:metadata/dc:language', NS)
    return (el.text or '').strip() if el is not None else ''


def _metadata(book: Book) -> etree._Element:
    return book.opf.find('opf:metadata', NS)


def _meta(md: etree._Element, prop: str, value: str, refines: str | None = None,
          scheme: str | None = None) -> etree._Element:
    el = etree.SubElement(md, OPF + 'meta')
    if refines:
        el.set('refines', refines)
    el.set('property', prop)
    if scheme:
        el.set('scheme', scheme)
    el.text = value
    return el


def _ensure_id(el: etree._Element, prefix: str, taken: set[str]) -> str:
    if el.get('id'):
        return el.get('id')
    n = 1
    while f'{prefix}{n}' in taken:
        n += 1
    el.set('id', f'{prefix}{n}')
    taken.add(f'{prefix}{n}')
    return el.get('id')


def upgrade_metadata(book: Book) -> list[str]:
    log = []
    md = _metadata(book)
    taken = {e.get('id') for e in book.opf.iter() if isinstance(e.tag, str) and e.get('id')}
    opf_attr = lambda name: OPF + name  # noqa: E731

    for el in list(md):
        if not isinstance(el.tag, str):
            continue
        role, file_as = el.get(opf_attr('role')), el.get(opf_attr('file-as'))
        if role or file_as:
            rid = _ensure_id(el, 'creator', taken)
            if role:
                _meta(md, 'role', role, f'#{rid}', 'marc:relators')
            if file_as:
                _meta(md, 'file-as', file_as, f'#{rid}')
        for a in ('role', 'file-as', 'scheme', 'event'):
            el.attrib.pop(opf_attr(a), None)
    # EPUB 3 中 dc:date 至多一个：保留第一个
    dates = md.findall('dc:date', NS)
    for d in dates[1:]:
        md.remove(d)
    if len(dates) > 1:
        log.append(f'删除多余的 dc:date {len(dates) - 1} 个（EPUB 3 只允许一个）')
    if md.find("opf:meta[@property='dcterms:modified']", NS) is None:
        _meta(md, 'dcterms:modified', now_utc())
        log.append('补 dcterms:modified')
    log.append('元数据改为 EPUB 3 写法（opf:role/file-as → refines meta）')
    return log


def upgrade_manifest(book: Book) -> list[str]:
    log = []
    md = _metadata(book)
    cover_meta = md.find("opf:meta[@name='cover']", NS)
    cover_id = cover_meta.get('content') if cover_meta is not None else None
    for it in book.manifest():
        new_mt = MEDIA_TYPE_FIX.get(it.media_type)
        if new_mt:
            it.element.set('media-type', new_mt)
            log.append(f'media-type {it.media_type} → {new_mt}：{it.href}')
            it.media_type = new_mt
        if it.id == cover_id and it.media_type.startswith('image/'):
            it.properties.add('cover-image')
        if it.media_type in XHTML_TYPES and it.path in book.files:
            props = content_properties(book, it.path)
            it.properties = (it.properties - {'svg', 'mathml', 'scripted', 'remote-resources'}) | props
        if it.properties:
            it.element.set('properties', ' '.join(sorted(it.properties)))
    return log


def content_properties(book: Book, path: str) -> set[str]:
    root = book.tree(path).getroot()
    props = set()
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        ns = el.tag[1:].split('}')[0] if el.tag.startswith('{') else ''
        if ns == NS['svg']:
            props.add('svg')
        elif ns == 'http://www.w3.org/1998/Math/MathML':
            props.add('mathml')
        if el.tag == X + 'script':
            props.add('scripted')
        if el.tag in (X + 'img', X + 'audio', X + 'video', X + 'source', X + 'link', X + 'iframe'):
            v = el.get('src') or (el.get('href') if el.tag == X + 'link' else None)
            if v and is_external(v) and v.lower().startswith(('http:', 'https:')):
                props.add('remote-resources')
    return props


def landmarks_from_guide(book: Book) -> list[tuple[str, str, str]]:
    out, seen = [], set()
    for ref in book.opf.iterfind('opf:guide/opf:reference', NS):
        t = LANDMARK_FROM_GUIDE.get((ref.get('type') or '').lower())
        href = ref.get('href', '')
        if not t or t in seen or not href:
            continue
        path = Book.resolve(book.opf_path, href)
        it = book.item_by_path(path)
        if it is None or it.media_type not in XHTML_TYPES:
            continue        # 指向图片等非内容文档的 guide 项不能进 landmarks
        frag = href.partition('#')[2]
        out.append((t, ref.get('title') or LANDMARK_LABEL.get(t, t), path + (f'#{frag}' if frag else '')))
        seen.add(t)
    return out


def generate_nav(book: Book) -> tuple[str, list[str]]:
    """生成并登记 nav.xhtml，返回 (nav 路径, 修改记录)。"""
    entries = entries_from_ncx(book)
    source = 'NCX'
    if not entries:
        entries = entries_from_headings(book)
        source = '正文标题'
    nav_path = default_nav_path(book)
    landmarks = landmarks_from_guide(book)
    # 不自动加指向 nav 自身的 toc landmark：nav 不在 spine 中时 epubcheck 报 RSC-011
    if not any(t == 'bodymatter' for t, _, _ in landmarks) and entries:
        landmarks.append(('bodymatter', '正文', entries[0].path))
    lang = book_language(book)
    data = build_nav(book, nav_path, entries, landmarks, lang)
    book.add_item(nav_path, 'application/xhtml+xml', item_id='nav', properties='nav', data=data)
    return nav_path, [f'生成 {nav_path}（来源：{source}，{len(entries)} 个目录项，{len(landmarks)} 个 landmarks）']


def upgrade_to_3(book: Book) -> list[str]:
    old = book.version
    log = [f'EPUB {old} → 3.0']
    book.opf.set('version', '3.0')
    log += upgrade_metadata(book)
    log += upgrade_manifest(book)
    if not any('nav' in i.properties for i in book.manifest()):
        _, l2 = generate_nav(book)
        log += l2
    n = 0
    for it in book.manifest():
        if it.media_type in XHTML_TYPES and it.path in book.files:
            book.tree(it.path)
            book.mark_dirty(it.path)      # 用 HTML5 DOCTYPE 重新序列化
            n += 1
    log.append(f'{n} 个内容文档改用 HTML5 DOCTYPE')
    book.mark_dirty(book.opf_path)
    return log
