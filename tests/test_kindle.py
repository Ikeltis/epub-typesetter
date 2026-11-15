"""Kindle 格式转换（kindle.py）与上传流程。

仓库里没有可公开的真 Kindle 文件：文件头用最小的 PalmDB 结构现场构造；旧格式打包用模拟的
KindleUnpack 输出目录；网页流程把真正的转换换成假实现。真书的转换在本机用实际文件验证过。
"""
import io
import struct
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from conftest import make_epub
from epub_typesetter import engine, epubcheck, kindle
from epub_typesetter.book import Book


def palmdb(encryption: int = 0) -> bytes:
    """最小的 MOBI 文件头：PalmDB 头 + 一条记录表项 + 第 0 条记录（MOBI 头的前 16 字节）。"""
    head = b'Test Book'.ljust(32, b'\0') + b'\0' * 28 + b'BOOKMOBI' + b'\0' * 8 + struct.pack('>H', 1)
    rec0_off = len(head) + 8 + 2
    head += struct.pack('>LL', rec0_off, 0) + b'\0\0'
    rec0 = struct.pack('>HHLHHH', 2, 0, 1000, 1, 4096, encryption) + b'\0\0'
    return head + rec0 + b'MOBI' + b'\0' * 200


def test_check_formats():
    kindle.check(palmdb(0))                                   # 未加密：通过
    for enc in (1, 2):
        with pytest.raises(kindle.KindleError, match='DRM'):
            kindle.check(palmdb(enc))
    with pytest.raises(kindle.KindleError, match='KFX'):
        kindle.check(b'\xeaDRMION\xee' + b'\0' * 100)
    with pytest.raises(kindle.KindleError, match='KFX'):
        kindle.check(b'CONT' + b'\0' * 100)
    with pytest.raises(kindle.KindleError):
        kindle.check(b'hello world' * 10)
    assert kindle.ext_of('书.AZW3') == 'azw3' and kindle.ext_of('x') == ''


# ---------- 旧格式（MOBI 6）打包 ----------

BOOK_HTML = """<html><head><meta http-equiv="content-type" content="text/html; charset=utf-8" />\
<guide><reference type="toc" title="目录" filepos=0000000300 /></guide></head><body>\
<p height="0pt" width="0pt" align="center"><img src="Images/a.png" width="10" height="10"></img></p>\
<mbp:pagebreak/><a id="filepos200"></a><p align="center"><font size="4"><b>第一章 开端</b></font></p>\
<p width="2em" height="1em" align="justify">正文第一段，见<a href="#filepos300">第二章</a>。\x01</p>\
<!-- 注释 --><mbp:section><p width="-1em">悬挂缩进的一段</p></mbp:section>\
<mbp:pagebreak/><a id="filepos300"></a><p align="center"><font size="4"><b>第二章 结束</b></font></p>\
<p width="2em">正文第二段，回到<a href="#filepos200">第一章</a>。</p><mbp:pagebreak/>\
</body></html>"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
<dc:title>测试旧格式</dc:title><dc:language>zh</dc:language><dc:identifier id="uid">123</dc:identifier>
<meta name="cover" content="cover_img" />
<!-- BEGIN INFORMATION ONLY <meta name="ASIN" content="x" /> END INFORMATION ONLY -->
</metadata>
<manifest>
<item id="item0" media-type="text/html" href="book.html" />
<item id="cover_img" media-type="image/png" href="Images/a.png" />
<item id="ncx" media-type="application/x-dtbncx+xml" href="toc.ncx" />
</manifest>
<spine toc="ncx"><itemref idref="item0"/></spine>
<tours></tours>
<guide><reference type="text" title="start" href="book.html#filepos200" /></guide>
</package>"""

NCX = """<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta content="123" name="dtb:uid"/></head>
<docTitle><text>测试旧格式</text></docTitle><navMap>
<navPoint id="np_1" playOrder="1"><navLabel><text>第一章 开端</text></navLabel><content src="book.html#filepos200"/></navPoint>
<navPoint id="np_2" playOrder="2"><navLabel><text>第二章 结束</text></navLabel><content src="book.html#filepos300"/></navPoint>
</navMap></ncx>"""


