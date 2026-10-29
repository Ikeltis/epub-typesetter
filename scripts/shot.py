"""把 EPUB 里某个文档渲染成 PNG（开发容器内运行，用 chromium + Noto CJK）。

用法: python scripts/shot.py book.epub 文档名片段 out.png [宽,高]
"""
import os
import subprocess
import sys
import tempfile
import zipfile

epub, part, out = sys.argv[1:4]
size = sys.argv[4] if len(sys.argv) > 4 else '560,1100'
with tempfile.TemporaryDirectory() as td:
    zipfile.ZipFile(epub).extractall(td)
    doc = next(os.path.join(dp, f) for dp, _, fs in os.walk(td) for f in sorted(fs)
               if part in f and f.endswith(('.xhtml', '.html')))
    env = dict(os.environ, HOME=td)
    subprocess.run(['chromium', '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
                    f'--user-data-dir={td}/prof', f'--window-size={size}', '--virtual-time-budget=4000',
                    f'--screenshot={os.path.abspath(out)}', 'file://' + doc],
                   capture_output=True, env=env, timeout=90)
print(out, os.path.exists(out))
