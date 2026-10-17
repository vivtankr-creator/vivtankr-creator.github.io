"""
抖音分享页兜底下载模块

背景
----
抖音 web 端启用 Argus 风控后，F2 调用的
``https://www.douyin.com/aweme/v1/web/aweme/detail/`` 接口会返回
``403 Blocked by ArgusSecurityPlugin Uifid Not Found``，详情接口拿不到作品数据。

本模块改用移动端分享页的服务端渲染数据作为兜底通道：
``https://www.iesdouyin.com/share/video/{aweme_id}/?region=CN``
页面内联的 ``window._ROUTER_DATA`` 中包含完整 aweme 数据
（图文作品为 ``images``，视频作品为 ``video``），无需签名接口即可下载。

产物命名与 F2 保持一致，便于 ``core.py`` 既有的存在性检查与文件查找逻辑复用：
``Download/{aweme_id}_{desc:.80}/{aweme_id}_{desc:.80}_image_N.webp``
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from f2.apps.douyin.utils import format_file_name
from f2.utils.utils import replaceT

try:
    from .logger import get_logger
except ImportError:
    from logger import get_logger

logger = get_logger()

SHARE_PAGE_URL = "https://www.iesdouyin.com/share/video/{aweme_id}/?region=CN"

# 分享页为移动端渲染，使用移动端 UA 才能拿到 SSR 数据
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

DEFAULT_NAMING = "{aweme_id}_{desc:.80}"

# 图片文件头（webp / jpeg / png）
IMAGE_MAGICS = (b"RIFF", b"\xff\xd8\xff", b"\x89PNG")

# 风控拦截特征（F2 抛出的 HTTP 403 / Argus 文案）
BLOCKED_PATTERNS = (
    "403",
    "forbidden",
    "argussecurityplugin",
    "uifid not found",
)

MAX_CONCURRENCY = 3
MAX_RETRIES = 3


def create_client(headers: Dict[str, str], timeout: float = 30.0) -> httpx.AsyncClient:
    """
    创建 HTTP 客户端（抽成函数便于测试替换）

    Args:
        headers: 请求头
        timeout: 超时（秒）

    Returns:
        httpx 异步客户端
    """
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers)


def is_blocked_error(message: str) -> bool:
    """
    判断错误信息是否为风控拦截（详情接口被 Argus/Uifid 拦住）

    Args:
        message: 异常或错误信息

    Returns:
        命中风控特征返回 True
    """
    if not message:
        return False
    lowered = message.lower()
    return any(pattern in lowered for pattern in BLOCKED_PATTERNS)


def parse_router_data(html: str) -> Optional[Dict[str, Any]]:
    """
    从分享页 HTML 中解析 ``window._ROUTER_DATA``

    使用 ``JSONDecoder.raw_decode`` 而不是正则，避免 JSON 字符串内出现
    ``</script>`` 之类的片段导致截断。

    Args:
        html: 分享页 HTML

    Returns:
        解析后的字典，未找到时返回 None
    """
    if not html:
        return None
    index = html.find("window._ROUTER_DATA")
    if index < 0:
        return None
    try:
        start = html.index("{", index)
    except ValueError:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html[start:])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def extract_aweme_item(router_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    从 ``_ROUTER_DATA`` 中提取作品原始数据（item_list[0]）

    页面结构可能随抖音前端改版调整 loaderData 的键名，因此遍历查找含
    ``videoInfoRes`` 的节点，而不是硬编码 ``video_(id)/page``。

    Args:
        router_data: 解析后的 ``_ROUTER_DATA``

    Returns:
        作品数据字典，未找到时返回 None
    """
    if not isinstance(router_data, dict):
        return None
    loader_data = router_data.get("loaderData") or {}
    for page in loader_data.values():
        if not isinstance(page, dict):
            continue
        info = page.get("videoInfoRes")
        if not isinstance(info, dict):
            continue
        items = info.get("item_list") or []
        if items:
            return items[0]
    return None


