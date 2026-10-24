"""「版面没被破坏」校验：用无头 chromium 渲染修复前后的内容文档，比较版面指标。

textcheck 只保证字没增删；这里兜住「字都在、但版面坏了」的情况
（例：把 <p width="0pt"> 转成 CSS width:0 → 段落被压成一条竖线）。

指标（视口宽 600px）：
- 页面总高度：正文被挤窄会让高度暴涨，内容被隐藏会让高度骤减；
- 窄块数：有文字但宽度 < 40px 的块；
- 隐形块数：有文字但宽或高为 0 的块。
只用于开发验收，不在交付镜像里（需要 chromium）。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field

from .book import Book

# 注入的脚本里不能出现 < 和 &：同一段代码要同时能放进 XHTML（按 XML 解析）和 HTML
METRIC_JS = """
(function () {
  var blocks = document.querySelectorAll('p,h1,h2,h3,h4,h5,h6,li,blockquote,td,th,figcaption,dd,dt,pre');
  var n = 0, narrow = 0, hidden = 0;
  for (var i = 0; i !== blocks.length; i++) {
    var b = blocks[i];
    var t = (b.textContent || '').replace(/\\s+/g, '');
    if (t.length === 0) { continue; }
    n++;
    var r = b.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) { hidden++; continue; }
    if (40 > r.width) { if (t.length >= 4) { narrow++; } }
  }
  var m = {height: document.documentElement.scrollHeight, blocks: n, narrow: narrow, hidden: hidden};
  document.documentElement.setAttribute('data-layout-metrics', JSON.stringify(m));
})();
"""
SCRIPT_TAG = '<script>' + METRIC_JS + '</script>'
METRICS_RE = re.compile(r'data-layout-metrics="([^"]*)"')


def available() -> bool:
    return shutil.which('chromium') is not None


@dataclass
class DocMetrics:
    height: int
    blocks: int
    narrow: int
    hidden: int


@dataclass
class LayoutDiff:
    ok: bool
    checked: int
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return f'{self.checked} 个文档版面正常'
        return f'版面异常 {len(self.problems)} 处：' + '；'.join(self.problems[:3])


def _render(html_path: str, profile_dir: str, timeout: int = 60) -> DocMetrics | None:
    cmd = ['chromium', '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
           f'--user-data-dir={profile_dir}',
           '--window-size=600,900', '--virtual-time-budget=2000', '--allow-file-access-from-files',
           '--dump-dom', 'file://' + html_path]
    try:
        # chromium 的崩溃上报组件需要可写的 HOME，否则直接崩溃（开发容器里的用户没有家目录）
        env = dict(os.environ, HOME=os.path.dirname(profile_dir))
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True, env=env).stdout
    except subprocess.TimeoutExpired:
        return None
    m = METRICS_RE.search(out)
    if not m:
        return None
    d = json.loads(m.group(1).replace('&quot;', '"'))
    return DocMetrics(d['height'], d['blocks'], d['narrow'], d['hidden'])


def _inject(data: bytes) -> bytes:
    s = data.decode('utf-8', 'replace')
    idx = s.lower().rfind('</body>')
    if idx < 0:
        return (s + SCRIPT_TAG).encode('utf-8')
    return (s[:idx] + SCRIPT_TAG + s[idx:]).encode('utf-8')


def measure(epub: bytes, docs: list[str]) -> dict[str, DocMetrics | None]:
    """docs：要测的内容文档 zip 内路径。"""
    out: dict[str, DocMetrics | None] = {}
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(io.BytesIO(epub)) as z:
            z.extractall(td)
        for d in docs:
            src = os.path.join(td, d)
            if not os.path.exists(src):
                out[d] = None
                continue
            head, tail = os.path.split(src)
            probe = os.path.join(head, '__layoutcheck__' + tail)
            with open(src, 'rb') as f:
                data = f.read()
            with open(probe, 'wb') as f:
                f.write(_inject(data))
            out[d] = _render(probe, os.path.join(td, '__chromium_profile__'))
    return out


def _pick_docs(book: Book, limit: int) -> list[str]:
    docs = [it.path for it in book.spine_items()
            if it.media_type == 'application/xhtml+xml' and it.path in book.files]
    # 优先测正文量大的文档
    docs.sort(key=lambda p: len(book.files[p]), reverse=True)
    return docs[:limit]


def compare_layout(before: bytes, after: bytes, limit: int = 12) -> LayoutDiff:
    b0 = Book.load(before)
    docs = _pick_docs(b0, limit)
    m0, m1 = measure(before, docs), measure(after, docs)
    problems = []
    checked = 0
    for d in docs:
        x, y = m0.get(d), m1.get(d)
        if x is None or y is None:
            continue
        checked += 1
        name = d.rsplit('/', 1)[-1]
        if x.height > 300 and not (0.6 <= y.height / x.height <= 1.5):
            problems.append(f'{name} 页面高度 {x.height}→{y.height}px')
        tol = max(3, x.blocks // 10)
        if y.narrow > x.narrow + tol:
            problems.append(f'{name} 被挤窄的文字块 {x.narrow}→{y.narrow}')
        if y.hidden > x.hidden + tol:
            problems.append(f'{name} 看不见的文字块 {x.hidden}→{y.hidden}')
    return LayoutDiff(not problems, checked, problems)
