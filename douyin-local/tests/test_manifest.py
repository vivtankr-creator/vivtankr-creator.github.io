import json

import pytest

from douyin_local.errors import WorkflowError
from douyin_local.manifest import atomic_json, build_manifest, digest, media_valid, reconcile, safe_name
from conftest import episode


def test_order_duplicates_and_original_metadata(raw_mix):
    pages = [{'has_more': 1, 'aweme_list': [episode(2, 2)]},
             {'has_more': 0, 'aweme_list': [episode(2, 2), episode(1, 1)]}]
    data = build_manifest(raw_mix, pages)
    assert [e['aweme_id'] for e in data['episodes']] == ['1', '2']
    assert data['discovered_count'] == 2
    assert data['expected_count'] == 2
    assert data['episodes'][0]['original_title'] is None
    assert data['episodes'][0]['original_description'] == '原文\n #话题 😀  '
    assert data['pagination_complete']


def test_missing_and_unknown_count_never_complete(raw_mix, tmp_path):
    data = reconcile(build_manifest(raw_mix, [{'has_more': 0, 'aweme_list': [episode(1)]}]), tmp_path)
    assert data['missing_count'] == 2 and not data['complete']
    del raw_mix['statis']
    data = reconcile(build_manifest(raw_mix, [{'has_more': 0, 'aweme_list': [episode(1)]}]), tmp_path)
    assert data['expected_count'] is None and not data['complete']


def test_resume_missing_corrupt_and_interrupted(raw_mix, tmp_path, mp4):
    data = build_manifest(raw_mix, [{'has_more': 0, 'aweme_list': [episode(1), episode(2, 2)]}])
    first, second = data['episodes']
    path = tmp_path / first['local_file']
    path.write_bytes(mp4)
    first.update(download_status='downloaded', sha256=digest(path))
    second['download_status'] = 'downloading'
    reconcile(data, tmp_path)
    assert first['download_status'] == 'downloaded'
    assert second['download_status'] == 'failed'
    path.write_bytes(b'html not video')
    reconcile(data, tmp_path)
    assert first['download_status'] == 'failed'


def test_path_sanitization_and_traversal(raw_mix, tmp_path):
    assert '/' not in safe_name('../../a/b:标题')
    assert len(safe_name('中' * 200).encode()) <= 100
    data = build_manifest(raw_mix, [{'has_more': 0, 'aweme_list': [episode(1)]}])
    data['episodes'][0]['local_file'] = '../escape.mp4'
    with pytest.raises(WorkflowError):
        reconcile(data, tmp_path)


def test_platform_order_fallback_and_invalid_mix(raw_mix):
    item = episode(1)
    del item['mix_info']['statis']
    data = build_manifest(raw_mix, [{'has_more': 0, 'aweme_list': [item]}])
    assert data['order_basis'] == 'platform_pagination'
    item['mix_info']['mix_id'] = '999'
    with pytest.raises(WorkflowError):
        build_manifest(raw_mix, [{'has_more': 0, 'aweme_list': [item]}])


def test_atomic_export_and_basic_validation(tmp_path, mp4):
    atomic_json(tmp_path / 'metadata.json', {'原文': '\n😀 #不改  '})
    assert json.loads((tmp_path / 'metadata.json').read_text()) == {'原文': '\n😀 #不改  '}
    path = tmp_path / 'video.mp4'
    path.write_bytes(mp4)
    assert media_valid(path)
    path.unlink()
    assert not media_valid(path)
