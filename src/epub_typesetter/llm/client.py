"""调用 Claude：结构化输出、按内容哈希缓存、用量与费用统计。

- 结构化输出用 messages.parse + Pydantic 模型，返回的就是校验过的对象；
- 同样的（模型、系统提示、输入、输出格式）只问一次，结果存在 {DATA_DIR}/llm-cache/，重复处理同一本书不重复花钱；
- 费用按官方价目估算（走中转时实际计费以中转为准）。
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from pydantic import BaseModel

from .settings import LLMSettings

# 每百万 token 的官方价（输入, 输出）；缓存写入按输入价 1.25 倍、读取按 0.1 倍估算
PRICES = {
    'claude-haiku-5-5': (0.10, 0.50), 'claude-sonnet-5-5': (2.0, 10.0), 'claude-opus-5-5': (4.0, 20.0),
    'claude-sonnet-5': (2.0, 10.0), 'claude-opus-5': (5.0, 25.0), 'claude-fable-5-1': (10.0, 50.0),
    'claude-haiku-4-5': (1.0, 5.0), 'claude-sonnet-4-6': (3.0, 15.0), 'claude-opus-4-8': (5.0, 25.0),
}
FALLBACK_BETA = 'server-side-fallback-2026-07-01'


class LLMError(RuntimeError):
    """给用户看的错误（配置不对、额度、网络）。"""


class ContentBlocked(LLMError):
    """中转或服务商的内容审核拦下了某一条（只影响这一条，不是配置问题）。"""


@dataclass
class Usage:
    calls: int = 0
    cached: int = 0                       # 命中本地缓存、没有真正调用的次数
    refused: int = 0
    blocked: int = 0                      # 被接口方内容审核拦下的条数
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0
    by_model: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def _price(model: str) -> tuple[float, float]:
    for k, v in PRICES.items():
        if model.startswith(k):
            return v
    return PRICES['claude-opus-5-5']


class LLM:
    def __init__(self, settings: LLMSettings, cache_dir: str | Path | None = None):
        if not settings.enabled:
            raise LLMError('大模型辅助已在设置里关闭')
        if not settings.has_credentials:
            raise LLMError('还没有配置大模型的令牌：在「大模型设置」里填写，或设置环境变量 EPUBTS_LLM_API_KEY / EPUBTS_LLM_AUTH_TOKEN')
        self.settings = settings
        kw = {'max_retries': 3, 'timeout': 180.0}
        if settings.base_url:
            kw['base_url'] = settings.base_url
        if settings.api_key:
            kw['api_key'] = settings.api_key
        if settings.auth_token:
            kw['auth_token'] = settings.auth_token
        self.client = anthropic.Anthropic(**kw)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.usage = Usage()
        self._lock = threading.Lock()

    # ---------- 缓存 ----------

    def _key(self, model: str, effort: str, system: str, content, schema: type[BaseModel]) -> str:
        blob = json.dumps([model, effort, system, content, schema.model_json_schema()], ensure_ascii=False,
                          sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_get(self, key: str):
        if self.cache_dir is None:
            return None
        p = self.cache_dir / f'{key}.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None

    def _cache_put(self, key: str, value) -> None:
        if self.cache_dir is not None:
            (self.cache_dir / f'{key}.json').write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    # ---------- 调用 ----------

    def ask(self, tier: str, system: str, content, schema: type[BaseModel], max_tokens: int = 8000,
            use_cache: bool = True):
        """问一次，返回 schema 实例；模型拒答返回 None。content 是字符串或内容块列表（可含图片）。"""
        model, effort = self.settings.model(tier), self.settings.effort(tier)
        key = self._key(model, effort, system, content, schema)
        hit = self._cache_get(key) if use_cache else None
        if hit is not None:
            with self._lock:
                self.usage.cached += 1
            return None if hit.get('refused') else schema.model_validate(hit['parsed'])
        extra = {}
        if self.settings.use_fallbacks and model.startswith(('claude-opus-5', 'claude-fable-5')):
            # 官方接口上拒答时由服务端按类别改派其他模型接手（只给 Opus 5/5.5、Fable 5.1 等开）
            extra = {'extra_headers': {'anthropic-beta': FALLBACK_BETA}, 'extra_body': {'fallbacks': 'default'}}
        try:
            r = self.client.messages.parse(
                model=model, max_tokens=max_tokens, output_config={'effort': effort},
                system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                messages=[{'role': 'user', 'content': content}], output_format=schema, **extra)
        except anthropic.AuthenticationError:
            raise LLMError('令牌无效（401），请检查「大模型设置」') from None
        except anthropic.PermissionDeniedError as e:
            if 'content_policy' in str(e.message) or '审' in str(e.message):
                with self._lock:
                    self.usage.blocked += 1
                raise ContentBlocked('接口方的内容审核拦下了这条请求') from None
            raise LLMError(f'没有权限（403）：{e.message}') from None
        except anthropic.NotFoundError:
            raise LLMError(f'模型 {model} 或接口地址不存在（404），请检查设置') from None
        except anthropic.RateLimitError:
            raise LLMError('请求太频繁或额度用完（429），稍后再试') from None
        except anthropic.BadRequestError as e:
            with self._lock:
                self.usage.failed += 1
            raise LLMError(f'请求被拒绝（400）：{e.message}') from None
        except anthropic.APIStatusError as e:
            raise LLMError(f'接口出错（{e.status_code}）：{e.message}') from None
        except anthropic.APIConnectionError:
            raise LLMError(f'连不上 {self.settings.effective_base_url}，请检查网络或接口地址') from None
        self._account(r, model)
        if r.stop_reason == 'refusal':
            with self._lock:
                self.usage.refused += 1
            self._cache_put(key, {'refused': True})
            return None
        if r.parsed_output is None:
            with self._lock:
                self.usage.failed += 1
            return None
        self._cache_put(key, {'parsed': r.parsed_output.model_dump()})
        return r.parsed_output

    def _account(self, r, model: str) -> None:
        u = r.usage
        pin, pout = _price(model)
        cr = getattr(u, 'cache_read_input_tokens', 0) or 0
        cw = getattr(u, 'cache_creation_input_tokens', 0) or 0
        cost = (u.input_tokens * pin + cw * pin * 1.25 + cr * pin * 0.1 + u.output_tokens * pout) / 1e6
        with self._lock:
            us = self.usage
            us.calls += 1
            us.input_tokens += u.input_tokens
            us.output_tokens += u.output_tokens
            us.cache_read += cr
            us.cache_write += cw
            us.cost += cost
            us.by_model[model] = us.by_model.get(model, 0) + 1

    def ping(self) -> dict:
        """测试连接：用轻量模型问一句，返回模型名与用时。"""
        import time

        class Pong(BaseModel):
            ok: bool

        t = time.time()
        r = self.ask('light', '按要求回答。', '请回答 ok=true。', Pong, max_tokens=1000, use_cache=False)
        return {'ok': bool(r and r.ok), 'model': self.settings.model_light, 'seconds': round(time.time() - t, 1),
                'base_url': self.settings.effective_base_url}
