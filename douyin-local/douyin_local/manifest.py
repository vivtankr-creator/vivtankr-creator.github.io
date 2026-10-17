"""原始元数据、顺序及断点清单。"""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import WorkflowError


def numeric_id(value: Any) -> str:
    value = str(value)
    if not re.fullmatch(r"[0-9]{1,30}", value):
        raise WorkflowError("平台返回了无效的作品或合集 ID")
    return value


def safe_name(value: str) -> str:
    value = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', '_', value).strip(' .')
    # macOS 文件名限制按 UTF-8 字节，而非字符数。
    return value.encode('utf-8')[:100].decode('utf-8', errors='ignore') or '合集'


def media_valid(path: Path) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size < 24:
        return False
    with path.open('rb') as stream:
        header = stream.read(32)
    if header[4:8] != b'ftyp':
        return False
    probe = shutil.which('ffprobe')
    if probe:
        try:
            result = subprocess.run(
                [probe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                 'stream=codec_type', '-of', 'json', str(path)], capture_output=True, timeout=30)
            return result.returncode == 0 and bool(json.loads(result.stdout).get('streams'))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
    return True


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix('.json.tmp')
    with tmp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def build_manifest(mix: dict, pages: list[dict], previous: dict | None = None) -> dict:
    mix_id = numeric_id(mix['mix_id'])
    unique = {}
    for page in pages:
        for item in page['aweme_list']:
            aweme_id = numeric_id(item.get('aweme_id'))
            item_mix = (item.get('mix_info') or {}).get('mix_id')
            if item_mix is not None and numeric_id(item_mix) != mix_id:
                raise WorkflowError('分页包含其他合集作品，已停止')
            if aweme_id in unique:
                continue
            unique[aweme_id] = item
    if not unique:
        raise WorkflowError('正式合集没有可用剧集，请检查登录或平台权限')
    rows = list(unique.values())
    # 平台明确给出集序时优先使用；否则保留合集接口的原始分页顺序。
    orders = [(v.get('mix_info') or {}).get('statis', {}).get('current_episode') for v in rows]
    if all(isinstance(x, int) and x > 0 for x in orders):
        if len(set(orders)) != len(orders):
            raise WorkflowError('平台集序冲突，无法确认合集顺序')
        rows = [v for _, v in sorted(zip(orders, rows), key=lambda pair: pair[0])]
    previous_rows = {v['aweme_id']: v for v in (previous or {}).get('episodes', [])}
    episodes = []
    for index, item in enumerate(rows, 1):
        aweme_id = numeric_id(item['aweme_id'])
        old = previous_rows.get(aweme_id, {})
        episodes.append({
            'aweme_id': aweme_id, 'original_title': item.get('title'),
            'original_description': item.get('desc', ''),
            'source_url': f'https://www.douyin.com/video/{aweme_id}',
            'mix_id': mix_id, 'episode_order': index,
            'local_file': old.get('local_file', f'{aweme_id}_{safe_name(item.get("desc", ""))}.mp4'),
            'download_status': old.get('download_status', 'pending'),
            'error': old.get('error'), 'sha256': old.get('sha256'),
            'attempts': old.get('attempts', 0),
        })
    count = mix.get('statis', {}).get('total')
    expected = count if isinstance(count, int) and count > 0 else None
    return {'schema_version': 1, 'mix_id': mix_id, 'mix_name': mix.get('mix_name', ''),
            'expected_count': expected, 'discovered_count': len(episodes),
            'pagination_complete': bool(pages) and pages[-1].get('has_more') in (0, False),
            'order_basis': 'platform_episode' if all(isinstance(x, int) and x > 0 for x in orders) else 'platform_pagination',
            'status': 'ready', 'episodes': episodes}


def reconcile(manifest: dict, folder: Path) -> dict:
    for row in manifest['episodes']:
        path = folder / row['local_file']
        if path.parent.resolve() != folder.resolve():
            raise WorkflowError('清单路径越界，已停止')
        if row['download_status'] == 'downloaded':
            if not media_valid(path) or not row.get('sha256') or digest(path) != row['sha256']:
                row.update(download_status='failed', error='文件缺失、损坏或校验值不一致')
        elif row['download_status'] == 'downloading':
            row.update(download_status='failed', error='上次下载被中断，请重试')
    manifest['downloaded_count'] = sum(r['download_status'] == 'downloaded' for r in manifest['episodes'])
    manifest['failed_count'] = sum(r['download_status'] == 'failed' for r in manifest['episodes'])
    manifest['missing_count'] = max(0, (manifest['expected_count'] or len(manifest['episodes'])) - manifest['downloaded_count'])
    manifest['complete'] = (manifest['pagination_complete'] and manifest['expected_count'] is not None
                            and manifest['expected_count'] == len(manifest['episodes']) == manifest['downloaded_count'])
    return manifest
