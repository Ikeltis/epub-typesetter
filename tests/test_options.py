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