def build_aweme_data(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    把分享页数据整理成与 F2 过滤结果一致的字段（供命名与去重使用）

    desc 会用 F2 的 ``replaceT`` 处理非法字符（换行、逗号等替换为下划线），
    与 F2 下载产物的命名保持一致。

    Args:
        item: 分享页中的作品数据

    Returns:
        精简后的作品数据
    """
    author = item.get("author") or {}
    images = item.get("images") or []
    return {
        "aweme_id": str(item.get("aweme_id", "")),
        "desc": replaceT(item.get("desc") or ""),
        "create_time": item.get("create_time"),
        "nickname": author.get("nickname", ""),
        # 抖音图文作品 aweme_type=68；分享页可能返回其他值，这里以是否含图片为准
        "aweme_type": 68 if images else item.get("aweme_type", 0),
    }


def collect_media(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    从作品数据中整理出待下载的媒体列表

    图文作品返回全部图片（``_image_N.webp``），视频作品返回单个视频
    （``_video.mp4``，并把带水印的 ``/playwm/`` 地址替换为 ``/play/``）。

    Args:
        item: 分享页中的作品数据

    Returns:
        形如 ``[{"suffix": "_image_1.webp", "urls": [...], "kind": "image"}]`` 的列表
    """
    media: List[Dict[str, Any]] = []

    for index, image in enumerate(item.get("images") or [], start=1):
        urls = [url for url in (image.get("url_list") or []) if url]
        if urls:
            media.append(
                {"suffix": f"_image_{index}.webp", "urls": urls, "kind": "image"}
            )
    if media:
        return media

    video = item.get("video") or {}
    urls: List[str] = []
    for key in ("play_addr", "play_addr_h264", "download_addr"):
        addr = video.get(key) or {}
        for url in addr.get("url_list") or []:
            if url:
                urls.append(url.replace("/playwm/", "/play/"))
    if urls:
        media.append({"suffix": "_video.mp4", "urls": urls, "kind": "video"})
    return media


async def fetch_aweme_item(
    aweme_id: str,
    cookie: str = "",
    timeout: float = 30.0,
    max_retries: int = MAX_RETRIES,
) -> Dict[str, Any]:
    """
    通过分享页获取作品数据

    Args:
        aweme_id: 作品ID
        cookie: 可选 Cookie（不带 Cookie 也能取到公开作品）
        timeout: 单次请求超时（秒）
        max_retries: 重试次数

    Returns:
        分享页中的作品数据

    Raises:
        RuntimeError: 重试后仍未取到数据
    """
    url = SHARE_PAGE_URL.format(aweme_id=aweme_id)
    headers = {"User-Agent": MOBILE_UA}
    if cookie:
        headers["Cookie"] = cookie

    last_error = ""
    async with create_client(headers, timeout=timeout) as client:
        for attempt in range(1, max_retries + 1):
            try:
                response = await client.get(url)
            except Exception as exc:  # noqa: BLE001 - 网络异常统一重试
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                item = extract_aweme_item(parse_router_data(response.text))
                if item:
                    logger.info(f"[SHARE-PAGE] 获取作品数据成功，aweme_id: {aweme_id}")
                    return item
                last_error = f"分享页未解析出作品数据 (HTTP {response.status_code})"
            logger.warning(
                f"[SHARE-PAGE] 第 {attempt}/{max_retries} 次获取失败: {last_error}"
            )
            if attempt < max_retries:
                await asyncio.sleep(attempt)

    raise RuntimeError(f"分享页兜底获取失败: {last_error}")


def is_valid_media(content: bytes, kind: str) -> bool:
    """
    校验下载内容是否为有效媒体（避免把错误页/JSON 当成文件写入）

    Args:
        content: 响应体
        kind: ``image`` 或 ``video``

    Returns:
        有效返回 True
    """
    if not content:
        return False
    if kind == "image":
        return any(content.startswith(magic) for magic in IMAGE_MAGICS)
    # 视频：排除 JSON/HTML 错误响应，并要求有最小体积
    if content[:1] in (b"{", b"<"):
        return False
    return len(content) > 1024


async def download_aweme_media(
    aweme_data: Dict[str, Any],
    media: List[Dict[str, Any]],
    download_root: str,
    naming: str = DEFAULT_NAMING,
    file_progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """
    下载分享页解析出的媒体文件

    Args:
        aweme_data: ``build_aweme_data`` 的结果（提供 aweme_id / desc 用于命名）
        media: ``collect_media`` 的结果
        download_root: 下载根目录（如 ``Download``）
        naming: 命名模板，需与 F2 使用的模板一致
        file_progress_callback: 文件级进度回调 (percentage, current_file)

    Returns:
        下载结果字典（success / files / primary_file / media_type / message 等）
    """
    if not media:
        return {"success": False, "message": "分享页数据中没有可下载的图片或视频"}

    prefix = format_file_name(naming, aweme_data)
    target_dir = Path(download_root) / prefix
    target_dir.mkdir(parents=True, exist_ok=True)

    # desc 文件（与 F2 dl.py 的 download_desc 产物一致）
    desc_text = format_file_name("{desc}", aweme_data)
    if desc_text:
        (target_dir / f"{prefix}_desc.txt").write_text(desc_text, encoding="utf-8")

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    downloaded: List[str] = []
    failed: List[str] = []
    total = len(media)

    async with create_client({"User-Agent": MOBILE_UA}) as client:

        async def fetch_one(entry: Dict[str, Any]) -> Optional[str]:
            filename = f"{prefix}{entry['suffix']}"
            dest = target_dir / filename
            if dest.exists() and dest.stat().st_size > 0:
                return filename
            async with semaphore:
                last_error = ""
                for attempt in range(1, MAX_RETRIES + 1):
                    for url in entry["urls"]:
                        try:
                            response = await client.get(url)
                        except Exception as exc:  # noqa: BLE001 - 单地址失败换下一个
                            last_error = f"{type(exc).__name__}: {exc}"
                            continue
                        if response.status_code == 200 and is_valid_media(
                            response.content, entry["kind"]
                        ):
                            dest.write_bytes(response.content)
                            return filename
                        last_error = f"HTTP {response.status_code}"
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(attempt)
                logger.warning(f"[SHARE-PAGE] 下载失败: {filename} ({last_error})")
                return None

        tasks = [asyncio.create_task(fetch_one(entry)) for entry in media]
        done_count = 0
        for task in asyncio.as_completed(tasks):
            filename = await task
            done_count += 1
            if filename:
                downloaded.append(filename)
            else:
                failed.append(str(done_count))
            if file_progress_callback:
                percentage = int(done_count / total * 100)
                try:
                    file_progress_callback(percentage, filename or "")
                except Exception as exc:  # noqa: BLE001 - 回调异常不影响下载
                    logger.debug(f"[SHARE-PAGE] 进度回调异常: {exc}")

    media_type = media[0]["kind"] if len(media) == 1 else "images"
    success = bool(downloaded)
    message = f"分享页兜底下载完成: 成功 {len(downloaded)}, 失败 {len(failed)}"
    logger.info(f"[SHARE-PAGE] {message} -> {target_dir}")

    return {
        "success": success,
        "message": message,
        "download_path": str(download_root),
        "dir": str(target_dir),
        "prefix": prefix,
        "files": downloaded,
        "primary_file": downloaded[0] if downloaded else "",
        "media_type": media_type,
        "failed": failed,
    }
