import re
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from douyin_local.service import CollectionService
from douyin_local.web import create_app


def test_local_security_and_confirmation(tmp_path):
    service = CollectionService(tmp_path, AsyncMock())
    with TestClient(create_app(service), base_url='http://127.0.0.1:8080') as client:
        response = client.get('/')
        assert response.status_code == 200
        token = re.search("const token='([^']+)'", response.text).group(1)
        assert client.get('/api/tasks').status_code == 403
        headers = {'X-Local-Token': token}
        assert client.get('/api/tasks', headers=headers).status_code == 200
        assert client.get('/', headers={'Host': 'evil.test'}).status_code == 403
        assert client.post('/api/login', headers=headers | {'Origin': 'https://evil.test'}, json={}).status_code == 403
        assert client.post('/api/download-mix', headers=headers, json={'mix_id': '123'}).status_code == 409
        assert client.get('/api/tasks/..%2Fsecret', headers=headers).status_code != 200
        assert client.get('/api/health', headers=headers).json()['real_mac_download_verification'] == 'not tested on Mac'


def test_bind_is_fixed_localhost():
    from pathlib import Path
    source = Path('douyin_local/web.py').read_text()
    assert "host='127.0.0.1'" in source
    assert "add_argument('--host'" not in source


async def test_launch_opens_default_browser(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import Mock
    opener = Mock(return_value=True)
    monkeypatch.setattr('douyin_local.web.webbrowser.open', opener)
    service = CollectionService(tmp_path, AsyncMock())
    app = create_app(service, 8081, open_browser=True)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(1.1)
        opener.assert_called_once_with('http://127.0.0.1:8081')
