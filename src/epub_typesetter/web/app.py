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
from pydantic import BaseModel

from .. import __version__, board, engine, epubcheck
from ..llm.client import LLM, LLMError
from ..llm.settings import LLMSettings
from ..waivers import WaiverFileError, WaiverSet
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
    """全部规范规则（含尚未实现检测的），供界面显示标题、提示和规范条目。"""
    implemented = {r.id for r in engine.all_rules()}
    return [{'id': rid, 'title': m['title'], 'description': m['description'], 'hint': m['hint'],
             'spec': m['spec'], 'severity': m['severity'], 'fix_level': m['fix_level'],
             'priority': m['priority'], 'implemented': rid in implemented,
             'category': rid.split('-')[0], 'category_name': CATEGORIES.get(rid.split('-')[0], '')}
            for rid, m in engine.rules_meta()['rules'].items()]


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
    audit = store.read_json(pid, 'audit.json')
    if audit and 'summary' not in audit['issues'] and meta.status not in jobs.BUSY:
        jobs.rescore(pid)                  # 旧版报告格式：按 guide/07 §6 重算一次
    return {'meta': asdict(meta), 'audit': store.read_json(pid, 'audit.json'),
            'fix': store.read_json(pid, 'fix.json'), 'versions': store.versions(pid), 'summary': jobs.summary(pid)}


@app.post('/api/books/{pid}/fix', status_code=202)
def run_fix(pid: str, mode: str = 'basic'):
    meta = _meta_or_404(pid)
    if mode not in ('basic', 'rebuild'):
        raise HTTPException(400, 'mode 只能是 basic 或 rebuild')
    if meta.status in jobs.BUSY:
        raise HTTPException(409, '这本书正在处理中')
    store.update(pid, status='fixing')
    jobs.submit(jobs.fix, pid, mode)
    return {'ok': True}


class WaiverIn(BaseModel):
    rule: str
    reason: str
    file: str | None = None
    where: dict | None = None


def _idle_or_409(pid: str) -> store.Meta:
    meta = _meta_or_404(pid)
    if meta.status in jobs.BUSY:
        raise HTTPException(409, '这本书正在处理中')
    return meta


def _load_waivers_or_409(pid: str) -> WaiverSet:
    try:
        return WaiverSet.load(store.path(pid, 'waivers.json'))
    except WaiverFileError as e:
        raise HTTPException(409, f'豁免文件格式有误，请先修正：{e}') from None


@app.get('/api/books/{pid}/waivers')
def get_waivers(pid: str):
    _meta_or_404(pid)
    ws = jobs.load_waivers(pid)
    return {**ws.to_dict(), 'problems': [{'severity': s, 'message': m} for s, m, _ in ws.problems]}


@app.post('/api/books/{pid}/waivers', status_code=201)
def add_waiver(pid: str, body: WaiverIn):
    """新增一条豁免（理由必填），随即重算问题报告。"""
    _idle_or_409(pid)
    if not body.reason.strip():
        raise HTTPException(400, '请填写豁免理由')
    ws = _load_waivers_or_409(pid)
    try:
        w = ws.add(body.rule, body.reason, body.file, body.where)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    ws.save(store.path(pid, 'waivers.json'))
    jobs.rescore(pid)
    return w.to_json()


@app.delete('/api/books/{pid}/waivers/{wid}', status_code=204)
def delete_waiver(pid: str, wid: str):
    _idle_or_409(pid)
    ws = _load_waivers_or_409(pid)
    if not ws.remove(wid):
        raise HTTPException(404, '找不到这条豁免')
    ws.save(store.path(pid, 'waivers.json'))
    jobs.rescore(pid)


@app.get('/api/books/{pid}/board')
def get_board(pid: str):
    """确认板：上次排版重建时识别出的段落样式簇、结构、建议，以及用户已保存的决定和大模型的判断。"""
    _meta_or_404(pid)
    data = store.read_json(pid, 'board.json')
    if data is None:
        raise HTTPException(404, '还没有确认板，请先做一次排版重建')
    llm = store.read_json(pid, 'llm.json') or {}
    for c in data['clusters']:
        c['llm'] = (llm.get('clusters') or {}).get(c['key'])
    for k in data['structures']:
        for it in k['items']:
            it['llm'] = (llm.get('items') or {}).get(it['key'])
    for sg in data['suggestions']:
        sg['llm'] = (llm.get('items') or {}).get(sg.get('key'))
    for h in data.get('heads', []):
        h['llm'] = (llm.get('heads') or {}).get(h['key'])
    data['alts'] = [{'key': k, **v} for k, v in (llm.get('alts') or {}).items()]
    data['llm'] = {'usage': llm.get('usage'), 'errors': llm.get('errors', []), 'models': llm.get('models'),
                   'base_url': llm.get('base_url')} if llm else None
    return {**data, 'decisions': board.load(store.path(pid, 'decisions.json'))}


