from unittest.mock import AsyncMock

import pytest

from conftest import episode
from douyin_local.errors import AuthRequired, WorkflowError
from douyin_local.service import CollectionService


async def test_resume_retry_and_no_duplicate(tmp_path, raw_mix, mp4, monkeypatch):
    browser = AsyncMock()
    browser.lookup.return_value = {'mix': raw_mix, 'pages': [{'has_more': 0, 'aweme_list': [episode(1), episode(2, 2)]}]}
    browser.media.return_value = (['https://v.douyinvod.com/v'], 'UA')
    service = CollectionService(tmp_path, browser)
    await service.lookup('link')
    calls = []
    async def download(self, urls, path):
        calls.append(path.name)
        if len(calls) == 2:
            raise WorkflowError('临时失败')
        path.write_bytes(mp4)
    monkeypatch.setattr('douyin_local.service.StrictF2Downloader.download_verified', download)
    monkeypatch.setattr('douyin_local.service.asyncio.sleep', AsyncMock())
    with pytest.raises(WorkflowError, match='确认'):
        await service.enqueue('123', False)
    await service.enqueue('123', True)
    await service.worker
    data = service.load('123')
    assert data['downloaded_count'] == 1 and data['failed_count'] == 1 and not data['complete']
    await service.enqueue('123', True)
    await service.worker
    assert service.load('123')['complete']
    assert len(calls) == 3
    assert calls[0] != calls[-1]
    # 模拟进程重新启动：读取清单后再次执行，不再传输已校验文件。
    service = CollectionService(tmp_path, browser)
    await service.enqueue('123', True)
    await service.worker
    assert len(calls) == 3


async def test_auth_pauses_remaining_episodes(tmp_path, raw_mix, monkeypatch):
    browser = AsyncMock()
    browser.lookup.return_value = {'mix': raw_mix, 'pages': [{'has_more': 0, 'aweme_list': [episode(1), episode(2, 2)]}]}
    browser.media.side_effect = AuthRequired('请登录')
    service = CollectionService(tmp_path, browser)
    await service.lookup('link')
    await service.enqueue('123', True)
    await service.worker
    data = service.load('123')
    assert data['status'] == 'auth_required'
    assert browser.media.call_count == 1
    assert data['episodes'][1]['download_status'] == 'pending'
    assert data['downloaded_count'] == 0
