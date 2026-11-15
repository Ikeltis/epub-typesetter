"""TXT 转 EPUB（txtbook.py）与上传流程。测试文本现场构造，覆盖常见的几种 TXT 写法。"""
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from epub_typesetter import engine, epubcheck, txtbook
from epub_typesetter.book import Book

BODY = '这是一段足够长的正文，用来模拟小说里的普通段落，结尾有句号。'

# 网文常见：GB18030，一行一段，正文行首两个全角空格，标题不缩进；开头有广告和书名作者
WEBNOVEL = '\r\n'.join([
    '==========================================================',
    '更多精校小说尽在某某书屋下载：http://example.com/',
    '==========================================================',
    '书名：测试仙途', '作者：某甲', '', '内容简介：', '　　一句简介。', '', '第一卷', '',
    '第1章 下山', *(['　　' + BODY] * 30),
    '不缩进但很长的一段正文，不应该被当成标题，因为它太长了而且是完整的句子。',
    '　　1、准备材料', '　　2、出发',
    '第2章 进城', *(['　　' + BODY] * 30),
    '第二卷', '第1章 再出发', *(['　　' + BODY] * 30),
    '狐狸番外', *(['　　' + BODY] * 3),
])

# 空行分段、不缩进、中文数字章号、序和尾声；UTF-8 带 BOM
PLAIN = '\n\n'.join(['序', BODY, '第一章　开端', BODY, BODY, '1、不是标题的列表项', '第二章　发展', BODY,
                     '尾声', BODY]) + '\n'

# 英文硬换行（每段多行、空行分段）
ENGLISH = """CHAPTER I.

It was a bright cold day in April, and the clocks
were striking thirteen. Winston Smith hurried
home through the glass doors.

The hallway smelt of boiled cabbage and old rag
mats. At one end of it a coloured poster had been
tacked to the wall.

CHAPTER II.

As he put his hand to the door-knob Winston saw
that he had left the diary open on the table.
"""


def paras_of(text):
    ps = txtbook.paragraphs(text)
    txtbook.classify(ps)
    return ps


def test_webnovel_structure():
    raw = WEBNOVEL.encode('gb18030')
    ps = paras_of(txtbook.decode(raw))
    heads = [(p.kind, p.text) for p in ps if p.kind in ('part', 'chapter')]
    assert heads == [('chapter', '内容简介：'), ('part', '第一卷'), ('chapter', '第1章 下山'), ('chapter', '第2章 进城'),
                     ('part', '第二卷'), ('chapter', '第1章 再出发'), ('chapter', '狐狸番外')]
    assert sum(p.kind == 'hr' for p in ps) == 2                       # ==== 分隔行
    assert all(not p.text.startswith('　') for p in ps)               # 行首缩进已去掉
    assert txtbook.metadata(ps, 'x.txt') == ('测试仙途', '某甲')


def test_plain_blank_line_paragraphs():
    raw = b'\xef\xbb\xbf' + PLAIN.encode('utf-8')
    ps = paras_of(txtbook.decode(raw))
    heads = [p.text for p in ps if p.kind == 'chapter']
    assert heads == ['序', '第一章　开端', '第二章　发展', '尾声']
    assert any(p.text == '1、不是标题的列表项' and p.kind == 'p' for p in ps)


def test_english_hard_wrapped():
    ps = paras_of(ENGLISH)
    assert [p.text for p in ps if p.kind == 'chapter'] == ['CHAPTER I.', 'CHAPTER II.']
    body = [p.text for p in ps if p.kind == 'p']
    assert body[0].startswith('It was a bright cold day in April, and the clocks were striking thirteen.')
    assert len(body) == 3


def test_encodings():
    tc = '第一章　開始\n　　這是一個繁體中文的段落，我們來測試編碼。\n' * 3
    assert txtbook.decode(tc.encode('big5')) == tc
    sc = '第一章　开始\n　　这是一个简体中文的段落，我们来测试编码。\n' * 3
    assert txtbook.decode(sc.encode('gb18030')) == sc
    assert txtbook.decode(sc.encode('utf-16')) == sc
    with pytest.raises(txtbook.TxtError):
        txtbook.decode(bytes(range(256)) * 20)


