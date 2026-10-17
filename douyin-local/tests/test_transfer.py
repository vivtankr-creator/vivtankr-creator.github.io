import httpx
import pytest

from douyin_local.errors import AuthRequired, WorkflowError
from douyin_local.transfer import StrictF2Downloader


async def test_f2_real_class_local_transport(mp4, tmp_path):
    from f2.dl.base_downloader import BaseDownloader
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=mp4)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with StrictF2Downloader('actual-browser-agent', client) as downloader:
        assert isinstance(downloader, BaseDownloader)
        await downloader.download_verified(['https://v.douyinvod.com/video.mp4'], tmp_path / 'ok.mp4')
    assert (tmp_path / 'ok.mp4').read_bytes() == mp4
    assert 'cookie' not in requests[0].headers


@pytest.mark.parametrize('status', [403, 429])
async def test_403_no_retry_or_success(status, tmp_path):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, content=b'Forbidden')
    async with StrictF2Downloader('UA', httpx.AsyncClient(transport=httpx.MockTransport(handler))) as downloader:
        with pytest.raises(AuthRequired):
            await downloader.download_verified(['https://v.douyinvod.com/v'], tmp_path / 'v.mp4')
    assert len(seen) == 1
    assert not (tmp_path / 'v.mp4').exists()
    assert not (tmp_path / 'v.part').exists()


@pytest.mark.parametrize('response', [httpx.Response(200, content=b'<html>captcha</html>'),
    httpx.Response(200, content=b'partial', headers={'Content-Length': '1000'}),
    httpx.Response(302, headers={'Location': 'http://127.0.0.1/internal'})])
async def test_invalid_file_and_redirect(response, tmp_path):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response))
    async with StrictF2Downloader('UA', client) as downloader:
        with pytest.raises(WorkflowError):
            await downloader.download_verified(['https://v.douyinvod.com/v'], tmp_path / 'v.mp4')
    assert not (tmp_path / 'v.mp4').exists()
