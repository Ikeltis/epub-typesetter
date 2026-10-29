"""A11Y：无障碍基础（guide/07 §2.7）。"""
from __future__ import annotations

import re

from ..book import NS
from ..engine import AUTO, ERROR, INFO, LLM, SUGGEST, WARNING, Rule, register
from ..upgrade import _meta, book_language
from ..xhtml import HAN, HEADINGS, X, XML_LANG, body, text_of

FILENAME_ALT = re.compile(r'\.(jpe?g|png|gif|webp|svg)$|^(图片?|插图|image|img\d*|pic\d*|\d+)$', re.I)
LANG_FIX = {'zho': 'zh', 'chi': 'zh', 'zh_cn': 'zh-CN', 'zh_tw': 'zh-TW', 'cn': 'zh', 'chs': 'zh-Hans',
            'cht': 'zh-Hant', 'eng': 'en', 'jpn': 'ja'}
BCP47 = re.compile(r'^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$')


def _caption_for(img):
    """img 所在 figure 的 figcaption 文字。"""
    el = img.getparent()
    while el is not None and el.tag != X + 'figure':
        el = el.getparent()
    if el is None:
        return ''
    cap = el.find(X + 'figcaption')
    return re.sub(r'[ \t\r\n]+', ' ', text_of(cap)).strip()[:120] if cap is not None else ''


@register
class ImageAlt(Rule):
    id, title, order = 'A11Y-001', '图片 alt', 90
    node_fix = True

    def check(self, book):
        out = []
        for path in book.content_docs():
            imgs = list(body(book.tree(path).getroot()).iter(X + 'img'))
            missing = [i for i in imgs if i.get('alt') is None]
            badname = [i for i in imgs if i.get('alt') and FILENAME_ALT.search(i.get('alt').strip())]
            if missing:
                out.append(self.issue(ERROR, f'{len(missing)} 张图片没有 alt 属性', path, AUTO,
                                      hits=[self.hit(i, fix={'op': 'set_attr', 'name': 'alt'}) for i in missing]))
            if badname:
                out.append(self.issue(WARNING, f'{len(badname)} 张图片的 alt 是文件名/无意义词', path, LLM,
                                      hits=[self.hit(i) for i in badname]))
        return out

    def fix(self, book, issues):
        log = []
        for i in issues:
            cap = empty = 0
            keep = i.waived_nodes()
            for img in body(book.tree(i.file).getroot()).iter(X + 'img'):
                if img.get('alt') is None and img not in keep:
                    c = _caption_for(img)
                    img.set('alt', c)
                    cap += bool(c)
                    empty += not c
            book.mark_dirty(i.file)
            log.append(f'{i.file}：补 alt（取自图注 {cap}，暂空 {empty}，待大模型/人工补描述）')
        return log


def _han_ratio(root) -> float:
    text = re.sub(r'\s+', '', ''.join(body(root).itertext()))[:5000]
    if not text:
        return 0.0
    return len(re.findall(f'[{HAN}]', text)) / len(text)


def normalize_lang(v: str) -> str:
    v = v.strip()
    return LANG_FIX.get(v.lower(), v)


@register
class Language(Rule):
    id, title, order = 'A11Y-002', '语言声明', 91

    def check(self, book):
        out = []
        el = book.opf.find('opf:metadata/dc:language', NS)
        if el is None or not (el.text or '').strip():
            return [self.issue(ERROR, 'OPF 缺少 dc:language', book.opf_path, SUGGEST)]
        lang = (el.text or '').strip()
        if normalize_lang(lang) != lang or not BCP47.match(lang):
            out.append(self.issue(WARNING, f'dc:language 不规范：{lang}', book.opf_path, AUTO, kind='opf'))
        book_lang = normalize_lang(lang)
        for path in book.content_docs():
            root = book.tree(path).getroot()
            if not root.get('lang') or not root.get(XML_LANG) or root.get('lang') != root.get(XML_LANG):
                out.append(self.issue(WARNING, '根元素缺 lang/xml:lang 或两者不一致', path, AUTO, kind='doc'))
            elif book_lang.startswith('zh') and not root.get('lang', '').lower().startswith(('zh', 'ja', 'ko', 'lzh')) \
                    and _han_ratio(root) > 0.3:
                # 中文正文被标成 en 等：阅读器会按西文选字体、断行
                out.append(self.issue(WARNING, f'正文是中文，却标为 lang="{root.get("lang")}"', path, AUTO, kind='doc-wrong'))
        return out

    def fix(self, book, issues):
        log = []
        el = book.opf.find('opf:metadata/dc:language', NS)
        if any(i.data.get('kind') == 'opf' for i in issues):
            new = normalize_lang(el.text or '')
            if BCP47.match(new):
                log.append(f'dc:language {el.text} → {new}')
                el.text = new
                book.mark_dirty(book.opf_path)
        lang = normalize_lang(book_language(book))
        n = 0
        for i in issues:
            if i.data.get('kind') not in ('doc', 'doc-wrong'):
                continue
            root = book.tree(i.file).getroot()
            v = lang if i.data['kind'] == 'doc-wrong' else (root.get('lang') or root.get(XML_LANG) or lang)
            v = normalize_lang(v)
            root.set('lang', v)
            root.set(XML_LANG, v)
            book.mark_dirty(i.file)
            n += 1
        if n:
            log.append(f'{n} 个内容文档补 lang/xml:lang')
        return log


A11Y_PROPS = ('schema:accessMode', 'schema:accessModeSufficient', 'schema:accessibilityFeature',
              'schema:accessibilityHazard', 'schema:accessibilitySummary')


@register
class A11yMetadata(Rule):
    id, title, order = 'A11Y-003', '无障碍元数据', 92

    def check(self, book):
        if not book.version.startswith('3'):
            return []
        md = book.opf.find('opf:metadata', NS)
        have = {m.get('property') for m in md.findall('opf:meta', NS)}
        miss = [p for p in A11Y_PROPS if p not in have]
        if miss:
            return [self.issue(WARNING, f'缺少无障碍元数据：{", ".join(miss)}', book.opf_path, AUTO, miss=miss)]
        return []

    def fix(self, book, issues):
        md = book.opf.find('opf:metadata', NS)
        miss = issues[0].data['miss']
        has_img = has_heading = False
        alts_ok = True
        for path in book.content_docs():
            b = body(book.tree(path).getroot())
            for img in b.iter(X + 'img'):
                has_img = True
                if not (img.get('alt') or '').strip():
                    alts_ok = False
            if not has_heading and next(b.iter(*HEADINGS), None) is not None:
                has_heading = True
        values = {
            'schema:accessMode': ['textual'] + (['visual'] if has_img else []),
            'schema:accessModeSufficient': ['textual'] if (not has_img or alts_ok) else ['textual,visual'],
            'schema:accessibilityFeature': (['tableOfContents', 'readingOrder']
                                            + (['structuralNavigation'] if has_heading else [])
                                            + (['alternativeText'] if has_img and alts_ok else [])),
            'schema:accessibilityHazard': ['unknown'],
            'schema:accessibilitySummary': ['本书的无障碍元数据由 epub-typesetter 根据内容自动推断，未经人工评估，'
                                            '不声明符合任何无障碍标准。'],
        }
        log = []
        for p in miss:
            for v in values[p]:
                _meta(md, p, v)
            log.append(f'{p} = {", ".join(values[p])}')
        book.mark_dirty(book.opf_path)
        return log
