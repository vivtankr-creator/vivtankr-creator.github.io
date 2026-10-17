"""
抖音视频下载器 Skill - Web API 服务

提供HTTP API接口供前端调用
基于FastAPI实现

启动命令:
    python -m skills.douyin_downloader.web --port 8080
    python skills/douyin_downloader/web.py --port 8080
"""

import sys
import asyncio
import argparse
import re
from typing import Any, Dict, Optional
from pathlib import Path
from datetime import datetime

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 直接导入，让Python显示真实的错误
from fastapi import (
    FastAPI,
    HTTPException,
    BackgroundTasks,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel, ValidationError, Field
from fastapi.exceptions import RequestValidationError
import uvicorn
import json

try:
    from .core import (
        DouyinDownloadSkill,
        clean_filename_for_display,
    )
    from .task_manager_v3 import (
        task_manager,
        TaskType,
        TaskStatus,
    )
except ImportError:
    from core import (
        DouyinDownloadSkill,
        clean_filename_for_display,
    )
    from task_manager_v3 import (
        task_manager,
        TaskType,
        TaskStatus,
    )

# 创建FastAPI应用
app = FastAPI(
    title="抖音视频下载器 API",
    description="基于F2框架的抖音视频下载服务",
    version="1.0.0",
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局Skill实例
skill: Optional[DouyinDownloadSkill] = None


async def _update_task_progress(task_id: str, percentage: int, message: str):
    """更新任务下载进度（中间状态）并广播"""
    try:
        await task_manager.update_task_progress(task_id, percentage, message)
    except Exception as e:
        print(f"[DY-WEB] 更新任务进度失败: {task_id[:8]}..., 错误: {e}")


async def _download_video_task(task_id: str, aweme_id: str, download_path: str):
    """后台下载视频任务"""
    try:
        if skill is None:
            print(f"[DY-WEB] Skill未初始化，无法下载")
            await task_manager.update_task_status(task_id, "failed", "Skill未初始化")
            return

        print(f"[DY-WEB] 开始后台下载任务: {task_id[:8]}..., aweme_id: {aweme_id}")

        # 更新任务状态为downloading
        await task_manager.update_task_status(task_id, "downloading")

        # 定义文件级进度回调（来自 F2 进度桥，显示字节级下载进度）
        def file_progress_callback(percentage: int, current_file: str):
            try:
                asyncio.create_task(
                    _update_task_progress(task_id, percentage, current_file)
                )
            except RuntimeError:
                pass  # 事件循环已关闭，忽略进度更新

        # 调用skill下载视频
        result = await skill.download_single_video(
            video_url=f"https://www.douyin.com/video/{aweme_id}",
            file_progress_callback=file_progress_callback,
        )

        # 更新任务结果
        if result.get("success"):
            # 更新视频信息和状态
            video_name = result.get("video_name", "") or result.get("original_desc", "")
            if video_name:
                # 更新数据库中的视频desc
                await task_manager.db.update_video_status(
                    task_id=task_id,
                    aweme_id=aweme_id,
                    status="downloaded",
                    file_path=result.get("file_name"),
                )
                # 更新视频desc（标题）
                await task_manager.db.execute(
                    "UPDATE task_videos SET desc = ? WHERE task_id = ? AND aweme_id = ?",
                    (video_name, task_id, aweme_id),
                )
                await task_manager.db.commit()
                print(f"[DY-WEB] 更新视频标题: {video_name[:50]}...")

            await task_manager.update_task_status(task_id, "completed")
            print(f"[DY-WEB] 下载成功: {task_id[:8]}...")
        else:
            await task_manager.update_task_status(
                task_id, "failed", result.get("message", "下载失败")
            )
            print(f"[DY-WEB] 下载失败: {task_id[:8]}...")

    except Exception as e:
        print(f"[DY-WEB] 下载任务异常: {task_id[:8]}..., 错误: {e}")
        await task_manager.update_task_status(task_id, "failed", str(e))


async def _download_mix_task(
    task_id: str,
    mix_id: str,
    mix_name: str,
    download_path: str,
    max_counts: Optional[int] = None,
    interval: str = "all",
):
    """后台下载合集任务"""
    try:
        if skill is None:
            print(f"[DY-WEB] Skill未初始化，无法下载合集")
            await task_manager.update_task_status(task_id, "failed", "Skill未初始化")
            return

        print(f"[DY-WEB] 开始后台下载合集任务: {task_id[:8]}..., mix_id: {mix_id}")

        # 更新任务状态为downloading
        await task_manager.update_task_status(task_id, "downloading")

        # 定义进度回调函数（同步函数，避免coroutine never awaited警告）
        def progress_callback(current: int, total: int, message: str):
            try:
                pct = int(current / max(total, 1) * 100)
                asyncio.create_task(_update_task_progress(task_id, pct, message))
            except RuntimeError:
                pass  # 事件循环已关闭，忽略进度更新

        # 定义文件级进度回调（来自 F2 进度桥，显示字节级下载进度）
        def file_progress_callback(percentage: int, current_file: str):
            try:
                asyncio.create_task(
                    _update_task_progress(task_id, percentage, current_file)
                )
            except RuntimeError:
                pass  # 事件循环已关闭，忽略进度更新

        # 调用skill下载合集
        result = await skill.download_mix_by_id(
            mix_id=mix_id,
            mix_name=mix_name,
            progress_callback=progress_callback,
            file_progress_callback=file_progress_callback,
            max_counts=max_counts,
            interval=interval,
        )

        # 更新任务结果
        if result.get("success"):
            await task_manager.update_task_status(task_id, "completed")
            print(
                f"[DY-WEB] 合集下载成功: {task_id[:8]}..., 下载{result.get('downloaded', 0)}个, 跳过{result.get('skipped', 0)}个"
            )
        else:
            await task_manager.update_task_status(
                task_id, "failed", result.get("message", "下载失败")
            )
            print(f"[DY-WEB] 合集下载失败: {task_id[:8]}...")

    except Exception as e:
        import traceback

        print(f"[DY-WEB] 合集下载任务异常: {task_id[:8]}..., 错误: {e}")
        print(traceback.format_exc())
        await task_manager.update_task_status(task_id, "failed", str(e))


# WebSocket连接管理器
class WebSocketManager:
    """管理WebSocket连接，处理任务状态广播"""

    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """接受新连接"""
        await websocket.accept()
        self.connections.append(websocket)
        print(f"[WebSocket] 新连接建立，当前连接数: {len(self.connections)}")

        # 发送当前所有任务
        result = await task_manager.get_tasks(limit=100)
        tasks = result.get("tasks", [])
        await websocket.send_json(
            {
                "type": "init",
                "data": {
                    "tasks": [task.to_dict() for task in tasks],
                    "total": result.get("total", 0),
                },
            }
        )

    def disconnect(self, websocket: WebSocket):
        """断开连接"""
        if websocket in self.connections:
            self.connections.remove(websocket)
            print(f"[WebSocket] 连接断开，当前连接数: {len(self.connections)}")

    async def broadcast(self, message: dict):
        """广播消息给所有连接"""
        disconnected = []
        for connection in self.connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"[WebSocket] 发送消息失败: {e}")
                disconnected.append(connection)

        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn)

    def on_task_status_change(self, task):
        """任务状态变更回调"""
        if self.connections:
            # 使用asyncio.create_task来异步广播
            message = {"type": "task_update", "data": task.to_dict()}
            asyncio.create_task(self.broadcast(message))


