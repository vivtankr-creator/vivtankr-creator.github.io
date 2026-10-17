"""真实浏览器操作本地 UI；平台数据为本地夹具。"""
import os
import shutil
import socket
import threading
import time
from unittest.mock import AsyncMock

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from conftest import episode
from douyin_local.service import CollectionService
from douyin_local.web import create_app


def test_browser_confirmation_and_escaping(tmp_path, raw_mix):
    binary = os.environ.get('TEST_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    if not binary:
        pytest.skip('系统 Chromium 不可用；UI 测试未执行')
    browser = AsyncMock()
    raw_mix['mix_name'] = '<img src=x onerror=alert(1)>原剧名'
    browser.lookup.return_value = {'mix': raw_mix, 'pages': [{'has_more': 0, 'aweme_list': [episode(1), episode(2, 2)]}]}
    browser.media.side_effect = Exception('测试不下载真实视频')
    service = CollectionService(tmp_path / 'output', browser)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(service, port), host='127.0.0.1', port=port,
                                         log_level='critical', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        with sync_playwright() as playwright:
            chromium = playwright.chromium.launch(executable_path=binary, headless=True)
            page = chromium.new_page()
            page.goto(f'http://127.0.0.1:{port}')
            page.locator('#url').fill('https://www.douyin.com/video/1')
            page.locator('#lookup').click()
            page.locator('#summary').wait_for()
            assert '已查询 2 集' in page.locator('#summary').inner_text()
            assert page.locator('#summary img').count() == 0
            assert page.locator('#rows tr').count() == 2
            page.locator('#download').click()
            expect(page.locator('#notice')).to_contain_text('请先勾选')
            assert not browser.media.called
            page.locator('#consent').check()
            page.locator('#download').click()
            expect(page.locator('#notice')).to_contain_text('任务已排队')
            chromium.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
