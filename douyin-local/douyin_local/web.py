"""仅绑定 localhost 的本地界面，使用同源检查和每次启动随机令牌。"""
import argparse
import asyncio
import fcntl
import os
import secrets
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .browser import BrowserSession
from .errors import AuthRequired, WorkflowError
from .service import CollectionService


class LinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=8192)


class DownloadRequest(BaseModel):
    mix_id: str = Field(pattern=r'^[0-9]{1,30}$')
    confirmed: bool = False


def create_app(service: CollectionService, port: int = 8080, open_browser: bool = False) -> FastAPI:
    token = secrets.token_urlsafe(32)
    origin = f'http://127.0.0.1:{port}'

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def delayed_open():
            await asyncio.sleep(1)
            await asyncio.to_thread(webbrowser.open, origin)
        opener = asyncio.create_task(delayed_open()) if open_browser else None
        try:
            yield
        finally:
            if opener:
                opener.cancel()
            await service.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def local_guard(request: Request, call_next):
        if request.headers.get('host') != f'127.0.0.1:{port}':
            return JSONResponse({'error': '仅允许本机 127.0.0.1 访问'}, status_code=403)
        if request.headers.get('origin') not in (None, origin):
            return JSONResponse({'error': '拒绝跨站访问'}, status_code=403)
        if request.url.path.startswith('/api/') and request.headers.get('x-local-token') != token:
            return JSONResponse({'error': '请从本机网页操作'}, status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY',
                                 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                                 'Content-Security-Policy': "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'"})
        return response

    @app.exception_handler(WorkflowError)
    async def workflow_error(request: Request, exc: WorkflowError):
        return JSONResponse({'error': str(exc), 'auth_required': isinstance(exc, AuthRequired)}, status_code=409)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        return JSONResponse({'error': '本地操作失败，请检查安装或浏览器状态；未确认下载成功'}, status_code=500)

    @app.get('/', response_class=HTMLResponse)
    async def index():
        return (Path(__file__).parent / 'index.html').read_text('utf-8').replace('__TOKEN__', token)

    @app.post('/api/login')
    async def login():
        if service.lock.locked():
            raise WorkflowError('任务进行中，请等待暂停或完成')
        await service.browser.login()
        return {'message': '请在打开的浏览器内正常登录，再返回查询或重试'}

    @app.post('/api/mix-info')
    async def mix_info(body: LinkRequest):
        return await service.lookup(body.url)

    @app.post('/api/download-mix')
    async def download_mix(body: DownloadRequest):
        return await service.enqueue(body.mix_id, body.confirmed)

    @app.get('/api/tasks')
    async def history():
        return service.history()

    @app.get('/api/tasks/{mix_id}')
    async def task(mix_id: str):
        return service.load(mix_id)

    @app.post('/api/open-folder')
    async def open_folder(body: DownloadRequest):
        service.open_folder(body.mix_id)
        return {'message': '已打开输出文件夹'}

    @app.get('/api/health')
    async def health():
        return {'status': 'local', 'real_mac_download_verification': 'not tested on Mac'}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--output', type=Path, default=Path.home() / 'Downloads' / '抖音合集下载')
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口必须为 1024–65535')
    os.umask(0o077)
    state = Path.home() / 'Library' / 'Application Support' / 'DouyinLocal'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    instance_lock = (state / 'instance.lock').open('a')
    try:
        fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        instance_lock.close()
        parser.exit(1, '本机已有下载程序运行，请使用已打开的网页或先停止旧进程。\n')
    service = CollectionService(args.output, BrowserSession(state))
    app = create_app(service, args.port, open_browser=not args.no_open)
    try:
        uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, log_level='critical')
    finally:
        instance_lock.close()


if __name__ == '__main__':
    main()
