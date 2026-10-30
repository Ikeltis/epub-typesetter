"""从规范生成默认主题样式表 src/epub_typesetter/themes/default.css。

主题只能从规范来：改样式请先改 guide/03 §11（默认样式表）或 guide/04 各节的 CSS 块，再运行本脚本。
    python3 scripts/build_theme.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
G03 = (ROOT / 'guide/03_CSS与中文排版规范.md').read_text(encoding='utf-8')
G04 = (ROOT / 'guide/04_排版样式模板库.md').read_text(encoding='utf-8')


def css_block(text: str, start: str, end: str) -> str:
    sec = text[text.index(start):text.index(end, text.index(start))]
    return re.search(r'```css\n(.*?)```', sec, re.S).group(1).strip()


base = css_block(G03, '## 11. 推荐默认样式表', '## 12.')
notes = css_block(G04, '## 4.12 注释', '## 4.13 ')
# 本工具重建时会输出、但不属于某个模板节的增量类
extra = '''/* ===== 10. 本工具重建时用到的增量类 ===== */
p.source{ margin:.2em 0 1em; font-size:.85em; line-height:1.5; text-indent:0; text-align:left; }  /* 图表资料来源 */
p.meta{ margin:.3em 0; text-indent:0; text-align:left; }                                     /* 版权页键值行 */
ul.bullets{ list-style-type:disc; }
img.glyph{ height:1em; width:auto; vertical-align:-.1em; margin:0 .05em; }  /* 行内图片字、生僻字（04 §4.16） */
figcaption p{ margin:.2em 0; text-indent:0; }                                 /* 多段图注（04 4.11.3.5） */
section.cover-page{ margin:0; padding:0; text-align:center; text-indent:0; }
section.cover-page img{ max-width:100%; max-height:100vh; }                  /* 04 §4.14；vh 需实测 */
/* 原书有语义的颜色（批语、强调）映射为 accent；03 默认不写死颜色，这是唯一例外，并给夜间模式配色 */
.accent{ color:#a8382b; }
@media (prefers-color-scheme: dark){ .accent{ color:#e88b7d; } }'''

out = ('/* epub-typesetter 默认主题。由 scripts/build_theme.py 从 guide/03 §11 与 guide/04 生成，请勿手改。 */\n'
       + base + '\n\n' + notes + '\n\n' + extra + '\n')
(ROOT / 'src/epub_typesetter/themes/default.css').write_text(out, encoding='utf-8')
print(f'default.css {len(out)} 字节')

# 按需模板：04 各节 CSS 块里以 /* tpl:名字 */ 开头的片段，重建时只追加用到的（04 附录 B.2 第 2 条）
WANTED = ('poem', 'poem-pagebreak', 'letter', 'script', 'article', 'list', 'figure', 'loi', 'table', 'glossary')
tpl_dir = ROOT / 'src/epub_typesetter/themes'
for old in tpl_dir.glob('tpl-*.css'):
    old.unlink()
n = 0
for block in re.findall(r'```css\n(.*?)```', G04, re.S):
    parts = re.split(r'^/\* tpl:([\w-]+)[^*]*\*/\n', block, flags=re.M)
    for name, css in zip(parts[1::2], parts[2::2]):
        if name in WANTED:
            (tpl_dir / f'tpl-{name}.css').write_text(f'/* tpl:{name}（04） */\n{css.strip()}\n', encoding='utf-8')
            n += 1
print(f'模板 {n} 个')
