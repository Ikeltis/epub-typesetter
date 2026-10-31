"""大模型辅助（M3）：配置优先级、缓存与计费、任务组装、网页接口。不联网：用假的 messages.parse。"""
import json
import time
from types import SimpleNamespace

import pytest

from epub_typesetter.book import Book
from epub_typesetter.llm import tasks
from epub_typesetter.llm.client import LLM, LLMError
from epub_typesetter.llm.settings import LLMSettings
from epub_typesetter.pipeline import optimize

from conftest import XHTML11, make_epub


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL'):
        monkeypatch.delenv(k, raising=False)
    for k in list(__import__('os').environ):
        if k.startswith('EPUBTS_LLM_'):
            monkeypatch.delenv(k)


class FakeMessages:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def parse(self, **kw):
        self.calls.append(kw)
        schema = kw['output_format']
        return SimpleNamespace(stop_reason='end_turn', parsed_output=schema.model_validate(self.answer(kw)),
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=100,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))


def fake_llm(tmp_path, answer):
    llm = LLM(LLMSettings(auth_token='t'), tmp_path / 'cache')
    llm.client = SimpleNamespace(messages=FakeMessages(answer))
    return llm


def test_settings_precedence_and_mask(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'sdk-token')
    s = LLMSettings.load(str(tmp_path))
    assert s.has_credentials and s.public()['credential_source'] == 'ANTHROPIC_* 环境变量'
    monkeypatch.setenv('EPUBTS_LLM_MODEL_LIGHT', 'claude-sonnet-5-5')
    monkeypatch.setenv('EPUBTS_LLM_BASE_URL', 'https://relay.example.com')
    assert LLMSettings.load(str(tmp_path)).model_light == 'claude-sonnet-5-5'
    s = LLMSettings.load(str(tmp_path)).save(str(tmp_path), {'model_light': 'claude-haiku-5-5', 'api_key': 'sk-secret-1234',
                                                               'bogus': 1})
    assert s.model_light == 'claude-haiku-5-5' and s.base_url == 'https://relay.example.com'   # 网页设置优先，没改的沿用环境变量
    pub = s.public()
    assert pub['api_key'] == '…1234' and 'secret' not in json.dumps(pub)
    assert (tmp_path / 'settings.json').stat().st_mode & 0o077 == 0                       # 只有属主可读
    s = s.save(str(tmp_path), {'api_key': ''})                                           # 空串 = 不改
    assert s.api_key == 'sk-secret-1234'
    s = s.save(str(tmp_path), {'api_key': None})                                         # None = 清除
    assert s.api_key == ''
    assert not s.use_fallbacks                                                           # 中转上默认不开拒答兜底
    assert LLMSettings(base_url='').use_fallbacks


def test_no_credentials_is_friendly_error(tmp_path):
    with pytest.raises(LLMError, match='令牌'):
        LLM(LLMSettings.load(str(tmp_path)))


def test_ask_caches_and_accounts(tmp_path):
    from epub_typesetter.llm.tasks import StructVerdict
    llm = fake_llm(tmp_path, lambda kw: {'accept': True, 'confidence': .9, 'reason': '是诗'})
    a = llm.ask('light', '系统', '床前明月光', StructVerdict)
    b = llm.ask('light', '系统', '床前明月光', StructVerdict)
    assert a.accept and b.accept
    assert len(llm.client.messages.calls) == 1 and llm.usage.cached == 1                 # 第二次走缓存
    call = llm.client.messages.calls[0]
    assert call['model'] == 'claude-haiku-5-5' and call['output_config'] == {'effort': 'low'}
    assert call['system'][0]['cache_control'] == {'type': 'ephemeral'}
    assert 'extra_body' not in call
    assert llm.usage.cost == pytest.approx((1000 * .10 + 100 * .50) / 1e6)


