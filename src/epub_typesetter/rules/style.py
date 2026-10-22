"""STY：样式表（guide/07 §2.3、guide/03）。

M0 只做不改变外观的清理：
- STY-001：去掉会让解析器出错的东西（混入的分隔符/零宽字符、空值声明、语法错误的声明、
  无效选择器的规则）。阅读器遇到这些本来就会丢弃，所以删掉不改变显示效果。
- STY-002：@font-face 里指向包内不存在文件的 url 删除（字体本来就加载不到）。
"""
from __future__ import annotations

import re

import cssselect
import tinycss2

from ..book import Book
from ..engine import AUTO, ERROR, SUGGEST, WARNING, Rule, register
from ..xhtml import css_paths, is_external

# CSS 不认作空白、却常被混进样式表的不可见字符（不动 nbsp/全角空格：它们可能在 content 字符串里）
JUNK_CHARS = re.compile('[\u2028\u2029\ufeff\u200b]')


def _valid_selector(prelude: str) -> bool:
    try:
        cssselect.parse(prelude)
        return True
    except Exception:
        return False


def _clean_declarations(content) -> tuple[str, int]:
    """返回 (清理后的声明块文本, 删除数)。"""
    out, dropped = [], 0
    for node in tinycss2.parse_blocks_contents(content, skip_whitespace=False, skip_comments=False):
        if node.type == 'declaration':
            value = tinycss2.serialize(node.value).strip()
            if not value:
                dropped += 1
                continue
            imp = ' !important' if node.important else ''
            out.append(f'{node.name}: {value}{imp};')
        elif node.type == 'error':
            dropped += 1
        elif node.type == 'comment':
            out.append(f'/*{node.value}*/')
        elif node.type in ('qualified-rule', 'at-rule'):
            out.append(node.serialize())         # 嵌套规则原样保留
    return '\n  ' + '\n  '.join(out) + '\n', dropped


def _block_needs_clean(content) -> bool:
    for node in tinycss2.parse_blocks_contents(content, skip_whitespace=True, skip_comments=True):
        if node.type == 'error':
            return True
        if node.type == 'declaration' and not tinycss2.serialize(node.value).strip():
            return True
    return False


def clean_css(css: str) -> tuple[str, list[str]]:
    """返回 (新 CSS, 问题说明列表)；无问题时原样返回、列表为空。"""
    problems = []
    cleaned = JUNK_CHARS.sub(' ', css)
    if cleaned != css:
        problems.append('混入的分隔符/零宽/全角空白字符')
    rules = tinycss2.parse_stylesheet(cleaned, skip_whitespace=False, skip_comments=False)
    out, changed = [], bool(problems)
    for node in rules:
        if node.type == 'error':
            problems.append(f'语法错误：{node.message}')
            changed = True
            continue
        if node.type == 'qualified-rule':
            prelude = tinycss2.serialize(node.prelude).strip()
            if not _valid_selector(prelude):
                problems.append(f'无效选择器：{prelude[:40]}')
                changed = True
                continue
            if _block_needs_clean(node.content):
                body, n = _clean_declarations(node.content)
                problems.append(f'{prelude[:30]} 中删除无效声明 {n} 个')
                out.append(f'{prelude} {{{body}}}')
                changed = True
                continue
        elif node.type == 'at-rule' and node.content is not None and node.lower_at_keyword in ('font-face', 'page'):
            if _block_needs_clean(node.content):
                body, n = _clean_declarations(node.content)
                problems.append(f'@{node.lower_at_keyword} 中删除无效声明 {n} 个')
                out.append(f'@{node.at_keyword}{tinycss2.serialize(node.prelude)}{{{body}}}')
                changed = True
                continue
        elif node.type == 'at-rule' and node.content is not None and node.lower_at_keyword in ('media', 'supports'):
            inner, p2 = clean_css(tinycss2.serialize(node.content))
            if p2:
                problems += [f'@{node.lower_at_keyword} 内：{p}' for p in p2]
                out.append(f'@{node.at_keyword}{tinycss2.serialize(node.prelude)}{{{inner}}}')
                changed = True
                continue
        out.append(node.serialize())
    return (''.join(out) if changed else css), problems


