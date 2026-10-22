import io
import zipfile

import pytest

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF2 = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>测试书</dc:title>
    <dc:creator opf:role="aut" opf:file-as="Zhang San">张三</dc:creator>
    <dc:identifier id="bookid" opf:scheme="uuid">urn:uuid:12345678-1234-1234-1234-123456789abc</dc:identifier>
    <dc:language>zh</dc:language>
    <meta name="cover" content="cover-img"/>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="c1" href="Text/c1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="Text/c2.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover-img" href="Images/cover.jpg" media-type="image/jpeg"/>
  </manifest>
  <spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine>
  <guide><reference type="cover" title="封面" href="Images/cover.jpg"/>
         <reference type="text" title="正文" href="Text/c1.xhtml"/></guide>
</package>"""

NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
  <head><meta name="dtb:uid" content="urn:uuid:12345678-1234-1234-1234-123456789abc"/></head>
  <docTitle><text>测试书</text></docTitle>
  <navMap>
    <navPoint id="n1" playOrder="1"><navLabel><text>第一章</text></navLabel><content src="Text/c1.xhtml"/>
      <navPoint id="n1a" playOrder="2"><navLabel><text>第一节</text></navLabel><content src="Text/c1.xhtml#s1"/></navPoint>
    </navPoint>
    <navPoint id="n2" playOrder="3"><navLabel><text>第二章</text></navLabel><content src="Text/c2.xhtml"/></navPoint>
  </navMap>
</ncx>"""

XHTML11 = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>
<body>{body}</body></html>"""

def _img(fmt: str) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (60, 80), (200, 180, 160)).save(buf, fmt)
    return buf.getvalue()


JPEG = _img('JPEG')
PNG = _img('PNG')


def make_epub(files: dict[str, bytes | str] | None = None, *, mimetype_first=True,
              compress_mimetype=False, drop: tuple[str, ...] = ()) -> bytes:
    """构造最小测试 EPUB。files 覆盖/追加默认文件；值为 None 表示删除。"""
    base = {
        'META-INF/container.xml': CONTAINER,
        'OEBPS/content.opf': OPF2,
        'OEBPS/toc.ncx': NCX,
        'OEBPS/Text/c1.xhtml': XHTML11.format(title='第一章', body='<h1>第一章</h1><h2 id="s1">第一节</h2><p>正文一。</p>'),
        'OEBPS/Text/c2.xhtml': XHTML11.format(title='第二章', body='<h1>第二章</h1><p>正文二。</p>'),
        'OEBPS/Images/cover.jpg': JPEG,
    }
    base.update(files or {})
    for d in drop:
        base.pop(d, None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        mt = zipfile.ZipInfo('mimetype')
        mt.compress_type = zipfile.ZIP_DEFLATED if compress_mimetype else zipfile.ZIP_STORED
        if mimetype_first:
            z.writestr(mt, 'application/epub+zip')
        for name, data in base.items():
            if data is None:
                continue
            z.writestr(name, data.encode('utf-8') if isinstance(data, str) else data,
                       compress_type=zipfile.ZIP_DEFLATED)
        if not mimetype_first:
            z.writestr(mt, 'application/epub+zip')
    return buf.getvalue()


@pytest.fixture
def epub_bytes():
    return make_epub()
