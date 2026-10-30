"""项目存储：每本上传的书一个目录。

    {DATA_DIR}/{id}/meta.json      状态与基本信息
                   original.epub   上传原件（永不修改）
                   fixed.epub      修复结果
                   audit.json      体检报告
                   fix.json        修复报告
                   waivers.json    按书豁免（guide/07 §7 格式）
                   fixed.renames.json  修复时的改名链（原路径 → 输出路径），豁免据此匹配输出文件
                   board.json      确认板（排版重建时生成）
                   decisions.json  用户在确认板上的决定（排版重建时读取）
                   llm.json        大模型对确认板各项的判断（只供采纳，不直接改书）
    {DATA_DIR}/settings.json       全局设置（大模型地址、令牌、模型；权限 600）
    {DATA_DIR}/llm-cache/          大模型调用结果缓存（按内容哈希）

不使用用户提供的文件名作路径，id 由服务端生成。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field

DATA_DIR = os.environ.get('EPUBTS_DATA', '/data')
ID_RE = re.compile(r'^[0-9a-f]{12}$')
_lock = threading.Lock()


@dataclass
class Meta:
    id: str
    filename: str
    size: int
    created: float
    status: str = 'queued'        # queued / auditing / ready / fixing / thinking / fixed / error
    message: str = ''
    title: str = ''
    author: str = ''
    version: str = ''
    updated: float = field(default_factory=time.time)


def root() -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def path(pid: str, name: str = '') -> str:
    if not ID_RE.match(pid):
        raise KeyError(pid)
    return os.path.join(root(), pid, name) if name else os.path.join(root(), pid)


def create(filename: str, data: bytes) -> Meta:
    pid = secrets.token_hex(6)
    os.makedirs(path(pid))
    with open(path(pid, 'original.epub'), 'wb') as f:
        f.write(data)
    clean_name = re.sub(r'[\x00-\x1f/\\]', '_', os.path.basename(filename or 'book.epub'))[:200]
    meta = Meta(pid, clean_name, len(data), time.time())
    save_meta(meta)
    return meta


def save_meta(meta: Meta) -> None:
    meta.updated = time.time()
    with _lock:
        tmp = path(meta.id, 'meta.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(asdict(meta), f, ensure_ascii=False)
        os.replace(tmp, path(meta.id, 'meta.json'))


def load_meta(pid: str) -> Meta:
    with open(path(pid, 'meta.json'), encoding='utf-8') as f:
        return Meta(**json.load(f))


def update(pid: str, **kw) -> Meta:
    m = load_meta(pid)
    for k, v in kw.items():
        setattr(m, k, v)
    save_meta(m)
    return m


def list_all() -> list[Meta]:
    out = []
    for name in os.listdir(root()):
        if ID_RE.match(name) and os.path.exists(path(name, 'meta.json')):
            try:
                out.append(load_meta(name))
            except (OSError, ValueError, TypeError):
                continue
    return sorted(out, key=lambda m: m.created, reverse=True)


def write_json(pid: str, name: str, obj) -> None:
    tmp = path(pid, name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path(pid, name))


def read_json(pid: str, name: str):
    p = path(pid, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def delete(pid: str) -> None:
    shutil.rmtree(path(pid), ignore_errors=True)