@register
class CssParseable(Rule):
    id, title, order = 'STY-001', '样式表可被解析', 40

    def check(self, book):
        out = []
        for path in css_paths(book):
            css = book.files[path].decode('utf-8', 'replace')
            _, problems = clean_css(css)
            if problems:
                out.append(self.issue(ERROR, f'{len(problems)} 处问题：{"；".join(problems[:3])}', path, AUTO))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            new, problems = clean_css(book.files[i.file].decode('utf-8', 'replace'))
            book.set_bytes(i.file, new.encode('utf-8'))
            log.append(f'{i.file}：{"；".join(problems[:5])}')
        return log


def _split_commas(tokens):
    parts, cur = [], []
    for t in tokens:
        if t.type == 'literal' and t.value == ',':
            parts.append(cur)
            cur = []
        else:
            cur.append(t)
    parts.append(cur)
    return parts


def _urls(tokens):
    for t in tokens:
        if t.type == 'url':
            yield t.value
        elif t.type == 'function' and t.lower_name == 'url':
            for a in t.arguments:
                if a.type == 'string':
                    yield a.value


def _missing_font_srcs(book: Book, css_path: str, css: str):
    """[(@font-face 节点, src 中缺失的 url 列表, 剩余可用部分数)]"""
    out = []
    for node in tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True):
        if node.type != 'at-rule' or node.lower_at_keyword != 'font-face' or node.content is None:
            continue
        for d in tinycss2.parse_blocks_contents(node.content, skip_whitespace=True, skip_comments=True):
            if d.type == 'declaration' and d.lower_name == 'src':
                parts = _split_commas(d.value)
                missing, ok = [], 0
                for part in parts:
                    urls = list(_urls(part))
                    bad = [u for u in urls if not is_external(u) and Book.resolve(css_path, u) not in book.files]
                    if bad:
                        missing += bad
                    elif tinycss2.serialize(part).strip():
                        ok += 1
                if missing:
                    out.append((node, missing, ok))
    return out


def _rewrite_font_face(book, css_path, css) -> tuple[str, list[str]]:
    log = []
    nodes = tinycss2.parse_stylesheet(css, skip_whitespace=False, skip_comments=False)
    out = []
    for node in nodes:
        if node.type == 'at-rule' and node.lower_at_keyword == 'font-face' and node.content is not None:
            decls = tinycss2.parse_blocks_contents(node.content, skip_whitespace=True, skip_comments=True)
            new_decls, removed_all = [], False
            for d in decls:
                if d.type != 'declaration':
                    continue
                if d.lower_name == 'src':
                    keep = []
                    for part in _split_commas(d.value):
                        urls = list(_urls(part))
                        if any(not is_external(u) and Book.resolve(css_path, u) not in book.files for u in urls):
                            log.append(f'删除缺失字体引用 {", ".join(urls)}')
                            continue
                        if tinycss2.serialize(part).strip():
                            keep.append(tinycss2.serialize(part).strip())
                    if not keep:
                        removed_all = True
                        break
                    new_decls.append(f'src: {", ".join(keep)};')
                else:
                    imp = ' !important' if d.important else ''
                    new_decls.append(f'{d.name}: {tinycss2.serialize(d.value).strip()}{imp};')
            if removed_all:
                log.append('整条 @font-face 已无可用来源，删除')
                continue
            out.append('@font-face {\n  ' + '\n  '.join(new_decls) + '\n}')
            continue
        out.append(node.serialize())
    return ''.join(out), log


@register
class CssReferences(Rule):
    id, title, order = 'STY-002', '样式表引用完整', 41

    def check(self, book):
        out = []
        for path in css_paths(book):
            css = book.files[path].decode('utf-8', 'replace')
            for node, missing, ok in _missing_font_srcs(book, path, css):
                out.append(self.issue(ERROR, f'@font-face 引用了包内不存在的字体：{", ".join(missing)}', path, AUTO))
            for m in re.finditer(r'url\(\s*[\'"]?([^\'")]+)', css):
                u = m.group(1)
                if not is_external(u) and Book.resolve(path, u) not in book.files and \
                        not any(u in miss for _, miss, _ in _missing_font_srcs(book, path, css)):
                    out.append(self.issue(WARNING, f'引用了不存在的资源：{u}', path, SUGGEST))
        return out

    def fix(self, book, issues):
        log = []
        for path in sorted({i.file for i in issues}):
            new, l2 = _rewrite_font_face(book, path, book.files[path].decode('utf-8', 'replace'))
            book.set_bytes(path, new.encode('utf-8'))
            log += [f'{path}：{x}' for x in l2]
        return log
