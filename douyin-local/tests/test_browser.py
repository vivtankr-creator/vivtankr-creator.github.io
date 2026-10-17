from unittest.mock import AsyncMock

import pytest

from douyin_local.browser import BrowserSession, checked_json, parse_share
from douyin_local.errors import AuthRequired, WorkflowError
from conftest import episode


@pytest.mark.parametrize('text,expected', [
    ('分享复制 https://v.douyin.com/xsZCGxFbWTQ/ 打开抖音', 'https://v.douyin.com/xsZCGxFbWTQ/'),
    ('https://www.douyin.com/video/7673835272434296714', 'https://www.douyin.com/video/7673835272434296714'),
    ('https://www.douyin.com/?modal_id=123', 'https://www.douyin.com/video/123')])
def test_share_links(text, expected):
    assert parse_share(text) == expected


@pytest.mark.parametrize('text', ['https://evil.test/video/123', 'https://www.douyin.com@evil.test/video/1',
                                 'file:///etc/passwd', 'https://www.douyin.com/user/123',
                                 'https://www.douyin.com:8000/video/1'])
def test_reject_untrusted_or_profile(text):
    with pytest.raises(WorkflowError):
        parse_share(text)


@pytest.mark.parametrize('status', [401, 403, 429])
def test_blocks_pause(status):
    with pytest.raises(AuthRequired):
        checked_json(status, {})


def session(tmp_path, responses):
    browser = BrowserSession(tmp_path)
    browser.start = AsyncMock()
    browser.page = AsyncMock()
    browser.page.url = 'https://www.douyin.com/video/1'
    browser.page.goto.return_value = None
    browser.page.title.return_value = '抖音'
    browser.json_request = AsyncMock(side_effect=responses)
    return browser


async def test_formal_mix_absent(tmp_path):
    browser = session(tmp_path, [{'aweme_detail': {'aweme_id': '1'}}])
    with pytest.raises(WorkflowError, match='没有正式合集'):
        await browser.lookup('https://www.douyin.com/video/1')
    assert browser.json_request.call_count == 1


async def test_pagination_aggregate(tmp_path, raw_mix, monkeypatch):
    monkeypatch.setattr('douyin_local.browser.asyncio.sleep', AsyncMock())
    browser = session(tmp_path, [{'aweme_detail': {'mix_info': raw_mix}},
                                {'aweme_list': [episode(1)], 'has_more': 1, 'cursor': 20},
                                {'aweme_list': [episode(2, 2)], 'has_more': 0, 'cursor': 40}])
    result = await browser.lookup('https://www.douyin.com/video/1')
    assert len(result['pages']) == 2
    assert browser.json_request.call_args_list[-1].args[1]['cursor'] == 20


async def test_stalled_cursor_never_complete(tmp_path, raw_mix):
    browser = session(tmp_path, [{'aweme_detail': {'mix_info': raw_mix}},
                                {'aweme_list': [episode(1)], 'has_more': 1, 'cursor': 0}])
    with pytest.raises(WorkflowError, match='游标重复'):
        await browser.lookup('https://www.douyin.com/video/1')
