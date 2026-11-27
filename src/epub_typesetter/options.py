"""排版重建的选项（按书保存）：哪些识别要做、主题的几处外观。

默认值与不设选项时完全相同；只有改过的项才影响结果，并写进版本说明。

    features  识别开关：关掉的那类内容按普通段落原样保留（文字不变）
    style     主题外观：在统一主题之后追加几条覆盖样式；没列出的照规范 03、04
"""
from __future__ import annotations

FEATURES = {           # 键: (说明, 关闭时版本说明里的写法, 对应的成组结构类别)
    'notes':    ('注释集中到书末（注号与注文配对，带回链）', '注释留在原处', ()),
    'toc_page': ('删除书内目录页（由阅读器的目录菜单代替）', '保留书内目录页', ()),
    'ads':      ('删除广告页', '保留广告页', ('junk',)),
    'poem':     ('识别诗歌', '不识别诗歌', ('poem',)),
    'letter':   ('识别书信', '不识别书信', ('letter',)),
    'lists':    ('识别列表、序号项、条文', '不识别列表', ('ol', 'item', 'article')),
    'loi':      ('插图目录、表格目录改成可跳转的目录页', '不转插图目录', ('loi', 'lot')),
}

STYLE = {              # 键: (说明, {取值: 显示名}, 默认值)
    'heading_font':  ('标题字体', {'sans': '黑体', 'serif': '宋体', 'kai': '楷体', 'inherit': '同正文'}, 'sans'),
    'heading_align': ('标题对齐', {'left': '居左', 'center': '居中'}, 'left'),
    'chapter_space': ('章标题上方留白', {'large': '大（约四分之一页）', 'small': '小（约三行）'}, 'large'),
    'body_align':    ('正文对齐', {'justify': '两端对齐', 'left': '左对齐'}, 'justify'),
    'paragraph':     ('段落', {'indent': '首行缩进两字', 'spaced': '不缩进，段间空开'}, 'indent'),
    'line_height':   ('行高', {'1.4': '1.4', '1.6': '1.6', '1.8': '1.8', '2.0': '2.0'}, '1.6'),
    'quote_font':    ('引文字体', {'kai': '楷体', 'inherit': '同正文'}, 'kai'),
}

FONTS = {
    'sans': '"Source Han Sans SC","Noto Sans CJK SC","PingFang SC","Microsoft YaHei","SimHei",sans-serif',
    'serif': '"Source Han Serif SC","Noto Serif CJK SC","Songti SC","STSong","SimSun",serif',
    'kai': '"Kaiti SC","STKaiti","KaiTi",serif',
    'inherit': 'inherit',
}
HEADINGS = 'h1, h2, h3, h4, h5, h6, .part-title, .chapter-title, .section-title, .subsection-title'


def defaults() -> dict:
    return {'features': {k: True for k in FEATURES}, 'style': {k: v[2] for k, v in STYLE.items()}}


def clean(d: dict | None) -> dict:
    """只收认识的键和合法取值，其余回到默认。"""
    out = defaults()
    d = d or {}
    for k, v in (d.get('features') or {}).items():
        if k in FEATURES and isinstance(v, bool):
            out['features'][k] = v
    for k, v in (d.get('style') or {}).items():
        if k in STYLE and str(v) in STYLE[k][1]:
            out['style'][k] = str(v)
    return out


def changed(opts: dict) -> list[str]:
    """和默认不同的项，用于版本说明：['不集中注释', '标题居中', …]。"""
    opts = clean(opts)
    out = [FEATURES[k][1] for k, on in opts['features'].items() if not on]
    out += [f'{STYLE[k][0]}{STYLE[k][1][v]}' for k, v in opts['style'].items() if v != STYLE[k][2]]
    return out


def kinds_off(opts: dict) -> dict[str, bool]:
    """关掉的识别对应的成组结构类别：并进确认板决定的 kinds（逐条决定仍优先）。"""
    out = {}
    for k, on in clean(opts)['features'].items():
        if not on:
            for kind in FEATURES[k][2]:
                out[kind] = False
    return out


def style_css(opts: dict) -> str:
    """追加在主题末尾的覆盖样式（选择器与主题里相同，靠顺序覆盖）。默认值时为空。"""
    s = clean(opts)['style']
    rules = []
    if s['heading_font'] != 'sans':
        rules.append(f'{HEADINGS}{{ font-family:{FONTS[s["heading_font"]]}; }}')
    if s['heading_align'] == 'center':
        rules.append(f'{HEADINGS}{{ text-align:center; }}')
    if s['chapter_space'] == 'small':
        rules.append('.chapter-title{ margin-top:3em; }\n.part-title{ margin-top:15%; }')
    if s['body_align'] == 'left':
        rules.append('body{ text-align:left; }')
    if s['paragraph'] == 'spaced':
        rules.append('p{ text-indent:0; margin:.6em 0; }')
    if s['line_height'] != '1.6':
        rules.append(f'body{{ line-height:{s["line_height"]}; }}')
    if s['quote_font'] == 'inherit':
        rules.append('blockquote p{ font-family:inherit; }')
    if not rules:
        return ''
    return '\n/* ===== 按书选项（网页「生成」里的自定义外观）===== */\n' + '\n'.join(rules) + '\n'