def _book():
    c1 = ('<h1>第一章</h1>' + '<p>正文叙述，内容内容内容内容内容。</p>' * 4 +
          '<p class="yin">引文一，内容。</p><p class="yin">引文二，内容。</p><p class="yin">引文三，内容。</p>'
          '<p>他念道：</p><p>世人都晓神仙好，惟有功名忘不了！</p><p>古今将相在何方？荒冢一堆草没了。</p>')
    return Book.load(make_epub({'OEBPS/Text/c1.xhtml': XHTML11.format(title='一', body=c1)}))


def test_tasks_run_builds_board_keys(tmp_path):
    rep = optimize(_book())
    llm = fake_llm(tmp_path, lambda kw: {'role': 'quote', 'confidence': .9, 'reason': '引文'} if 'role' in
                   json.dumps(kw['output_format'].model_json_schema()) else {'accept': False, 'confidence': .7,
                                                                             'reason': '散文'})
    out = tasks.run(llm, rep.analysis, rep.rebuild.head_kind, {'clusters', 'structures'})
    from epub_typesetter import board
    bd = board.build(rep.analysis, rep.rebuild.head_kind)
    yin = next(c['key'] for c in bd['clusters'] if '|yin|' in c['key'])
    assert out['clusters'][yin]['role'] == 'quote'
    poem = next(k for k in bd['structures'] if k['kind'] == 'poem')['items'][0]['key']
    assert out['items'][poem]['accept'] is False
    assert out['usage']['calls'] == len(llm.client.messages.calls) and not out['errors']
    sent = ' '.join(c['messages'][0]['content'] for c in llm.client.messages.calls)
    assert '世人都晓神仙好' in sent and len(sent) < 5000                                    # 只发片段


