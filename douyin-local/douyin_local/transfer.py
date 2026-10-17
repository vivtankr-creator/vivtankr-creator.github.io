"""F2 传输适配：修正 TLS、吞异常和错误成功计数。"""
import asyncio
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from f2.dl.base_downloader import BaseDownloader

from .errors import AuthRequired, WorkflowError
from .manifest import media_valid


CDN_SUFFIXES = ('douyinvod.com', 'bytevod.com', 'douyin.com', 'bytecdn.cn', 'ibytedtos.com', 'bytedance.com')


def validate_media_url(url: str) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port
            or not any(host == suffix or host.endswith('.' + suffix) for suffix in CDN_SUFFIXES)):
        raise WorkflowError('媒体地址不属于允许的抖音 CDN，已停止')


class StrictF2Downloader(BaseDownloader):
    def __init__(self, user_agent: str, client: httpx.AsyncClient | None = None) -> None:
        super().__init__({'headers': {'User-Agent': user_agent}, 'cookie': '',
                          'max_tasks': 1, 'max_connections': 1, 'max_retries': 0, 'timeout': 60})
        # F2 默认 transport 使用 verify=False，必须替换，且不传 Cookie 给媒体域名。
        self._aclient = client or httpx.AsyncClient(
            verify=True, timeout=60, follow_redirects=False, headers={'User-Agent': user_agent})

    async def close(self) -> None:
        # F2 原 close 会为关闭而创建未使用的同步客户端，避免该副作用。
        if self._aclient is not None:
            await self._aclient.aclose()

    async def download_verified(self, urls: list[str], destination: Path) -> None:
        self.download_tasks.append(asyncio.create_task(self._strict_transfer(urls, destination)))
        try:
            # 保留 F2 任务执行器；异常必须传递给逐集清单。
            await self.execute_tasks()
        finally:
            self.download_tasks.clear()

    async def _strict_transfer(self, urls: list[str], destination: Path) -> None:
        tmp = destination.with_suffix('.part')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if tmp.is_symlink() or destination.is_symlink():
            raise WorkflowError('目标文件是符号链接，已停止')
        # 逐集重试重新获取媒体地址；不在未知 Range 语义下拼接部分文件。
        if not urls:
            raise WorkflowError('没有媒体地址')
        url = urls[0]
        try:
            for _ in range(6):
                validate_media_url(url)
                async with self.aclient.stream('GET', url) as response:
                    if response.status_code in (401, 403, 429):
                        raise AuthRequired('媒体请求被平台阻止；请正常登录/验证后点击重试')
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get('location')
                        if not location:
                            raise WorkflowError('媒体重定向缺少目标')
                        url = urljoin(url, location)
                        continue
                    if response.status_code != 200:
                        raise WorkflowError('媒体服务器返回错误，稍后可重试')
                    if 'text/html' in response.headers.get('content-type', '').lower():
                        raise AuthRequired('媒体返回登录或验证页面；请在正常网站认证后重试')
                    size = 0
                    with tmp.open('wb') as stream:
                        async for chunk in response.aiter_bytes():
                            stream.write(chunk)
                            size += len(chunk)
                    expected = response.headers.get('content-length')
                    if expected and int(expected) != size:
                        raise WorkflowError('媒体文件长度不完整')
                    if not media_valid(tmp):
                        raise WorkflowError('文件未通过 MP4/可用 ffprobe 校验')
                    tmp.replace(destination)
                    return
            raise WorkflowError('媒体重定向次数过多')
        except httpx.HTTPError:
            raise WorkflowError('媒体网络连接失败，可重试') from None
        finally:
            tmp.unlink(missing_ok=True)