# 创建全局WebSocket管理器实例
ws_manager = WebSocketManager()


# 全局异常处理 - 捕获验证错误
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求验证错误，返回详细的错误信息"""
    errors = []
    for error in exc.errors():
        error_msg = {
            "field": error.get("loc", []),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        errors.append(error_msg)

    # 打印请求体以便调试
    body = await request.body()
    try:
        body_str = body.decode()
    except:
        body_str = str(body)

    print(f"[ERROR] Validation failed for {request.url}")
    print(f"[ERROR] Request body: {body_str}")
    print(f"[ERROR] Validation errors: {errors}")

    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "请求数据验证失败",
            "errors": errors,
            "request_body": body_str,
        },
    )


# 数据模型
class DownloadRequest(BaseModel):
    """下载请求模型"""

    url: str

    class Config:
        json_schema_extra = {"example": {"url": "https://v.douyin.com/xxxxx"}}


class DownloadMixRequest(BaseModel):
    """下载合集请求模型

    支持单个合集ID或批量合集ID（使用空格、逗号、换行、分号等分隔符）
    """

    mix_id: str
    mix_name: str = ""
    max_counts: Optional[int] = Field(
        None, description="最大下载数量，None表示全量下载"
    )
    interval: str = Field(
        "all", description="日期区间，格式如 '2024-01-01|2024-12-31' 或 'all'"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "mix_id": "123456, 789012",
                "mix_name": "合集名称",
                "max_counts": None,
                "interval": "all",
            }
        }


class RefreshCookieRequest(BaseModel):
    """刷新Cookie请求模型"""

    headless: bool = True

    class Config:
        json_schema_extra = {"example": {"headless": False}}


class ApiResponse(BaseModel):
    """API响应模型"""

    success: bool
    data: Optional[Dict[str, Any]] = None
    message: str = ""


@app.on_event("startup")
async def startup_event():
    """服务启动时初始化Skill"""
    global skill
    skill = DouyinDownloadSkill()
    print("[DY-WEB] DouyinDownloadSkill 初始化完成")

    # 初始化任务管理器
    await task_manager.initialize()
    print("[DY-WEB] TaskManager 初始化完成")

    # 注册WebSocket状态回调
    task_manager.register_status_callback(ws_manager.on_task_status_change)
    print("[DY-WEB] WebSocket状态回调已注册")


@app.on_event("shutdown")
async def shutdown_event():
    """服务关闭时清理"""
    # 注销WebSocket回调
    task_manager.unregister_status_callback(ws_manager.on_task_status_change)
    print("[DY-WEB] WebSocket状态回调已注销")

    # 关闭任务管理器
    await task_manager.shutdown()
    print("[DY-WEB] TaskManager 已关闭")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket端点 - 实时推送任务状态"""
    print("[WebSocket] 新的WebSocket连接")
    await websocket.accept()
    ws_manager.connections.append(websocket)
    print(f"[WebSocket] 连接已建立，当前连接数: {len(ws_manager.connections)}")

    try:
        # 发送初始任务列表
        result = await task_manager.get_tasks(limit=100)
        tasks = result["tasks"]
        total = result["total"]
        await websocket.send_json(
            {
                "type": "init",
                "data": {
                    "tasks": [task.to_dict() for task in tasks],
                    "total": total,
                },
            }
        )
        print("[WebSocket] 初始数据已发送")

        while True:
            # 使用超时接收消息，如果超时则继续循环（保持连接）
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)
                print(f"[WebSocket] 收到消息: {message.get('type')}")

                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "get_tasks":
                    result = await task_manager.get_tasks(limit=100)
                    tasks = result["tasks"]
                    total = result["total"]
                    await websocket.send_json(
                        {
                            "type": "init",
                            "data": {
                                "tasks": [task.to_dict() for task in tasks],
                                "total": total,
                            },
                        }
                    )
            except asyncio.TimeoutError:
                # 超时后继续循环，不发送额外消息
                print("[WebSocket] 等待消息超时，继续保持连接")
                continue
            except Exception as e:
                print(f"[WebSocket] 处理消息时出错: {e}")
                break

    except WebSocketDisconnect:
        print(f"[WebSocket] 客户端断开连接")
    except Exception as e:
        print(f"[WebSocket] 连接错误: {e}")
    finally:
        if websocket in ws_manager.connections:
            ws_manager.connections.remove(websocket)
        print(f"[WebSocket] 连接已关闭，剩余连接数: {len(ws_manager.connections)}")