def test_web_settings_and_llm_job(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from epub_typesetter.web import store
    monkeypatch.setattr(store, 'DATA_DIR', str(tmp_path))
    from epub_typesetter.web import app as appmod
    c = TestClient(appmod.app)
    assert c.get('/api/settings/llm').json()['has_credentials'] is False
    assert c.post('/api/settings/llm/test').status_code == 400
    r = c.put('/api/settings/llm', json={'auth_token': 'tok-abcd', 'model_heavy': 'claude-opus-5-5'})
    assert r.json()['auth_token'] == '…abcd' and r.json()['has_credentials']

    pid = c.post('/api/books', files={'file': ('a.epub', _book_bytes(), 'application/epub+zip')}).json()['id']
    _wait(c, pid, ('ready',))
    assert c.post(f'/api/books/{pid}/llm', json={'tasks': ['clusters']}).status_code == 409   # 还没有确认板
    c.post(f'/api/books/{pid}/fix?mode=rebuild')
    _wait(c, pid, ('fixed',))

    real_init = LLM.__init__

    def init(self, settings, cache_dir=None):
        real_init(self, settings, cache_dir)
        self.client = SimpleNamespace(messages=FakeMessages(
            lambda kw: {'role': 'quote', 'confidence': .95, 'reason': '引文'} if 'role' in
            json.dumps(kw['output_format'].model_json_schema()) else {'accept': True, 'confidence': .9, 'reason': '成立'}))
    monkeypatch.setattr(LLM, '__init__', init)
    assert c.post(f'/api/books/{pid}/llm', json={'tasks': []}).status_code == 400
    assert c.post(f'/api/books/{pid}/llm', json={'tasks': ['clusters', 'structures']}).status_code == 202
    d = _wait(c, pid, ('fixed',))
    assert not d['meta']['message']
    bd = c.get(f'/api/books/{pid}/board').json()
    assert bd['llm']['usage']['calls'] > 0
    assert any(cl['llm'] and cl['llm']['role'] == 'quote' for cl in bd['clusters'])


def _book_bytes():
    c1 = ('<h1>第一章</h1>' + '<p>正文叙述，内容内容内容内容内容。</p>' * 4 +
          '<p class="yin">引文一，内容。</p><p class="yin">引文二，内容。</p>')
    return make_epub({'OEBPS/Text/c1.xhtml': XHTML11.format(title='一', body=c1)})


def _wait(c, pid, done, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        d = c.get(f'/api/books/{pid}').json()
        if d['meta']['status'] in done + ('error',):
            assert d['meta']['status'] != 'error', d['meta']['message']
            return d
        time.sleep(.2)
    raise AssertionError('timeout')


def test_heads_task_uses_heavy_model(tmp_path):
    c1 = '<h1>序</h1><p>正文。</p><h1>第一章</h1><p>正文。</p><h1>第二章</h1><p>正文。</p>'
    rep = optimize(Book.load(make_epub({'OEBPS/Text/c1.xhtml': XHTML11.format(title='一', body=c1)})))
    llm = fake_llm(tmp_path, lambda kw: {'changes': [{'n': 1, 'kind': 'chapter', 'matter': 'preface',
                                                      'confidence': .9, 'reason': '序言'},
                                                     {'n': 99, 'kind': 'para', 'confidence': .9, 'reason': '越界'}]})
    out = tasks.run(llm, rep.analysis, rep.rebuild.head_kind, {'heads'})
    call = llm.client.messages.calls[0]
    assert call['model'] == 'claude-opus-5-5' and call['output_config'] == {'effort': 'medium'}
    assert '1. [chapter] 序' in call['messages'][0]['content']
    assert list(out['heads'].values()) == [{'kind': 'chapter', 'matter': 'preface', 'confidence': .9, 'reason': '序言'}]


def test_alt_drafts_and_adoption(tmp_path):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new('RGB', (400, 300), (10, 120, 200)).save(buf, 'JPEG')
    c1 = ('<h1>第一章</h1><p>正文叙述。</p><div class="pic"><img src="../Images/p1.jpg"/><p>图1　海边</p></div>'
          '<p>正文。</p><p><img src="../Images/cover.jpg"/></p><p>正文。</p>')
    src = make_epub({'OEBPS/Text/c1.xhtml': XHTML11.format(title='一', body=c1), 'OEBPS/Images/p1.jpg': buf.getvalue()})
    book = Book.load(src)
    rep = optimize(book)
    llm = fake_llm(tmp_path, lambda kw: {'alt': '图片：海边的一座灯塔', 'decorative': False, 'confidence': .8})
    out = tasks.run(llm, rep.analysis, rep.rebuild.head_kind, {'alts'}, book=book)
    assert len(out['alts']) == 1                                     # 60×80 的小图不发
    (key, draft), = out['alts'].items()
    assert draft['alt'] == '海边的一座灯塔。' and draft['caption'] == '图1　海边'
    sent = llm.client.messages.calls[0]['messages'][0]['content']
    assert sent[0]['type'] == 'image' and sent[0]['source']['media_type'] == 'image/jpeg'
    from epub_typesetter import board
    b2 = Book.load(src)
    optimize(b2, decisions=board.clean({'alts': {key: '海边的灯塔'}}))
    out_book = Book.load(b2.to_bytes())
    alts = [i.get('alt') for p in out_book.content_docs() for i in out_book.tree(p).getroot().iter(
        '{http://www.w3.org/1999/xhtml}img') if 'p1' in i.get('src', '')]
    assert alts == ['海边的灯塔。']


def test_alt_equal_to_caption_gets_a_draft(tmp_path):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new('RGB', (400, 300), (10, 120, 200)).save(buf, 'JPEG')
    c1 = ('<h1>第一章</h1><p>正文。</p><figure><img src="../Images/p1.jpg" alt="图1—1 股价走势"/>'
          '<figcaption>图1—1 股价走势</figcaption></figure><p>正文。</p>'
          '<figure><img src="../Images/p2.jpg" alt="一条上升的折线。"/><figcaption>图1—2 另一张</figcaption></figure>')
    src = make_epub({'OEBPS/Text/c1.xhtml': XHTML11.format(title='一', body=c1), 'OEBPS/Images/p1.jpg': buf.getvalue(),
                     'OEBPS/Images/p2.jpg': buf.getvalue()})
    book = Book.load(src)
    rep = optimize(book)
    jobs = tasks.alt_jobs(book, rep.analysis)
    assert [j[2]['old_alt'] for j in jobs] == ['图1—1 股价走势']        # 已有像样描述的那张不重写
