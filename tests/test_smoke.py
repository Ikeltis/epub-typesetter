import shutil

import epub_typesetter


def test_version():
    assert epub_typesetter.__version__


def test_epubcheck_available():
    assert shutil.which("epubcheck")


def test_utf8_locale():
    # epubcheck(Java) 依赖 UTF-8 locale 才能打开中文文件名；缺失时会静默返回 0 条消息
    import locale
    assert locale.getpreferredencoding().lower().replace("-", "") == "utf8"