@pytest.fixture
def mobi7(tmp_path):
    from conftest import _img
    d = tmp_path / 'mobi7'
    (d / 'Images').mkdir(parents=True)
    (d / 'book.html').write_bytes(BOOK_HTML.encode('utf-8'))
    (d / 'content.opf').write_text(OPF, encoding='utf-8')
    (d / 'toc.ncx').write_text(NCX, encoding='utf-8')
    (d / 'Images' / 'a.png').write_bytes(_img('PNG'))
    return d


def test_pack_mobi7(mobi7):
    data = kindle.pack_mobi7(str(mobi7))
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.namelist()[0] == 'mimetype' and z.getinfo('mimetype').compress_type == zipfile.ZIP_STORED
    book = Book.load(data)
    assert not book.parse_notes, book.parse_notes                       # 各文件都是合法 XML
    docs = [it.path for it in book.spine_items()]
    assert docs == ['OEBPS/part0001.xhtml', 'OEBPS/part0002.xhtml', 'OEBPS/part0003.xhtml']   # 按分页符拆，空的不要
    assert 'OEBPS/book.html' not in book.files and 'OEBPS/Images/a.png' in book.files
    x = lambda p: book.files[p].decode('utf-8')                        # noqa: E731
    assert 'mbp:' not in ''.join(x(p) for p in docs) and '\x01' not in x(docs[1])
    # 跨文件链接改到拆出的文件；同文件的不动
    assert 'href="part0003.xhtml#filepos300"' in x(docs[1]) and 'href="part0002.xhtml#filepos200"' in x(docs[2])
    # MOBI 段落属性 → CSS（width 是首行缩进，height 是段前空白；0 不写）
    assert 'text-indent: 2em; margin-top: 1em' in x(docs[1]) and 'text-indent: -1em' in x(docs[1])
    assert 'width="0pt"' not in x(docs[0]) and 'text-indent' not in x(docs[0])
    ncx = book.files['OEBPS/toc.ncx'].decode('utf-8')
    assert 'src="part0002.xhtml#filepos200"' in ncx and 'src="part0003.xhtml#filepos300"' in ncx
    opf = book.files['OEBPS/content.opf'].decode('utf-8')
    assert 'part0002.xhtml#filepos200' in opf and 'tours' not in opf and 'INFORMATION ONLY' not in opf
    text = ''.join(''.join(book.tree(p).getroot().itertext()) for p in docs)
    for s in ('第一章 开端', '正文第一段', '悬挂缩进的一段', '第二章 结束', '正文第二段'):
        assert s in text


def test_packed_mobi7_survives_pipeline(mobi7):
    """打包结果交给规范修复后应能通过 epubcheck（旧标记由 SEM-015 等规则清理）。"""
    book = Book.load(kindle.pack_mobi7(str(mobi7)))
    engine.fix(book)
    assert book.version.startswith('3')
    msgs = epubcheck.run_bytes(book.to_bytes())
    if msgs is None:
        pytest.skip('没有 epubcheck')
    assert epubcheck.blocking(msgs) == 0, [m for m in msgs if m.severity in ('ERROR', 'FATAL')]


# ---------- 网页：上传 Kindle 文件 ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    from epub_typesetter.web import store
    monkeypatch.setattr(store, 'DATA_DIR', str(tmp_path))
    from epub_typesetter.web.app import app
    return TestClient(app)


