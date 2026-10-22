"""调用 EPUBCheck（Java）并把结果转成统一结构。

EPUBCheck 不可用时返回 None，调用方应退化为只用自研规则（guide/07 §1）。
注意：运行环境必须是 UTF-8 locale，否则 Java 打不开中文文件名且不报错。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass


@dataclass
class Message:
    id: str
    severity: str        # FATAL / ERROR / WARNING / USAGE / INFO
    message: str
    locations: list[str]


def available() -> bool:
    return shutil.which('epubcheck') is not None


def run(epub_path: str, timeout: int = 600) -> list[Message] | None:
    if not available():
        return None
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 'out.json')
        subprocess.run(['epubcheck', epub_path, '--json', out, '-q'],
                       capture_output=True, timeout=timeout)
        if not os.path.exists(out):
            return None
        data = json.load(open(out, encoding='utf-8'))
    msgs = []
    for m in data.get('messages', []):
        locs = [f"{l.get('path')}:{l.get('line')}" for l in m.get('locations', [])]
        msgs.append(Message(m['ID'], m['severity'], m['message'], locs))
    return msgs


def run_bytes(data: bytes, timeout: int = 600) -> list[Message] | None:
    with tempfile.NamedTemporaryFile(suffix='.epub', delete=False) as f:
        f.write(data)
        path = f.name
    try:
        return run(path, timeout)
    finally:
        os.unlink(path)


def summarize(msgs: list[Message] | None) -> dict:
    if msgs is None:
        return {'available': False}
    sev = Counter()
    ids = Counter()
    for m in msgs:
        n = max(1, len(m.locations))
        sev[m.severity] += n
        ids[m.id] += n
    return {'available': True, 'by_severity': dict(sev), 'by_id': dict(ids.most_common())}


def blocking(msgs: list[Message] | None) -> int:
    """FATAL+ERROR 的总处数（验收口径：应为 0）。"""
    if not msgs:
        return 0
    return sum(max(1, len(m.locations)) for m in msgs if m.severity in ('FATAL', 'ERROR'))
