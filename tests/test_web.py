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
