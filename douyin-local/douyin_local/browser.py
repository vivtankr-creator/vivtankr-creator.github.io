"""只使用用户自己的可见浏览器会话，不解密 Chrome Cookie。"""
import asyncio
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import async_playwright

from .errors import AuthRequired, WorkflowError
from .manifest import numeric_id


AUTH_MESSAGE = '登录已失效或平台要求验证：请在可见抖音浏览器内正常登录/完成验证，再明确点击重试。'


def parse_share(text: str) -> str:
    matches = re.findall(r'https?://[^\s<>"\u3000]+', text)
    for value in matches:
        value = value.rstrip('。，、！!）)】];')
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.port or parsed.username or parsed.password:
            continue
        if parsed.hostname == 'v.douyin.com' and re.fullmatch(r'/[A-Za-z0-9_-]+/?', parsed.path):
            return value
        if parsed.hostname in ('www.douyin.com', 'douyin.com'):
            if re.fullmatch(r'/video/[0-9]+/?', parsed.path):
                return 'https://www.douyin.com' + parsed.path
            ids = parse_qs(parsed.query).get('modal_id', [])
            if len(ids) == 1 and ids[0].isdigit():
                return f'https://www.douyin.com/video/{ids[0]}'
    raise WorkflowError('请粘贴抖音单集 https 链接或包含链接的分享文案')


def checked_json(status: int, body: dict | None) -> dict:
    if status in (401, 403, 429):
        raise AuthRequired(AUTH_MESSAGE)
    if status == 200 and not isinstance(body, dict):
        raise AuthRequired(AUTH_MESSAGE)
    if status != 200:
        raise WorkflowError('平台接口未返回有效数据；请在浏览器检查，未执行下载')
    if body.get('status_code') != 0:
        raise AuthRequired(AUTH_MESSAGE)
    return body


class BrowserSession:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.context = None
        self.page = None
        self.playwright = None
        self.lock = asyncio.Lock()
        self.details = {}

    async def start(self) -> None:
        if self.context is not None:
            return
        os.umask(0o077)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_dir.chmod(0o700)
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.state_dir / 'browser'), headless=False)
        self.page = await self.context.new_page()
        self.page.on('response', self._observe_response)

    async def _observe_response(self, response) -> None:
        # 只读取本工具页面自身收到的公开作品详情，不截获其他浏览器流量。
        parsed = urlsplit(response.url)
        if parsed.hostname != 'www.douyin.com' or parsed.path != '/aweme/v1/web/aweme/detail/':
            return
        try:
            data = checked_json(response.status, await response.json())
            item = data.get('aweme_detail') or {}
            if item.get('aweme_id'):
                self.details[str(item['aweme_id'])] = data
        except Exception:
            return

    async def login(self) -> None:
        async with self.lock:
            await self.start()
            await self.page.goto('https://www.douyin.com/', wait_until='domcontentloaded')
            await self.page.bring_to_front()

    async def json_request(self, path: str, params: dict) -> dict:
        # 在真实页面中发送普通同源请求；不合成指纹、签名或 Token。
        result = await self.page.evaluate('''async (path) => {
          const r = await fetch(path, {credentials:'same-origin', redirect:'error'});
          let body = null; try { body = await r.json(); } catch (_) {}
          return {status:r.status, body};
        }''', path + '?' + urlencode(params))
        return checked_json(result['status'], result['body'])

    async def lookup(self, text: str) -> dict:
        async with self.lock:
            await self.start()
            url = parse_share(text)
            response = await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
            if response and response.status in (401, 403, 429):
                raise AuthRequired(AUTH_MESSAGE)
            if '验证码' in await self.page.title():
                raise AuthRequired(AUTH_MESSAGE)
            parsed = urlsplit(self.page.url)
            match = re.fullmatch(r'/video/([0-9]+)/?', parsed.path)
            aweme_id = match.group(1) if match else (parse_qs(parsed.query).get('modal_id') or [None])[0]
            if parsed.hostname != 'www.douyin.com' or not aweme_id:
                raise WorkflowError('分享链接未解析为抖音单集，请在浏览器确认后输入完整 video 链接')
            body = self.details.pop(str(aweme_id), None)
            if body is None:
                body = await self.json_request('/aweme/v1/web/aweme/detail/', {'aid': 6383, 'aweme_id': numeric_id(aweme_id)})
            detail = body.get('aweme_detail')
            if not isinstance(detail, dict):
                raise AuthRequired(AUTH_MESSAGE)
            mix = detail.get('mix_info') or {}
            if not mix.get('mix_id'):
                raise WorkflowError('此单集没有正式合集；不会转为下载用户主页')
            mix_id = numeric_id(mix['mix_id'])
            pages, cursors, cursor = [], set(), 0
            for _ in range(1000):
                if cursor in cursors:
                    raise WorkflowError('合集分页游标重复，不能确认完整性')
                cursors.add(cursor)
                page = await self.json_request('/aweme/v1/web/mix/aweme/',
                                               {'aid': 6383, 'mix_id': mix_id, 'cursor': cursor, 'count': 20})
                if not isinstance(page.get('aweme_list'), list) or page.get('has_more') not in (0, 1, False, True):
                    raise WorkflowError('合集分页响应不完整')
                pages.append(page)
                if not page['has_more']:
                    return {'mix': mix, 'pages': pages}
                cursor = page.get('cursor')
                if not isinstance(cursor, int) or cursor < 0:
                    raise WorkflowError('合集分页游标无效')
                await asyncio.sleep(2)
            raise WorkflowError('合集分页超过安全上限，无法确认完整性')

    async def media(self, aweme_id: str) -> tuple[list[str], str]:
        async with self.lock:
            await self.start()
            if urlsplit(self.page.url).hostname != 'www.douyin.com':
                raise AuthRequired(AUTH_MESSAGE)
            body = await self.json_request('/aweme/v1/web/aweme/detail/', {'aid': 6383, 'aweme_id': numeric_id(aweme_id)})
            item = body.get('aweme_detail')
            if not isinstance(item, dict):
                raise AuthRequired(AUTH_MESSAGE)
            status = item.get('status') or {}
            if status.get('private_status', 0) != 0 or status.get('is_prohibited') or status.get('part_see'):
                raise WorkflowError('作品受限或非公开，已停止该集下载')
            video = item.get('video') or {}
            if video.get('is_drm') or video.get('drm_type'):
                raise WorkflowError('视频受 DRM 限制，不尝试下载或解密')
            urls = video.get('play_addr', {}).get('url_list') or []
            if not urls:
                raise WorkflowError('平台没有提供公开 MP4 视频地址，不尝试绕过限制')
            # 只提供真实浏览器 UA。会话 Cookie 保留于浏览器，禁止转交 CDN。
            return urls, await self.page.evaluate('navigator.userAgent')

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