@app.get("/")
async def root():
    """根路径 - 返回服务状态"""
    return {"service": "抖音视频下载器 API", "version": "1.0.0", "status": "running"}


@app.get("/api/status")
async def get_status():
    """获取服务状态"""
    return {"status": "ok", "skill_initialized": skill is not None}


@app.post("/api/download", response_model=ApiResponse)
async def download_video(request: DownloadRequest):
    """
    下载单个视频（异步任务模式）

    Args:
        request: 包含视频URL的请求

    Returns:
        创建的任务信息
    """
    print(f"[DEBUG] Download request received: {request}")
    if skill is None:
        raise HTTPException(status_code=503, detail="Skill未初始化")

    try:
        from f2.apps.douyin.utils import AwemeIdFetcher

        aweme_id = await AwemeIdFetcher.get_aweme_id(request.url)
        if not aweme_id:
            raise HTTPException(status_code=400, detail="无法从URL中提取视频ID")

        # 检查是否已存在该视频的任务（从数据库查询）
        print(f"[DY-WEB] 检查视频重复: aweme_id={aweme_id}")
        existing_result = await task_manager.get_tasks(
            status=None, task_type=TaskType.SINGLE, limit=100
        )
        existing_tasks = existing_result.get("tasks", [])

        existing_task = None
        for task in existing_tasks:
            task_aweme_id = task.video_info.get("aweme_id") if task.video_info else None
            if task_aweme_id == aweme_id:
                existing_task = task
                print(f"[DY-WEB] [OK] 找到重复任务: {task.video_name}")
                break

        if existing_task:
            # 如果任务已完成，提示用户已下载
            if existing_task.status == TaskStatus.COMPLETED.value:
                return ApiResponse(
                    success=True,
                    data={
                        "task_id": existing_task.id,
                        "status": existing_task.status,
                        "video_name": existing_task.video_name,
                        "is_duplicate": True,
                    },
                    message=f"该视频已下载过：{existing_task.video_name}",
                )
            # 如果任务还在进行中，直接返回现有任务
            elif existing_task.status in [
                TaskStatus.PENDING.value,
                TaskStatus.QUEUED.value,
                TaskStatus.DOWNLOADING.value,
            ]:
                return ApiResponse(
                    success=True,
                    data={
                        "task_id": existing_task.id,
                        "status": existing_task.status,
                        "video_name": existing_task.video_name,
                        "is_duplicate": True,
                    },
                    message=f"该视频已在下载队列中：{existing_task.video_name}",
                )

        # 获取下载路径
        download_path = (
            skill.douyin_conf.get("path", "Download") if skill else "Download"
        )

        # 预获取视频信息以设置正确的标题
        try:
            kwargs = skill._build_kwargs({"cookie": await skill.get_cookie()})
            handler = skill._get_handler(kwargs)
            video = await handler.fetch_one_video(aweme_id)
            video_data = video._to_dict()
            video_desc = video_data.get("desc", "")
            video_nickname = video_data.get("nickname", "")
            print(f"[DY-WEB] 预获取视频信息成功: {aweme_id}, desc={video_desc[:30]}...")
        except Exception as e:
            print(f"[DY-WEB] 预获取视频信息失败: {e}, 使用默认标题")
            video_desc = f"视频 {aweme_id}"
            video_nickname = ""

        # 使用新的V3接口创建任务（异步，保存视频信息到数据库）
        video_info = {
            "aweme_id": aweme_id,
            "desc": video_desc,
            "nickname": video_nickname,
        }

        task = await task_manager.create_single_task(
            aweme_id=aweme_id,
            video_info=video_info,
            download_path=download_path,
        )

        # 触发实际下载（后台异步执行）
        asyncio.create_task(
            _download_video_task(
                task_id=task.id,
                aweme_id=aweme_id,
                download_path=download_path,
            )
        )

        return ApiResponse(
            success=True,
            data={
                "task_id": task.id,
                "status": task.status,
                "message": "下载任务已创建",
            },
            message="下载任务已创建，请在任务列表中查看进度",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mix-info")
async def get_mix_info(request: DownloadRequest):
    """
    根据视频URL获取合集信息

    Args:
        request: 包含视频URL的请求

    Returns:
        合集信息
    """
    if skill is None:
        raise HTTPException(status_code=503, detail="Skill未初始化")

    try:
        result = await skill.get_mix_info_by_video_url(request.url)
        return ApiResponse(
            success=result.get("success", False),
            data=result,
            message=result.get("message", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download-mix", response_model=ApiResponse)
async def download_mix(request: DownloadMixRequest):
    """
    下载合集视频（异步任务模式）
    支持单个合集ID或批量合集ID（使用空格、逗号、换行、分号等分隔符）

    Args:
        request: 包含合集ID(s)和名称的请求

    Returns:
        创建的任务信息（单个或批量）
    """
    if skill is None:
        raise HTTPException(status_code=503, detail="Skill未初始化")

    try:
        import re

        # 解析多个合集ID
        mix_ids = re.split(r"[,;\s]+", request.mix_id.strip())
        mix_ids = [mid.strip() for mid in mix_ids if mid.strip()]

        if not mix_ids:
            raise HTTPException(status_code=400, detail="未解析到有效的合集ID")

        # 获取下载路径
        download_path = (
            skill.douyin_conf.get("path", "Download") if skill else "Download"
        )

        # 单个合集下载
        if len(mix_ids) == 1:
            mix_id = mix_ids[0]
            mix_name = request.mix_name or f"合集 {mix_id}"

            # 检查是否已存在该合集的任务（在下载中或队列中）
            print(f"[DY-WEB] 检查合集重复: mix_id={mix_id}")

            # 从数据库查询已存在的合集任务
            existing_result = await task_manager.get_tasks(
                status=None, task_type=TaskType.MIX, limit=100
            )
            existing_tasks = existing_result.get("tasks", [])

            existing_mix_task = None
            for task in existing_tasks:
                task_mix_id = task.video_info.get("mix_id") if task.video_info else None
                if task_mix_id == mix_id and task.status in [
                    TaskStatus.PENDING.value,
                    TaskStatus.QUEUED.value,
                    TaskStatus.DOWNLOADING.value,
                ]:
                    existing_mix_task = task
                    print(f"[DY-WEB] [OK] 找到进行中的合集任务: {task.video_name}")
                    break

            if existing_mix_task:
                # 如果合集任务还在进行中，提示用户
                return ApiResponse(
                    success=True,
                    data={
                        "task_id": existing_mix_task.id,
                        "status": existing_mix_task.status,
                        "video_name": existing_mix_task.video_name,
                        "is_duplicate": True,
                    },
                    message=f"该合集已在下载队列中：{existing_mix_task.video_name}",
                )

            # 创建合集任务（异步保存到数据库）
            print(f"[DY-WEB] 创建合集任务: mix_id={mix_id}, name={mix_name}")
            task = await task_manager.create_mix_task(
                mix_id=mix_id,
                mix_name=mix_name,
                videos=None,  # 先不获取视频列表，下载时再获取
                download_path=download_path,
                max_counts=request.max_counts,
                interval=request.interval,
            )

            # 启动后台下载任务
            asyncio.create_task(
                _download_mix_task(
                    task_id=task.id,
                    mix_id=mix_id,
                    mix_name=mix_name,
                    download_path=download_path,
                    max_counts=request.max_counts,
                    interval=request.interval,
                )
            )

            return ApiResponse(
                success=True,
                data={
                    "task_id": task.id,
                    "status": task.status,
                    "video_name": task.video_name,
                    "message": "合集下载任务已创建",
                },
                message=f"合集下载任务已创建：{task.video_name}",
            )

        # 批量合集下载
        else:
            print(f"[DY-WEB] 批量下载 {len(mix_ids)} 个合集")
            skipped_mixes = []
            created_tasks = []

            # 查询已存在的合集任务
            existing_result = await task_manager.get_tasks(
                status=None, task_type=TaskType.MIX, limit=100
            )
            existing_tasks = existing_result.get("tasks", [])

            for mix_id in mix_ids:
                mix_name = request.mix_name or f"合集 {mix_id}"

                # 检查是否已存在进行中的该合集任务
                is_existing = False
                for task in existing_tasks:
                    task_mix_id = (
                        task.video_info.get("mix_id") if task.video_info else None
                    )
                    if task_mix_id == mix_id and task.status in [
                        TaskStatus.PENDING.value,
                        TaskStatus.QUEUED.value,
                        TaskStatus.DOWNLOADING.value,
                    ]:
                        skipped_mixes.append({"mix_id": mix_id, "reason": "已在队列中"})
                        is_existing = True
                        break

                if is_existing:
                    continue

                # 创建合集任务
                task = await task_manager.create_mix_task(
                    mix_id=mix_id,
                    mix_name=mix_name,
                    videos=None,
                    download_path=download_path,
                    max_counts=request.max_counts,
                    interval=request.interval,
                )
                task = await task_manager.create_mix_task(
                    mix_id=mix_id,
                    mix_name=mix_name,
                    videos=None,
                    download_path=download_path,
                )
                created_tasks.append(task)

                # 启动后台下载任务
                asyncio.create_task(
                    _download_mix_task(
                        task_id=task.id,
                        mix_id=mix_id,
                        mix_name=mix_name,
                        download_path=download_path,
                        max_counts=request.max_counts,
                        interval=request.interval,
                    )
                )

            message_parts = []
            if created_tasks:
                message_parts.append(f"成功创建 {len(created_tasks)} 个下载任务")
            if skipped_mixes:
                message_parts.append(f"跳过 {len(skipped_mixes)} 个已在队列中的合集")

            return ApiResponse(
                success=True,
                data={
                    "task_ids": [t.id for t in created_tasks],
                    "tasks_count": len(created_tasks),
                    "skipped_count": len(skipped_mixes),
                    "skipped_mixes": skipped_mixes,
                },
                message="; ".join(message_parts)
                if message_parts
                else "批量下载任务已创建",
            )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        print(f"[DY-WEB] 下载合集错误: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cookie/refresh")
async def refresh_cookie(request: RefreshCookieRequest):
    """
    刷新Cookie

    Args:
        request: 包含headless设置的请求

    Returns:
        新的Cookie字符串
    """
    if skill is None:
        raise HTTPException(status_code=503, detail="Skill未初始化")

    try:
        cookie = await skill.refresh_cookie(headless=request.headless)
        return ApiResponse(
            success=True,
            data={"cookie": cookie[:50] + "..." if len(cookie) > 50 else cookie},
            message="Cookie刷新成功",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cookie/status")
async def check_cookie_status():
    """检查Cookie状态"""
    if skill is None:
        raise HTTPException(status_code=503, detail="Skill未初始化")

    try:
        try:
            from .cookie_manager import (
                load_local_cookie,
                is_cookie_logged_in,
            )
        except ImportError:
            from cookie_manager import (
                load_local_cookie,
                is_cookie_logged_in,
            )

        cookie = load_local_cookie()
        is_valid = is_cookie_logged_in(cookie) if cookie else False

        return ApiResponse(
            success=True,
            data={
                "exists": cookie is not None and len(cookie) > 0,
                "valid": is_valid,
                "length": len(cookie) if cookie else 0,
            },
            message="Cookie检查完成",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 任务管理 API ==========


class CreateTaskRequest(BaseModel):
    """创建任务请求"""

    type: str  # single, mix, mix_user
    url: Optional[str] = None
    mix_id: Optional[str] = None
    mix_name: Optional[str] = None
    user_url: Optional[str] = None
    max_counts: Optional[int] = Field(
        None, description="最大下载数量，None表示全量下载"
    )
    interval: str = Field(
        "all", description="日期区间，格式如 '2024-01-01|2024-12-31' 或 'all'"
    )


class TaskResponse(BaseModel):
    """任务响应"""

    success: bool
    data: Optional[Dict[str, Any]] = None
    message: str = ""


@app.get("/api/tasks", response_model=ApiResponse)
async def get_tasks(
    status: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    获取任务列表

    Args:
        status: 状态过滤 (pending, downloading, completed, failed, cancelled)
        type: 类型过滤 (single, mix, mix_user)
        limit: 返回数量限制
        offset: 偏移量
    """
    try:
        # 将字符串转换为枚举，再取value作为字符串传入
        task_status_enum = TaskStatus(status) if status else None
        task_type_enum = TaskType(type) if type else None

        # 提取字符串值用于get_tasks调用
        status_str = task_status_enum.value if task_status_enum else None

        print(
            f"[DY-WEB] 调用 get_tasks: status={status_str}, type={task_type_enum}, limit={limit}, offset={offset}"
        )
        result = await task_manager.get_tasks(
            status=status_str, task_type=task_type_enum, limit=limit, offset=offset
        )

        tasks = result.get("tasks", [])
        total = result.get("total", 0)
        print(f"[DY-WEB] 获取到 {len(tasks)} 个任务, 总计 {total}")

        # 调试：检查第一个任务的video_name
        if tasks:
            first_task = tasks[0]
            print(f"[DY-WEB] 返回任务列表，第一个任务: id={first_task.id[:8]}...")
            print(f"[DY-WEB] 第一个任务类型: {first_task.type}")
            print(f"[DY-WEB] 第一个任务状态: {first_task.status}")
            print(f"[DY-WEB] 第一个任务video_name: '{first_task.video_name}'")

        return ApiResponse(
            success=True,
            data={
                "tasks": [task.to_dict() for task in tasks],
                "total": total,
            },
            message="获取任务列表成功",
        )
    except ValueError as e:
        # 处理枚举转换错误
        print(f"[DY-WEB] 获取任务列表参数错误: {e}")
        return ApiResponse(
            success=False,
            data={"tasks": [], "total": 0},
            message=f"参数错误: {str(e)}",
        )
    except Exception as e:
        print(f"[DY-WEB] 获取任务列表失败: {e}")
        import traceback

        print(traceback.format_exc())
        return ApiResponse(
            success=False,
            data={"tasks": [], "total": 0},
            message=f"获取任务列表失败: {str(e)}",
        )


@app.get("/api/tasks/{task_id}", response_model=ApiResponse)
async def get_task(task_id: str):
    """获取单个任务详情"""
    try:
        task = await task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        return ApiResponse(
            success=True, data=task.to_dict(), message="获取任务详情成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tasks", response_model=ApiResponse)
async def create_task(request: CreateTaskRequest):
    """
    创建下载任务

    根据任务类型创建对应的下载任务：
    - single: 单视频下载，需要提供 url
    - mix: 合集下载，需要提供 mix_id 和可选的 mix_name
    - mix_user: 用户合集下载（暂未实现）
    """
    if skill is None:
        raise HTTPException(status_code=503, detail="Skill未初始化")

    try:
        task_type = TaskType(request.type)

        if task_type == TaskType.SINGLE_VIDEO:
            if not request.url:
                raise HTTPException(status_code=400, detail="单视频下载需要提供 url")

            # 获取视频信息
            print(f"[DY-WEB] 创建单视频下载任务: {request.url}")

            # 先获取视频基本信息用于创建任务
            import asyncio
            from f2.apps.douyin.utils import AwemeIdFetcher

            aweme_id = await AwemeIdFetcher.get_aweme_id(request.url)
            if not aweme_id:
                raise HTTPException(status_code=400, detail="无法从URL中提取视频ID")

            # 检查是否已存在该视频的任务
            # 从数据库查询已存在的任务
            existing_result = await task_manager.get_tasks(
                status=None, task_type=TaskType.SINGLE, limit=100
            )
            existing_tasks = existing_result.get("tasks", [])

            existing_task = None
            for task in existing_tasks:
                task_aweme_id = (
                    task.video_info.get("aweme_id") if task.video_info else None
                )
                if task_aweme_id == aweme_id:
                    existing_task = task
                    break

            if existing_task:
                # 如果任务已完成，提示用户已下载
                if existing_task.status == TaskStatus.COMPLETED.value:
                    return ApiResponse(
                        success=True,
                        data={
                            "task_id": existing_task.id,
                            "status": existing_task.status,
                            "video_name": existing_task.video_name,
                            "is_duplicate": True,
                        },
                        message=f"该视频已下载过：{existing_task.video_name}",
                    )
                # 如果任务还在进行中，直接返回现有任务
                elif existing_task.status in [
                    TaskStatus.PENDING.value,
                    TaskStatus.QUEUED.value,
                    TaskStatus.DOWNLOADING.value,
                ]:
                    return ApiResponse(
                        success=True,
                        data={
                            "task_id": existing_task.id,
                            "status": existing_task.status,
                            "video_name": existing_task.video_name,
                            "is_duplicate": True,
                        },
                        message=f"该视频已在下载队列中：{existing_task.video_name}",
                    )

            # 检查本地文件是否已存在
            if skill and hasattr(skill, "douyin_conf"):
                download_path = Path(skill.douyin_conf.get("path", "Download"))
                if download_path.exists():
                    pattern = re.compile(
                        rf"^{re.escape(aweme_id)}_.*\.mp4$", re.IGNORECASE
                    )
                    for f in download_path.rglob("*.mp4"):
                        if pattern.match(f.name):
                            return ApiResponse(
                                success=True,
                                data={
                                    "file_path": str(f),
                                    "video_name": f.name,
                                    "is_duplicate": True,
                                    "file_exists": True,
                                },
                                message=f"该视频文件已存在：{f.name}",
                            )

            # 获取下载路径
            download_path = (
                skill.douyin_conf.get("path", "Download") if skill else "Download"
            )

            # 创建任务（先不下载，由worker执行）
            task = task_manager.create_task(
                task_type=task_type,
                video_name=f"视频 {aweme_id}",  # 临时名称，下载时会更新
                file_name=f"{aweme_id}.mp4",
                original_desc="",
                video_info={"aweme_id": aweme_id},
                url=request.url,
                download_path=download_path,
            )

        elif task_type == TaskType.MIX_VIDEO:
            if not request.mix_id:
                raise HTTPException(status_code=400, detail="合集下载需要提供 mix_id")

            # 获取下载路径
            download_path = (
                skill.douyin_conf.get("path", "Download") if skill else "Download"
            )

            # 从数据库查询已存在的合集任务
            existing_result = await task_manager.get_tasks(
                status=None, task_type=TaskType.MIX, limit=100
            )
            existing_tasks = existing_result.get("tasks", [])

            existing_mix_task = None
            for task in existing_tasks:
                task_mix_id = task.video_info.get("mix_id") if task.video_info else None
                if task_mix_id == request.mix_id and task.status in [
                    TaskStatus.PENDING.value,
                    TaskStatus.QUEUED.value,
                    TaskStatus.DOWNLOADING.value,
                ]:
                    existing_mix_task = task
                    break

            if existing_mix_task:
                # 如果合集任务还在进行中，提示用户
                return ApiResponse(
                    success=True,
                    data={
                        "task_id": existing_mix_task.id,
                        "status": existing_mix_task.status,
                        "video_name": existing_mix_task.video_name,
                        "is_duplicate": True,
                    },
                    message=f"该合集已在下载队列中：{existing_mix_task.video_name}",
                )

            task = task_manager.create_task(
                task_type=task_type,
                video_name=request.mix_name or f"合集 {request.mix_id}",
                file_name=f"{request.mix_id}",
                original_desc="",
                video_info={"mix_id": request.mix_id},
                mix_id=request.mix_id,
                mix_name=request.mix_name,
                download_path=download_path,
                max_counts=request.max_counts,
                interval=request.interval,
            )

        else:
            raise HTTPException(
                status_code=400, detail=f"不支持的任务类型: {request.type}"
            )

        return ApiResponse(
            success=True,
            data={"task_id": task.id, "status": task.status},
            message="任务创建成功",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tasks/{task_id}/retry", response_model=ApiResponse)
async def retry_task(task_id: str):
    """重试失败或取消的任务"""
    try:
        task = await task_manager.retry_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在或无法重试")

        return ApiResponse(
            success=True,
            data={"task_id": task.id, "status": task.status},
            message="任务已添加到重试队列",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tasks/{task_id}/restart", response_model=ApiResponse)
async def restart_task(task_id: str):
    """重新执行已完成的任务（用于处理跳过的视频）"""
    try:
        task = await task_manager.restart_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在或无法重新执行")

        return ApiResponse(
            success=True,
            data={
                "task_id": task.id,
                "status": task.status,
                "prev_downloaded": task.result.get("prev_downloaded", 0),
                "prev_skipped": task.result.get("prev_skipped", 0),
            },
            message="任务已重新加入执行队列，将自动跳过已下载的视频",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/tasks/{task_id}", response_model=ApiResponse)
async def delete_task(task_id: str):
    """删除任务"""
    try:
        success = await task_manager.delete_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail="任务不存在")

        return ApiResponse(success=True, message="任务已删除")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tasks/{task_id}/cancel", response_model=ApiResponse)
async def cancel_task(task_id: str):
    """取消正在执行的任务"""
    try:
        success = await task_manager.cancel_task(task_id)
        if not success:
            raise HTTPException(status_code=400, detail="任务不存在或已完成，无法取消")

        return ApiResponse(success=True, message="任务已取消")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _download_user_posts_task(
    task_id: str,
    user_url: str,
    download_path: str,
    max_counts: Optional[int] = None,
    interval: str = "all",
):
    """后台下载用户作品任务"""
    try:
        if skill is None:
            print(f"[DY-WEB] Skill未初始化，无法下载用户作品")
            await task_manager.update_task_status(task_id, "failed", "Skill未初始化")
            return

        print(f"[DY-WEB] 开始后台下载用户作品任务: {task_id[:8]}..., url: {user_url}")

        # 更新任务状态为downloading
        await task_manager.update_task_status(task_id, "downloading")

        # 定义进度回调函数（作品级）
        def progress_callback(current: int, total: int, message: str):
            try:
                pct = int(current / max(total, 1) * 100)
                asyncio.create_task(_update_task_progress(task_id, pct, message))
            except RuntimeError:
                pass  # 事件循环已关闭，忽略进度更新

        # 定义文件级进度回调（来自 F2 进度桥，显示字节级下载进度）
        def file_progress_callback(percentage: int, current_file: str):
            try:
                asyncio.create_task(
                    _update_task_progress(task_id, percentage, current_file)
                )
            except RuntimeError:
                pass  # 事件循环已关闭，忽略进度更新

        # 调用skill下载用户作品
        result = await skill.download_user_posts(
            user_url=user_url,
            progress_callback=progress_callback,
            file_progress_callback=file_progress_callback,
            max_counts=max_counts,
            interval=interval,
        )

        # 更新任务结果
        if result.get("success"):
            # 保存视频信息到数据库
            videos = result.get("videos", [])
            if videos:
                try:
                    from db import TaskVideoInfo

                    for video in videos:
                        await task_manager.db.add_video(
                            TaskVideoInfo(
                                id=0,
                                task_id=task_id,
                                aweme_id=video["aweme_id"],
                                desc=video["desc"],
                                nickname=video["nickname"],
                                sec_user_id=video.get("sec_user_id"),
                                create_time=video.get(
                                    "create_time", datetime.now().isoformat()
                                ),
                                status=video.get("status", "downloaded"),
                                file_path=None,
                                file_size=None,
                                error_message=None,
                                download_time=None,
                            )
                        )
                    print(f"[DY-WEB] 已保存 {len(videos)} 个视频信息到数据库")
                except Exception as e:
                    print(f"[DY-WEB] 保存视频信息失败: {e}")

            await task_manager.update_task_status(task_id, "completed")
            print(
                f"[DY-WEB] 用户作品下载成功: {task_id[:8]}..., 下载{result.get('downloaded', 0)}个, 跳过{result.get('skipped', 0)}个"
            )
        else:
            await task_manager.update_task_status(
                task_id, "failed", result.get("message", "下载失败")
            )
            print(f"[DY-WEB] 用户作品下载失败: {task_id[:8]}...")

    except Exception as e:
        import traceback

        print(f"[DY-WEB] 用户作品下载任务异常: {task_id[:8]}..., 错误: {e}")
        print(traceback.format_exc())
        await task_manager.update_task_status(task_id, "failed", str(e))


class DownloadUserPostsRequest(BaseModel):
    """下载用户作品请求模型"""

    user_url: str = Field(..., description="用户主页链接")
    max_counts: Optional[int] = Field(
        None, description="最大下载数量，None表示全量下载"
    )
    interval: str = Field(
        "all", description="日期区间，格式如 '2024-01-01|2024-12-31' 或 'all'"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_url": "https://www.douyin.com/user/xxxxx",
                "max_counts": None,
                "interval": "all",
            }
        }


@app.post("/api/download-user-posts", response_model=ApiResponse)
async def download_user_posts(request: DownloadUserPostsRequest):
    """
    下载用户主页作品（异步任务模式）

    Args:
        request: 包含用户主页URL和下载选项的请求

    Returns:
        创建的任务信息
    """
    if skill is None:
        raise HTTPException(status_code=503, detail="Skill未初始化")

    try:
        from f2.apps.douyin.utils import SecUserIdFetcher

        # 从URL提取sec_user_id用于检查重复
        sec_user_id = await SecUserIdFetcher.get_sec_user_id(request.user_url)
        if not sec_user_id:
            raise HTTPException(status_code=400, detail="无法从URL中提取用户ID")

        # 获取用户信息
        kwargs = skill._build_kwargs({"cookie": await skill.get_cookie()})
        handler = skill._get_handler(kwargs)
        user_profile = await handler.fetch_user_profile(sec_user_id)
        user_nickname = user_profile.nickname

        # 检查是否已存在该用户的作品下载任务（在下载中或队列中）
        print(f"[DY-WEB] 检查用户作品任务重复: sec_user_id={sec_user_id}")

        # 从数据库查询已存在的用户作品任务
        existing_result = await task_manager.get_tasks(
            status=None, task_type=TaskType.POST, limit=100
        )
        existing_tasks = existing_result.get("tasks", [])

        existing_post_task = None
        for task in existing_tasks:
            task_sec_user_id = (
                task.video_info.get("sec_user_id") if task.video_info else None
            )
            if task_sec_user_id == sec_user_id and task.status in [
                TaskStatus.PENDING.value,
                TaskStatus.QUEUED.value,
                TaskStatus.DOWNLOADING.value,
            ]:
                existing_post_task = task
                print(f"[DY-WEB] [OK] 找到进行中的用户作品任务: {task.video_name}")
                break

        if existing_post_task:
            # 如果任务还在进行中，提示用户
            return ApiResponse(
                success=True,
                data={
                    "task_id": existing_post_task.id,
                    "status": existing_post_task.status,
                    "video_name": existing_post_task.video_name,
                    "is_duplicate": True,
                },
                message=f"该用户的作品下载已在队列中：{existing_post_task.video_name}",
            )

        # 获取下载路径
        download_path = (
            skill.douyin_conf.get("path", "Download") if skill else "Download"
        )

        # 创建用户作品下载任务（异步保存到数据库）
        print(
            f"[DY-WEB] 创建用户作品任务: sec_user_id={sec_user_id}, name={user_nickname}"
        )
        task = await task_manager.create_post_task(
            sec_user_id=sec_user_id,
            user_name=user_nickname,
            user_url=request.user_url,
            max_counts=request.max_counts,
            interval=request.interval,
            download_path=download_path,
        )

        # 启动后台下载任务
        asyncio.create_task(
            _download_user_posts_task(
                task_id=task.id,
                user_url=request.user_url,
                download_path=download_path,
                max_counts=request.max_counts,
                interval=request.interval,
            )
        )

        return ApiResponse(
            success=True,
            data={
                "task_id": task.id,
                "status": task.status,
                "video_name": task.video_name,
                "message": "用户作品下载任务已创建",
            },
            message=f"用户作品下载任务已创建：{task.video_name}",
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        print(f"[DY-WEB] 下载用户作品错误: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# 前端静态文件服务
frontend_path = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_path.exists():
    # 挂载 /assets 路径提供静态资源
    app.mount(
        "/assets", StaticFiles(directory=str(frontend_path / "assets")), name="assets"
    )
    # 挂载 /app 路径提供前端应用（html=true 支持前端路由）
    app.mount(
        "/app", StaticFiles(directory=str(frontend_path), html=True), name="frontend"
    )


@app.get("/api/download/file/{filename}")
async def download_file(
    filename: str, subpath: Optional[str] = None, aweme_id: Optional[str] = None
):
    """
    下载已下载的视频文件

    Args:
        filename: 文件名
        subpath: 子目录路径（可选）
        aweme_id: 视频ID（可选，用于智能查找文件）

    Returns:
        文件下载响应
    """
    if skill is None:
        raise HTTPException(status_code=503, detail="Skill未初始化")

    try:
        # 获取下载根目录
        download_root = Path(skill.douyin_conf.get("path", "Download"))

        if not download_root.exists():
            raise HTTPException(status_code=404, detail="下载目录不存在")

        # 构建完整路径
        if subpath:
            file_path = download_root / subpath / filename
        else:
            file_path = download_root / filename

        # 安全检查：确保文件路径在下载目录内
        try:
            file_path.resolve().relative_to(download_root.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="非法的文件路径")

        # 如果直接路径不存在，尝试在目录中搜索文件
        # 媒体文件后缀（视频+图文图片）
        MEDIA_EXTS = [".mp4", ".mov", ".avi", ".mkv", ".flv", ".webp", ".jpeg", ".jpg", ".png", ".avif"]

        if not file_path.exists():
            # 1. 先尝试在指定子目录下搜索
            if subpath:
                search_dir = download_root / subpath
                if search_dir.exists():
                    for ext in MEDIA_EXTS:
                        pattern = f"*{filename}*{ext}"
                        found_files = list(search_dir.glob(pattern))
                        if found_files:
                            file_path = found_files[0]
                            break

            # 2. 如果还是没找到，在整个下载目录中递归搜索
            if not file_path.exists() and aweme_id:
                # 根据 aweme_id 搜索
                for ext in MEDIA_EXTS:
                    pattern = f"**/{aweme_id}*{ext}"
                    found_files = list(download_root.glob(pattern))
                    if found_files:
                        file_path = found_files[0]
                        break

            # 3. 最后尝试按文件名搜索
            if not file_path.exists():
                for ext in MEDIA_EXTS:
                    pattern = f"**/{filename}"
                    if not filename.endswith(ext):
                        pattern = f"**/{filename}*{ext}"
                    found_files = list(download_root.glob(pattern))
                    if found_files:
                        file_path = found_files[0]
                        break

        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")

        if not file_path.is_file():
            raise HTTPException(status_code=400, detail="不是有效的文件")

        # 按扩展名返回正确的媒体类型
        media_types = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".flv": "video/x-flv",
            ".webp": "image/webp",
            ".jpeg": "image/jpeg",
            ".jpg": "image/jpeg",
            ".png": "image/png",
        }
        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type=media_types.get(file_path.suffix.lower(), "application/octet-stream"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="抖音视频下载器 Web 服务")
    parser.add_argument("--port", type=int, default=8080, help="服务端口")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="服务地址")
    args = parser.parse_args()

    print(f"[DY-WEB] 启动服务: http://{args.host}:{args.port}")
    print(f"[DY-WEB] API文档: http://{args.host}:{args.port}/docs")
    uvicorn.run(app, host=args.host, port=args.port)
