import shutil
import struct
import subprocess

import pytest


@pytest.fixture
def mp4(tmp_path):
    """有 ffmpeg 时生成实际可探测视频；否则使用明确的签名级夹具。"""
    path = tmp_path / 'sample.mp4'
    if shutil.which('ffmpeg'):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=32x32:d=0.1',
                        '-an', '-c:v', 'mpeg4', str(path)], check=True)
    else:
        path.write_bytes(struct.pack('>I', 24) + b'ftypisom' + b'\0' * 12 + b'fixture' * 10)
    return path.read_bytes()


@pytest.fixture
def raw_mix():
    return {'mix_id': '123', 'mix_name': '原剧名', 'statis': {'total': 2}}


def episode(aweme_id, order=1, desc='原文\n #话题 😀  '):
    return {'aweme_id': str(aweme_id), 'title': None, 'desc': desc,
            'mix_info': {'mix_id': '123', 'statis': {'current_episode': order}}}
