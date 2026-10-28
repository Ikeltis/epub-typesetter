"""网页后端（M1）：上传 → 体检 → 自动修复 → 下载。

    uvicorn epub_typesetter.web.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
from dataclasses import asdict
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, engine, epubcheck
from . import jobs, store

MAX_UPLOAD = int(os.environ.get('EPUBTS_MAX_UPLOAD_MB', '300')) * 1024 * 1024
CATEGORIES = {'STR': '结构', 'SEM': '语义', 'STY': '样式', 'TYP': '排版', 'TXT': '文本', 'RES': '资源',
              'A11Y': '无障碍'}

app = FastAPI(title='epub-typesetter', version=__version__)


def _meta_or_404(pid: str) -> store.Meta:
    try:
        return store.load_meta(pid)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, '找不到这本书') from None


@app.get('/api/health')
def health():
    return {'ok': True, 'version': __version__, 'epubcheck': epubcheck.available()}


@app.get('/api/rules')
def rules():
    return [{'id': r.id, 'title': r.title, 'category': r.id.split('-')[0],
             'category_name': CATEGORIES.get(r.id.split('-')[0], '')} for r in engine.all_rules()]


@app.get('/api/books')
def list_books():
    return [asdict(m) for m in store.list_all()]


@app.post('/api/books', status_code=201)
async def upload(file: UploadFile):
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data += chunk
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, f'文件超过 {MAX_UPLOAD // 1024 // 1024} MB')
    if not jobs.is_epub_like(bytes(data[:4])):
        raise HTTPException(400, '这不是 EPUB 文件（EPUB 是 ZIP 格式）')
    meta = store.create(file.filename or 'book.epub', bytes(data))
    jobs.submit(jobs.audit, meta.id)
    return asdict(meta)


@app.get('/api/books/{pid}')
def get_book(pid: str):
    meta = _meta_or_404(pid)
    return {'meta': asdict(meta), 'audit': store.read_json(pid, 'audit.json'),
            'fix': store.read_json(pid, 'fix.json')}


@app.post('/api/books/{pid}/fix', status_code=202)
def run_fix(pid: str, mode: str = 'basic'):
    meta = _meta_or_404(pid)
    if mode not in ('basic', 'rebuild'):
        raise HTTPException(400, 'mode 只能是 basic 或 rebuild')
    if meta.status in ('queued', 'auditing', 'fixing'):
        raise HTTPException(409, '这本书正在处理中')
    store.update(pid, status='fixing')
    jobs.submit(jobs.fix, pid, mode)
    return {'ok': True}


@app.get('/api/books/{pid}/download')
def download(pid: str, which: str = 'fixed'):
    meta = _meta_or_404(pid)
    if which not in ('fixed', 'original'):
        raise HTTPException(400, 'which 只能是 fixed 或 original')
    p = store.path(pid, f'{which}.epub')
    if not os.path.exists(p):
        raise HTTPException(404, '还没有修复结果')
    stem = meta.filename[:-5] if meta.filename.lower().endswith('.epub') else meta.filename
    name = f'{stem}.epub' if which == 'original' else f'{stem}（优化）.epub'
    return FileResponse(p, media_type='application/epub+zip',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})


@app.delete('/api/books/{pid}', status_code=204)
def delete_book(pid: str):
    meta = _meta_or_404(pid)
    if meta.status in ('auditing', 'fixing'):
        raise HTTPException(409, '这本书正在处理中')
    store.delete(pid)


# 构建好的前端（Vite 产物）。开发时前端由 Vite dev server 提供，这里可以不存在。
STATIC_DIR = os.environ.get('EPUBTS_STATIC', os.path.join(os.path.dirname(__file__), 'static'))
if os.path.isdir(STATIC_DIR):
    app.mount('/', StaticFiles(directory=STATIC_DIR, html=True), name='static')