def wait(client, pid, done=('ready', 'fixed', 'error'), timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        r = client.get(f'/api/books/{pid}').json()
        if r['meta']['status'] in done:
            return r
        time.sleep(0.2)
    raise AssertionError('timeout')


def test_upload_kindle(client, monkeypatch):
    monkeypatch.setattr(kindle, 'available', lambda: True)
    monkeypatch.setattr(kindle, 'to_epub', lambda data, ext='azw3', timeout=300: make_epub())
    raw = palmdb(0)
    r = client.post('/api/books', files={'file': ('测试书.azw3', raw, 'application/octet-stream')})
    assert r.status_code == 201, r.text
    pid = r.json()['id']
    d = wait(client, pid)
    assert d['meta']['status'] == 'ready', d['meta']['message']
    assert d['meta']['source_format'] == 'azw3' and d['meta']['title'] == '测试书'
    src = client.get(f'/api/books/{pid}/download?which=source')
    assert src.status_code == 200 and src.content == raw
    assert '.azw3' in src.headers['content-disposition']
    orig = client.get(f'/api/books/{pid}/download?which=original')
    assert orig.status_code == 200 and zipfile.ZipFile(io.BytesIO(orig.content)).namelist()[0] == 'mimetype'
    assert '%E6%B5%8B%E8%AF%95%E4%B9%A6.epub' in orig.headers['content-disposition']     # 「测试书.epub」


def test_upload_kindle_rejected(client, monkeypatch):
    monkeypatch.setattr(kindle, 'available', lambda: True)
    r = client.post('/api/books', files={'file': ('drm.azw', palmdb(2), 'application/octet-stream')})
    assert r.status_code == 400 and 'DRM' in r.json()['detail']
    r = client.post('/api/books', files={'file': ('a.txt', b'hello' * 30, 'text/plain')})
    assert r.status_code == 400
    monkeypatch.setattr(kindle, 'available', lambda: False)
    r = client.post('/api/books', files={'file': ('a.mobi', palmdb(0), 'application/octet-stream')})
    assert r.status_code == 400 and 'KindleUnpack' in r.json()['detail']


def test_convert_failure_reported(client, monkeypatch):
    monkeypatch.setattr(kindle, 'available', lambda: True)

    def boom(data, ext='azw3', timeout=300):
        raise kindle.KindleError('转换失败：测试')
    monkeypatch.setattr(kindle, 'to_epub', boom)
    pid = client.post('/api/books', files={'file': ('x.mobi', palmdb(0), 'application/octet-stream')}).json()['id']
    d = wait(client, pid)
    assert d['meta']['status'] == 'error' and d['meta']['message'] == '转换失败：测试'


def test_real_unpack_tool_rejects_garbage():
    """装了 mobiunpack 时：头像 MOBI、内容是垃圾的文件应报转换失败，而不是崩溃或卡住。"""
    if not kindle.available():
        pytest.skip('没有 mobiunpack')
    with pytest.raises(kindle.KindleError):
        kindle.to_epub(palmdb(0), 'mobi', timeout=60)


# ---------- KindleUnpack 输出的清理、只有图片的标题 ----------

def test_tidy_kindleunpack_leftovers():
    from conftest import OPF2
    opf = (OPF2.replace('<dc:language>zh</dc:language>', '<dc:language>zh</dc:language><dc:publisher></dc:publisher>')
           .replace('<spine toc="ncx">', '<spine toc="ncx" page-map="map">')
           .replace('</spine>', '</spine><tours></tours>')
           .replace('</manifest>', '<item id="nav" href="Text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>'))
    nav = ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
           'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head><body><nav epub:type="toc"><ol>'
           '<li><a href="c1.xhtml">第一章</a></li><li><a href="c2.xhtml"><img src="../Images/cover.jpg" alt=""/></a></li>'
           '<li><a href="c1.xhtml"></a><ol><li><a href="c1.xhtml#s1">第一节</a></li></ol></li></ol></nav></body></html>')
    book = Book.load(kindle.tidy(make_epub({'OEBPS/content.opf': opf, 'OEBPS/Text/nav.xhtml': nav})))
    o = book.files['OEBPS/content.opf'].decode('utf-8')
    assert 'tours' not in o and 'page-map' not in o and 'publisher' not in o and '测试书' in o
    n = book.files['OEBPS/Text/nav.xhtml'].decode('utf-8')
    assert 'c2.xhtml' not in n                          # 没文字也没下级的条目去掉
    assert '<a href="c1.xhtml">第一节</a>' in n          # 有下级的空条目借用第一个下级的文字


def test_image_only_heading_gets_nav_label():
    """只有图片的标题（如花饰分隔页）重建后，导航条目不能是空链接。"""
    from epub_typesetter.pipeline import optimize
    from conftest import XHTML11
    c2 = XHTML11.format(title='第二章', body='<h1><img src="../Images/cover.jpg" alt=""/></h1><p>正文二。</p>')
    book = Book.load(make_epub({'OEBPS/Text/c2.xhtml': c2}))
    optimize(book)
    nav = next(it.path for it in book.manifest() if 'nav' in it.properties)
    root = book.tree(nav).getroot()
    anchors = list(root.iter('{http://www.w3.org/1999/xhtml}a'))
    assert anchors and all(''.join(a.itertext()).strip() for a in anchors)
