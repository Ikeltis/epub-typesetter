import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from conftest import make_epub


@pytest.fixture
def client(tmp_path, monkeypatch):
    from epub_typesetter.web import store
    monkeypatch.setattr(store, 'DATA_DIR', str(tmp_path))
    from epub_typesetter.web.app import app
    return TestClient(app)


def wait(client, pid, done=('ready', 'fixed', 'error'), timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        r = client.get(f'/api/books/{pid}').json()
        if r['meta']['status'] in done:
            return r
        time.sleep(0.2)
    raise AssertionError('timeout')


def test_full_flow(client):
    r = client.post('/api/books', files={'file': ('测试书.epub', make_epub(), 'application/epub+zip')})
    assert r.status_code == 201
    pid = r.json()['id']
    d = wait(client, pid)
    assert d['meta']['status'] == 'ready'
    assert d['meta']['title'] == '测试书'
    assert d['audit']['issues']['total'] > 0
    assert client.post(f'/api/books/{pid}/fix').status_code == 202
    d = wait(client, pid, done=('fixed', 'error'))
    assert d['meta']['status'] == 'fixed', d['meta']['message']
    assert d['fix']['text']['equal']
    assert d['fix']['changes']
    r = client.get(f'/api/books/{pid}/download')
    assert r.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist()[0] == 'mimetype'
    assert "filename*=UTF-8''" in r.headers['content-disposition']
    assert any(b['id'] == pid for b in client.get('/api/books').json())
    # 排版重建模式
    assert client.post(f'/api/books/{pid}/fix?mode=rebuild').status_code == 202
    d = wait(client, pid, done=('fixed', 'error'))
    assert d['meta']['status'] == 'fixed', d['meta']['message']
    assert d['fix']['mode'] == 'rebuild' and d['fix']['rebuild']['files'] >= 1 and d['fix']['text']['equal']
    assert client.delete(f'/api/books/{pid}').status_code == 204
    assert client.get(f'/api/books/{pid}').status_code == 404


def test_reject_non_epub(client):
    r = client.post('/api/books', files={'file': ('a.epub', b'hello', 'application/epub+zip')})
    assert r.status_code == 400


def test_broken_zip_becomes_error_status(client):
    r = client.post('/api/books', files={'file': ('a.epub', b'PK\x03\x04garbage', 'application/epub+zip')})
    d = wait(client, r.json()['id'])
    assert d['meta']['status'] == 'error' and d['meta']['message']


def test_bad_id_is_404(client):
    assert client.get('/api/books/../../etc').status_code == 404
    assert client.get('/api/books/zzzzzzzzzzzz').status_code == 404


def test_rules_list(client):
    rules = client.get('/api/rules').json()
    assert any(r['id'] == 'STR-004' and r['category_name'] == '结构' for r in rules)


def test_waiver_endpoints(client):
    pid = client.post('/api/books', files={'file': ('测试书.epub', make_epub(), 'application/epub+zip')}).json()['id']
    d = wait(client, pid)
    item = next(i for i in d['audit']['issues']['issues'] if i['rule_id'] == 'STR-004')
    assert item['hint'] and item['status'] == 'open'
    body = {'rule': 'STR-004', 'file': item['file'], 'reason': ''}
    assert client.post(f'/api/books/{pid}/waivers', json=body).status_code == 400      # 理由必填
    body['reason'] = '测试：保持 EPUB 2'
    r = client.post(f'/api/books/{pid}/waivers', json=body)
    assert r.status_code == 201 and r.json()['id'] == 'w-001'
    d = client.get(f'/api/books/{pid}').json()
    item = next(i for i in d['audit']['issues']['issues'] if i['rule_id'] == 'STR-004')
    assert item['status'] == 'waived' and item['waivers'][0]['reason'] == '测试：保持 EPUB 2'
    assert d['audit']['issues']['summary']['waived'] == 1
    assert client.get(f'/api/books/{pid}/waivers').json()['ignore'][0]['rule'] == 'STR-004'
    assert client.delete(f'/api/books/{pid}/waivers/w-009').status_code == 404
    assert client.delete(f'/api/books/{pid}/waivers/w-001').status_code == 204
    d = client.get(f'/api/books/{pid}').json()
    assert next(i for i in d['audit']['issues']['issues'] if i['rule_id'] == 'STR-004')['status'] == 'open'


def test_board_endpoints(client):
    pid = client.post('/api/books', files={'file': ('测试书.epub', make_epub(), 'application/epub+zip')}).json()['id']
    wait(client, pid)
    assert client.get(f'/api/books/{pid}/board').status_code == 404              # 还没重建
    client.post(f'/api/books/{pid}/fix?mode=rebuild')
    wait(client, pid, done=('fixed', 'error'))
    bd = client.get(f'/api/books/{pid}/board').json()
    assert bd['clusters'] and bd['decisions']['clusters'] == {}
    key = bd['clusters'][0]['key']
    r = client.put(f'/api/books/{pid}/decisions', json={'clusters': {key: 'quote'}})
    assert r.status_code == 200 and r.json()['clusters'] == {key: 'quote'}
    assert client.get(f'/api/books/{pid}').json()['fix']['decisions_changed']
    client.post(f'/api/books/{pid}/fix?mode=rebuild')
    d = wait(client, pid, done=('fixed', 'error'))
    assert d['meta']['status'] == 'fixed' and not d['fix'].get('decisions_changed')
    assert client.get(f'/api/books/{pid}/board').json()['decisions']['clusters'] == {key: 'quote'}


def test_versions_kept_and_downloadable(client):
    pid = client.post('/api/books', files={'file': ('测试书.epub', make_epub(), 'application/epub+zip')}).json()['id']
    wait(client, pid)
    for mode in ('basic', 'rebuild'):
        client.post(f'/api/books/{pid}/fix?mode={mode}')
        wait(client, pid, done=('fixed', 'error'))
    d = client.get(f'/api/books/{pid}').json()
    vs = d['versions']
    assert [v['n'] for v in vs] == [2, 1] and [v['mode'] for v in vs] == ['rebuild', 'basic']
    assert vs[0]['decisions'] == 0 and vs[0]['text_ok'] and d['fix']['version'] == 2
    assert d['summary']['board']['clusters'] >= 1 and d['summary']['decisions'] == {'total': 0, 'llm': 0}
    r = client.get(f'/api/books/{pid}/download?which=v1')
    assert r.status_code == 200 and '%C2%B7v1' in r.headers['content-disposition']
    assert client.get(f'/api/books/{pid}/download?which=v9').status_code == 404
    assert client.get(f'/api/books/{pid}/download?which=../x').status_code == 400
    for _ in range(5):                                            # 只留最近 5 个版本
        client.post(f'/api/books/{pid}/fix?mode=basic')
        wait(client, pid, done=('fixed', 'error'))
    assert [v['n'] for v in client.get(f'/api/books/{pid}').json()['versions']] == [7, 6, 5, 4, 3]