@app.get('/api/books/{pid}/asset')
def get_asset(pid: str, path: str):
    """书里的一张图片（确认板上的缩略图）。只读包内已有的图片文件。"""
    import mimetypes
    import zipfile
    from fastapi.responses import Response
    _meta_or_404(pid)
    if not path.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg')):
        raise HTTPException(400, '只能取图片')
    for name in ('fixed.epub', 'original.epub'):
        f = store.path(pid, name)
        if os.path.exists(f):
            with zipfile.ZipFile(f) as z:
                if path in z.namelist():
                    return Response(z.read(path), media_type=mimetypes.guess_type(path)[0] or 'application/octet-stream',
                                    headers={'Cache-Control': 'private, max-age=3600'})
    raise HTTPException(404, '找不到这张图')


@app.post('/api/books/{pid}/llm', status_code=202)
def run_llm(pid: str, body: dict):
    """大模型分析（后台）。body: {"tasks": ["clusters", "structures"]}。"""
    meta = _idle_or_409(pid)
    if store.read_json(pid, 'board.json') is None:
        raise HTTPException(409, '请先做一次排版重建，生成确认板')
    wanted = [t for t in body.get('tasks') or [] if t in jobs.LLM_TASKS]
    if not wanted:
        raise HTTPException(400, '至少选一项分析任务')
    s = LLMSettings.load(store.root())
    if not s.enabled or not s.has_credentials:
        raise HTTPException(400, '大模型未启用或没有配置令牌，请先到「大模型设置」')
    store.update(pid, status='thinking', message='大模型分析：排队中')
    jobs.submit(jobs.llm, pid, wanted, meta.status)
    return {'ok': True}


# ---------- 大模型设置（全局） ----------

@app.get('/api/settings/llm')
def get_llm_settings():
    return LLMSettings.load(store.root()).public()


@app.put('/api/settings/llm')
def put_llm_settings(body: dict):
    return LLMSettings.load(store.root()).save(store.root(), body).public()


@app.post('/api/settings/llm/test')
def test_llm_settings():
    try:
        return LLM(LLMSettings.load(store.root())).ping()
    except LLMError as e:
        raise HTTPException(400, str(e)) from None


@app.put('/api/books/{pid}/decisions')
def put_decisions(pid: str, body: dict):
    """保存确认板上的决定；下次排版重建时生效（前端保存后会直接触发重建）。"""
    _idle_or_409(pid)
    d = board.clean(body)
    store.write_json(pid, 'decisions.json', d)
    f = store.read_json(pid, 'fix.json')
    if f is not None:
        f['decisions_changed'] = True
        store.write_json(pid, 'fix.json', f)
    return d


@app.get('/api/books/{pid}/download')
def download(pid: str, which: str = 'fixed'):
    """which：original 原件、fixed 最近一次生成、vN 第 N 版。"""
    import re as _re
    meta = _meta_or_404(pid)
    if which in ('fixed', 'original'):
        p = store.path(pid, f'{which}.epub')
    elif _re.fullmatch(r'v\d{1,6}', which):
        p = os.path.join(store.path(pid, 'versions'), f'{which}.epub')
    else:
        raise HTTPException(400, 'which 只能是 original、fixed 或 vN')
    if not os.path.exists(p):
        raise HTTPException(404, '没有这份文件（旧版本只保留最近 5 份）')
    stem = meta.filename[:-5] if meta.filename.lower().endswith('.epub') else meta.filename
    name = f'{stem}.epub' if which == 'original' else f'{stem}（优化{"" if which == "fixed" else "·" + which}）.epub'
    return FileResponse(p, media_type='application/epub+zip',
                        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})


@app.delete('/api/books/{pid}', status_code=204)
def delete_book(pid: str):
    meta = _meta_or_404(pid)
    if meta.status in jobs.BUSY:
        raise HTTPException(409, '这本书正在处理中')
    store.delete(pid)


# 构建好的前端（Vite 产物）。开发时前端由 Vite dev server 提供，这里可以不存在。
STATIC_DIR = os.environ.get('EPUBTS_STATIC', os.path.join(os.path.dirname(__file__), 'static'))
if os.path.isdir(STATIC_DIR):
    app.mount('/', StaticFiles(directory=STATIC_DIR, html=True), name='static')