def test_filename_metadata():
    assert txtbook._from_filename('半劫小仙 (o滴神) (z-library.sk, 1lib.sk, z-lib.sk).txt') == ('半劫小仙', 'o滴神')
    assert txtbook._from_filename('《三体》作者：刘慈欣.txt') == ('三体', '刘慈欣')
    assert txtbook._from_filename('无题.txt') == ('无题', '')


def test_to_epub_package():
    data = txtbook.to_epub(WEBNOVEL.encode('gb18030'), 'x.txt')
    assert zipfile.ZipFile(io.BytesIO(data)).namelist()[0] == 'mimetype'
    book = Book.load(data)
    assert not book.parse_notes
    docs = [it.path for it in book.spine_items()]
    assert len(docs) == 8                                    # 开头一份 + 7 个标题各一份
    first = book.files[docs[0]].decode('utf-8')
    assert '<hr/>' in first and '更多精校小说' in first       # 开头的其他文字原样保留（广告由确认板建议删除）
    assert '书名：' not in first and '作者：' not in first     # 已写进元数据的书名、作者行不留在正文
    assert '<h1>第一卷</h1>' in book.files[docs[2]].decode('utf-8')
    assert '<h2>第1章 下山</h2>' in book.files[docs[3]].decode('utf-8')
    ncx = book.files['OEBPS/toc.ncx'].decode('utf-8')
    # 部下面挂章：第一卷的 navPoint 在第 1 章之后才闭合
    assert ncx.index('第一卷') < ncx.index('第1章 下山') < ncx.index('第二卷')
    assert '<dc:creator>某甲</dc:creator>' in book.files['OEBPS/content.opf'].decode('utf-8')


def test_converted_txt_passes_epubcheck():
    book = Book.load(txtbook.to_epub(PLAIN.encode('utf-8'), '测试.txt'))
    engine.fix(book)
    msgs = epubcheck.run_bytes(book.to_bytes())
    if msgs is None:
        pytest.skip('没有 epubcheck')
    assert epubcheck.blocking(msgs) == 0, [m for m in msgs if m.severity in ('ERROR', 'FATAL')]


# ---------- 网页 ----------

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


def test_upload_txt(client):
    raw = WEBNOVEL.encode('gb18030')
    r = client.post('/api/books', files={'file': ('测试仙途.txt', raw, 'text/plain')})
    assert r.status_code == 201, r.text
    pid = r.json()['id']
    d = wait(client, pid)
    assert d['meta']['status'] == 'ready', d['meta']['message']
    assert d['meta']['source_format'] == 'txt' and d['meta']['title'] == '测试仙途'
    src = client.get(f'/api/books/{pid}/download?which=source')
    assert src.status_code == 200 and src.content == raw and src.headers['content-type'].startswith('text/plain')
    assert client.post(f'/api/books/{pid}/fix?mode=rebuild').status_code == 202
    d = wait(client, pid, done=('fixed', 'error'))
    assert d['meta']['status'] == 'fixed', d['meta']['message']
    assert d['fix']['text']['equal']


def test_upload_binary_txt_rejected(client):
    r = client.post('/api/books', files={'file': ('a.txt', bytes(range(256)) * 20, 'text/plain')})
    assert r.status_code == 400


def test_txt_source_ad_suggested_with_rules():
    """「==== / 更多精校小说尽在…下载：http://… / ====」列为零散广告行建议，勾选后连同分隔线一起删。"""
    from epub_typesetter.pipeline import optimize
    src = txtbook.to_epub(WEBNOVEL.encode('gb18030'), 'x.txt')
    o = optimize(Book.load(src))
    ads = [sg for sg in o.analysis.suggestions if sg['kind'] == 'ad']
    assert len(ads) == 1 and len(ads[0]['blocks']) == 3            # 广告行 + 上下两条分隔线
    book = Book.load(src)
    o = optimize(book, decisions={'items': {ads[0]['key']: True}})
    text = ''.join(book.files[p].decode('utf-8') for p in book.content_docs())
    assert '更多精校小说' not in text and '<hr' not in text
    assert sum(r == 'junk' for r, _ in o.rebuild.removed) == 3        # 删除清单里列出（广告 + 两条分隔线）
