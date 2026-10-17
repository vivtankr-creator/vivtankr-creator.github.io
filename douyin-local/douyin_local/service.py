"""单任务串行执行，清单持久化；明确确认后才下载。"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from .errors import AuthRequired, WorkflowError
from .manifest import atomic_json, build_manifest, digest, numeric_id, reconcile
from .transfer import StrictF2Downloader


class CollectionService:
    def __init__(self, root: Path, browser) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.browser = browser
        self.lock = asyncio.Lock()
        self.worker = None
        self.verified_mixes = set()

    def folder(self, mix_id: str) -> Path:
        folder = self.root / numeric_id(mix_id)
        if folder.is_symlink():
            raise WorkflowError('合集目录为符号链接，已停止')
        return folder

    def load(self, mix_id: str) -> dict:
        folder = self.folder(mix_id)
        try:
            data = json.loads((folder / 'metadata.json').read_text('utf-8'))
        except (OSError, ValueError):
            raise WorkflowError('没有可恢复的合集清单，请先查询') from None
        # 下载中由 worker 更新状态，避免读取时将正在下载的项目重置。
        if (not self.worker or self.worker.done()) and mix_id not in self.verified_mixes:
            data = reconcile(data, folder)
            atomic_json(folder / 'metadata.json', data)
            self.verified_mixes.add(mix_id)
        return data

    async def lookup(self, url: str) -> dict:
        if self.lock.locked():
            raise WorkflowError('已有任务正在运行，请等待')
        async with self.lock:
            raw = await self.browser.lookup(url)
            mix_id = numeric_id(raw['mix']['mix_id'])
            folder = self.folder(mix_id)
            previous = self.load(mix_id) if (folder / 'metadata.json').exists() else None
            data = reconcile(build_manifest(raw['mix'], raw['pages'], previous), folder)
            atomic_json(folder / 'metadata.json', data)
            return data

    async def enqueue(self, mix_id: str, confirmed: bool) -> dict:
        if not confirmed:
            raise WorkflowError('请先确认合集信息和下载授权')
        if self.worker and not self.worker.done() or self.lock.locked():
            raise WorkflowError('已有任务正在运行，请等待')
        data = reconcile(self.load(mix_id), self.folder(mix_id))
        atomic_json(self.folder(mix_id) / 'metadata.json', data)
        if not data['pagination_complete']:
            raise WorkflowError('分页未完成，请重新查询')
        self.worker = asyncio.create_task(self.download(mix_id))
        return {'status': 'queued', 'mix_id': mix_id}

    async def download(self, mix_id: str) -> None:
        async with self.lock:
            folder = self.folder(mix_id)
            data = reconcile(json.loads((folder / 'metadata.json').read_text('utf-8')), folder)
            data['status'] = 'downloading'
            atomic_json(folder / 'metadata.json', data)
            try:
                for row in data['episodes']:
                    if row['download_status'] == 'downloaded':
                        continue
                    row.update(download_status='downloading', error=None)
                    row['attempts'] += 1
                    atomic_json(folder / 'metadata.json', data)
                    try:
                        urls, user_agent = await self.browser.media(row['aweme_id'])
                        async with StrictF2Downloader(user_agent) as downloader:
                            await downloader.download_verified(urls, folder / row['local_file'])
                        row.update(download_status='downloaded', sha256=digest(folder / row['local_file']), error=None)
                    except AuthRequired as exc:
                        row.update(download_status='failed', error=str(exc))
                        data['status'] = 'auth_required'
                        break
                    except WorkflowError as exc:
                        row.update(download_status='failed', error=str(exc))
                    except Exception:
                        row.update(download_status='failed', error='下载内部错误；请检查环境后重试')
                    atomic_json(folder / 'metadata.json', data)
                    await asyncio.sleep(2)
                reconcile(data, folder)
                if data['status'] != 'auth_required':
                    data['status'] = 'complete' if data['complete'] else 'incomplete'
            except asyncio.CancelledError:
                data['status'] = 'interrupted'
                raise
            except Exception:
                data['status'] = 'failed'
            finally:
                # 只在单集已完成/失败后校验，避免重置正在执行的状态。
                reconcile(data, folder)
                atomic_json(folder / 'metadata.json', data)

    def history(self) -> list[dict]:
        items = []
        for path in self.root.glob('*/metadata.json'):
            if path.parent.name.isdigit():
                try:
                    data = self.load(path.parent.name)
                    items.append({k: data[k] for k in ('mix_id', 'mix_name', 'status')})
                except WorkflowError:
                    continue
        return items

    def open_folder(self, mix_id: str) -> None:
        folder = self.folder(mix_id)
        if not folder.exists():
            raise WorkflowError('输出文件夹尚不存在')
        if sys.platform != 'darwin':
            raise WorkflowError('在 Mac 上才能打开 Finder；输出目录：' + str(folder))
        subprocess.Popen(['open', str(folder)])

    async def close(self) -> None:
        if self.worker and not self.worker.done():
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        await self.browser.close()
