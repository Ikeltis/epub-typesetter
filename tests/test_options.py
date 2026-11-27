"""排版重建的按书选项（options.py）：识别开关与外观。"""
import shutil

from epub_typesetter import epubcheck, options
from epub_typesetter.book import Book
from epub_typesetter.pipeline import optimize
from epub_typesetter.rebuild import REMOVED_ROLES
from epub_typesetter.textcheck import compare_blocks
from epub_typesetter.xhtml import X

from conftest import XHTML11, make_epub

P = '<p>' + '正文叙述，' * 8 + '。</p>'
C1 = ('<h1>第一章</h1>' + P + '<p>正文<a id="r1" href="c2.xhtml#n1">[1]</a>继续。</p>' + P +
      '<p>他念道：</p><p>世人都晓神仙好，惟有功名忘不了！</p><p>古今将相在何方？荒冢一堆草没了。</p>' + P)
C2 = '<h1>第二章</h1>' + P + '<p id="n1"><a href="c1.xhtml#r1">[1]</a>这是注释。</p>'


def build(opts):
    src = make_epub({'OEBPS/Text/c1.xhtml': XHTML11.format(title='一', body=C1),
                     'OEBPS/Text/c2.xhtml': XHTML11.format(title='二', body=C2)})
    b = Book.load(src)
    rep = optimize(b, options=opts)
    data = b.to_bytes()
    out = Book.load(data)
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok
    if shutil.which('epubcheck'):
        assert epubcheck.blocking(epubcheck.run_bytes(data)) == 0
    return out, rep


def text_of(book):
    return ''.join(''.join(book.tree(p).getroot().itertext()) for p in book.content_docs())


def css(book):
    return next(book.files[p].decode() for p in book.files if p.endswith('typesetter.css'))


def test_defaults_unchanged():
    assert options.clean(None) == options.defaults() and options.changed({}) == [] and options.style_css({}) == ''
    assert options.clean({'features': {'notes': 'x', 'bogus': False}, 'style': {'line_height': '9'}}) == options.defaults()


def test_features_off_keep_content_in_place():
    on, rep_on = build(None)
    assert rep_on.rebuild.notes == 1 and any(p.endswith('endnotes.xhtml') for p in on.files)
    assert 'stanza' in ''.join(on.files[p].decode() for p in on.content_docs())
    off, rep_off = build({'features': {'notes': False, 'poem': False}})
    assert rep_off.rebuild.notes == 0 and not any(p.endswith('endnotes.xhtml') for p in off.files)
    html = ''.join(off.files[p].decode() for p in off.content_docs())
    assert 'stanza' not in html and '这是注释。' in text_of(off) and '[1]' in text_of(off)
    assert options.changed({'features': {'notes': False, 'poem': False}}) == ['注释留在原处', '不识别诗歌']


def test_style_overrides_appended():
    o = {'style': {'heading_align': 'center', 'paragraph': 'spaced', 'line_height': '1.8', 'heading_font': 'serif'}}
    out, rep = build(o)
    c = css(out)
    tail = c[c.index('按书选项'):]
    assert 'text-align:center' in tail and 'text-indent:0; margin:.6em 0' in tail and 'line-height:1.8' in tail
    assert 'Noto Serif CJK SC' in tail
    assert options.changed(o) == ['标题字体宋体', '标题对齐居中', '段落不缩进，段间空开', '行高1.8']


def build_img(body, opts=None):
    src = make_epub({'OEBPS/Text/c1.xhtml': XHTML11.format(title='一', body=body),
                     'OEBPS/Images/big.png': _png(1200, 800)})
    b = Book.load(src)
    rep = optimize(b, options=opts)
    out = Book.load(b.to_bytes())
    assert compare_blocks(rep.analysis.blocks, REMOVED_ROLES, out).ok
    return out


def _png(w, h):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (200, 100, 50)).save(buf, 'PNG')
    return buf.getvalue()


def figures(book):
    return [(f.get('class'), [i.get('class') for i in f.iter(X + 'img')])
            for p in book.content_docs() for f in book.tree(p).getroot().iter(X + 'figure')]


IMG_BODY = ('<h1>第一章</h1>' + P +
            '<div style="text-align:left"><img src="../Images/big.png" style="width:20%"/></div>' + P +
            '<p><img src="../Images/big.png" width="420"/></p>' + P +
            '<div style="float:right"><img src="../Images/big.png"/></div>' + P)


def test_image_size_and_place_follow_original_by_default():
    out = build_img(IMG_BODY)
    assert figures(out) == [('fig-left', ['w-20']), (None, ['w-70']), ('float-right', [None])]   # 420/600 = 70%
    c = css(out)
    assert 'figure img.w-20{ width:20%; }' in c and 'figure.fig-left img{ margin-left:0' in c
    assert 'figure.float-right' in c                                                          # 绕排模板


def test_image_size_options():
    out = build_img(IMG_BODY, {'style': {'image_width': '60', 'image_align': 'center'}})
    assert figures(out) == [(None, [None])] * 3
    assert 'figure img{ width:60%; }' in css(out)
    out = build_img(IMG_BODY, {'style': {'image_width': 'natural'}})
    assert [f[1] for f in figures(out)] == [[None], [None], [None]] and figures(out)[0][0] == 'fig-left'
