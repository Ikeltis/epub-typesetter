"""大模型配置。仓库是公开的，地址和令牌一律不写进代码，从下面三处读（前面的优先）：

1. 网页「大模型设置」保存的 {DATA_DIR}/settings.json（data/ 不进仓库）；
2. 环境变量 EPUBTS_LLM_*（部署时写在 .env，见 .env.example；.env 不进仓库）；
3. Anthropic SDK 的标准环境变量 ANTHROPIC_BASE_URL、ANTHROPIC_API_KEY、ANTHROPIC_AUTH_TOKEN。

两档模型：light 做大批量的简单判断（逐组、逐条、看图写描述），heavy 做需要通盘考虑的判断（标题层级、注释配对）。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

OFFICIAL_HOSTS = ('api.anthropic.com',)


@dataclass
class LLMSettings:
    enabled: bool = True
    base_url: str = ''                 # 空 = 官方 https://api.anthropic.com（或 ANTHROPIC_BASE_URL）
    api_key: str = ''                  # 走 x-api-key 头（官方密钥）
    auth_token: str = ''               # 走 Authorization: Bearer 头（部分中转用这种）
    model_light: str = 'claude-haiku-5-5'
    model_heavy: str = 'claude-opus-5-5'
    effort_light: str = 'low'
    effort_heavy: str = 'medium'
    fallbacks: str = 'auto'            # 拒答时服务端改由其他模型接手：auto=只在官方接口上开（中转多半不支持）、on、off
    max_workers: int = 4

    # ---------- 读写 ----------

    @classmethod
    def load(cls, data_dir: str | None = None) -> 'LLMSettings':
        s = cls()
        env = {f.name: os.environ.get(f'EPUBTS_LLM_{f.name.upper()}') for f in fields(cls)}
        for f in fields(cls):
            v = env[f.name]
            if v not in (None, ''):
                setattr(s, f.name, _coerce(f.type, v))
        if data_dir:
            p = Path(data_dir) / 'settings.json'
            if p.exists():
                saved = json.loads(p.read_text(encoding='utf-8')).get('llm', {})
                for f in fields(cls):
                    if f.name in saved and saved[f.name] not in (None, ''):
                        setattr(s, f.name, _coerce(f.type, saved[f.name]))
        return s

    def save(self, data_dir: str, updates: dict) -> 'LLMSettings':
        """只保存网页上改过的项。令牌字段传空串表示「不改」，传 None 表示清除网页上保存的值。"""
        p = Path(data_dir) / 'settings.json'
        doc = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        saved = doc.get('llm', {})
        names = {f.name: f for f in fields(self)}
        for k, v in updates.items():
            if k not in names:
                continue
            if k in ('api_key', 'auth_token'):
                if v is None:
                    saved.pop(k, None)
                elif v:
                    saved[k] = str(v).strip()
                continue
            saved[k] = _coerce(names[k].type, v)
        doc['llm'] = saved
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        return LLMSettings.load(data_dir)

    # ---------- 推导 ----------

    @property
    def effective_base_url(self) -> str:
        return self.base_url or os.environ.get('ANTHROPIC_BASE_URL', '') or 'https://api.anthropic.com'

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key or self.auth_token or os.environ.get('ANTHROPIC_API_KEY')
                    or os.environ.get('ANTHROPIC_AUTH_TOKEN'))

    @property
    def use_fallbacks(self) -> bool:
        if self.fallbacks == 'on':
            return True
        if self.fallbacks == 'off':
            return False
        return any(h in self.effective_base_url for h in OFFICIAL_HOSTS)

    def model(self, tier: str) -> str:
        return self.model_heavy if tier == 'heavy' else self.model_light

    def effort(self, tier: str) -> str:
        return self.effort_heavy if tier == 'heavy' else self.effort_light

    def public(self) -> dict:
        """给网页看的：令牌只显示末 4 位。"""
        d = asdict(self)
        for k in ('api_key', 'auth_token'):
            d[k] = _mask(d[k])
        d['effective_base_url'] = self.effective_base_url
        d['has_credentials'] = self.has_credentials
        d['credential_source'] = ('网页设置或 EPUBTS_LLM_*' if (self.api_key or self.auth_token)
                                  else 'ANTHROPIC_* 环境变量' if self.has_credentials else '未配置')
        return d


def _mask(v: str) -> str:
    return f'…{v[-4:]}' if v else ''


def _coerce(tp, v):
    tp = str(tp)
    if 'bool' in tp:
        return v if isinstance(v, bool) else str(v).lower() in ('1', 'true', 'yes', 'on')
    if 'int' in tp:
        return int(v)
    return str(v).strip()
