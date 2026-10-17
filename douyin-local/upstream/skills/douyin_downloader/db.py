"""
数据库管理器 - 参考F2项目设计

使用异步SQLite操作，支持任务和视频信息的完整存储
"""

import aiosqlite
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class TaskInfo:
    """任务信息"""

    task_id: str
    type: str  # 'single' | 'mix' | 'mix_user'
    mix_id: Optional[str]
    mix_name: Optional[str]
    status: str  # 'pending' | 'downloading' | 'completed' | 'failed' | 'cancelled'
    base_path: Optional[str]
    total_count: int = 0
    downloaded_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    download_options: Optional[str] = None  # JSON格式字符串
    progress_percentage: Optional[int] = None  # 下载中间进度百分比
    current_video_name: Optional[str] = None  # 下载中的当前文件名

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "type": self.type,
            "mix_id": self.mix_id,
            "mix_name": self.mix_name,
            "status": self.status,
            "base_path": self.base_path,
            "total_count": self.total_count,
            "downloaded_count": self.downloaded_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "download_options": self.download_options,
            "progress_percentage": self.progress_percentage,
            "current_video_name": self.current_video_name,
        }


@dataclass
class TaskVideoInfo:
    """任务中的视频信息 - 参考F2的video_info表设计"""

    id: int
    task_id: str
    aweme_id: str
    desc: str
    nickname: str
    sec_user_id: Optional[str]
    create_time: str
    status: str  # 'pending' | 'downloaded' | 'skipped' | 'failed'
    file_path: Optional[str]
    file_size: Optional[int]
    error_message: Optional[str]
    download_time: Optional[str]
    # 扩展字段，参考F2设计
    video_play_addr: Optional[str] = None
    cover: Optional[str] = None
    duration: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "aweme_id": self.aweme_id,
            "desc": self.desc,
            "nickname": self.nickname,
            "sec_user_id": self.sec_user_id,
            "create_time": self.create_time,
            "status": self.status,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "error_message": self.error_message,
            "download_time": self.download_time,
            "video_play_addr": self.video_play_addr,
            "cover": self.cover,
            "duration": self.duration,
        }


class TaskDB:
    """
    任务数据库管理器 - 参考F2 BaseDB设计

    使用异步SQLite存储，支持完整的任务和视频信息管理
    """

    def __init__(self, db_path: str = "./douyin_downloader.db"):
        self.db_path = db_path
        self.conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """连接到数据库"""
        self.conn = await aiosqlite.connect(self.db_path)
        await self._create_tables()

    async def close(self) -> None:
        """关闭数据库连接"""
        conn = self.conn
        self.conn = None
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass

    async def _create_tables(self) -> None:
        """创建数据库表"""
        # 任务表 - 简化版，参考F2设计
        await self.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                mix_id TEXT,
                mix_name TEXT,
                status TEXT DEFAULT 'pending',
                base_path TEXT,
                total_count INTEGER DEFAULT 0,
                downloaded_count INTEGER DEFAULT 0,
                skipped_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TEXT,
                completed_at TEXT,
                download_options TEXT  -- JSON格式存储下载选项(max_counts, interval等)
            )
        """)

        # 视频表 - 参考F2的video_info表设计，添加task_id关联
        await self.execute("""
            CREATE TABLE IF NOT EXISTS task_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                aweme_id TEXT NOT NULL,
                desc TEXT,
                nickname TEXT,
                sec_user_id TEXT,
                create_time TEXT,
                status TEXT DEFAULT 'pending',
                file_path TEXT,
                file_size INTEGER,
                error_message TEXT,
                download_time TEXT,
                video_play_addr TEXT,
                cover TEXT,
                duration TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id),
                UNIQUE(task_id, aweme_id)
            )
        """)

        # 创建索引
        await self.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_videos_task_id 
            ON task_videos(task_id)
        """)
        await self.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_videos_aweme_id 
            ON task_videos(aweme_id)
        """)
        await self.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status 
            ON tasks(status)
        """)

        await self.commit()

        # 执行数据库迁移
        await self._migrate_database()

    async def _migrate_database(self) -> None:
        """数据库迁移 - 添加新字段"""
        # 检查是否需要添加 download_options 字段
        try:
            await self.execute("SELECT download_options FROM tasks LIMIT 1")
        except Exception:
            # 字段不存在，添加它
            print("[DB] Migrating: adding download_options column to tasks table")
            await self.execute("ALTER TABLE tasks ADD COLUMN download_options TEXT")
            await self.commit()
            print("[DB] Migration completed")

        # 检查是否需要添加 progress_percentage 字段（下载中间进度）
        try:
            await self.execute("SELECT progress_percentage FROM tasks LIMIT 1")
        except Exception:
            print("[DB] Migrating: adding progress_percentage column to tasks table")
            await self.execute(
                "ALTER TABLE tasks ADD COLUMN progress_percentage INTEGER"
            )
            await self.commit()
            print("[DB] Migration completed")

        # 检查是否需要添加 current_video_name 字段（下载中的当前文件）
        try:
            await self.execute("SELECT current_video_name FROM tasks LIMIT 1")
        except Exception:
            print("[DB] Migrating: adding current_video_name column to tasks table")
            await self.execute(
                "ALTER TABLE tasks ADD COLUMN current_video_name TEXT"
            )
            await self.commit()
            print("[DB] Migration completed")

    async def execute(self, sql: str, parameters: tuple = ()) -> aiosqlite.Cursor:
        """执行SQL语句"""
        if not self.conn:
            await self.connect()
        return await self.conn.execute(sql, parameters)

    async def commit(self) -> None:
        """提交事务"""
        if self.conn:
            await self.conn.commit()

    async def fetch_one(self, sql: str, parameters: tuple = ()) -> Optional[tuple]:
        """获取单条记录"""
        cursor = await self.execute(sql, parameters)
        return await cursor.fetchone()

    async def fetch_all(self, sql: str, parameters: tuple = ()) -> List[tuple]:
        """获取多条记录"""
        cursor = await self.execute(sql, parameters)
        return await cursor.fetchall()

    # ==================== 任务操作 ====================

    async def create_task(
        self,
        task_type: str,
        mix_id: Optional[str] = None,
        mix_name: Optional[str] = None,
        base_path: Optional[str] = None,
        download_options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        创建新任务

        Returns:
            task_id: 任务ID
        """
        import uuid
        import json

        task_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()
        download_options_json = json.dumps(download_options) if download_options else None

        await self.execute(
            """
            INSERT INTO tasks (task_id, type, mix_id, mix_name, status, base_path, created_at, download_options)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (task_id, task_type, mix_id, mix_name, base_path, created_at, download_options_json),
        )
        await self.commit()
        return task_id

    async def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务信息"""
        row = await self.fetch_one("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        if row:
            return TaskInfo(
                task_id=row[0],
                type=row[1],
                mix_id=row[2],
                mix_name=row[3],
                status=row[4],
                base_path=row[5],
                total_count=row[6] or 0,
                downloaded_count=row[7] or 0,
                skipped_count=row[8] or 0,
                failed_count=row[9] or 0,
                error_message=row[10],
                created_at=row[11],
                completed_at=row[12],
                download_options=row[13] if len(row) > 13 else None,
                progress_percentage=row[14] if len(row) > 14 else None,
                current_video_name=row[15] if len(row) > 15 else None,
            )
        return None

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """更新任务状态"""
        if status in ["completed", "failed"]:
            completed_at = datetime.now().isoformat()
            await self.execute(
                """
                UPDATE tasks SET status=?, error_message=?, completed_at=?
                WHERE task_id=?
                """,
                (status, error_message, completed_at, task_id),
            )
        else:
            await self.execute(
                "UPDATE tasks SET status=?, error_message=? WHERE task_id=?",
                (status, error_message, task_id),
            )
        await self.commit()

    async def update_task_counts(
        self,
        task_id: str,
        total: Optional[int] = None,
        downloaded: Optional[int] = None,
        skipped: Optional[int] = None,
        failed: Optional[int] = None,
    ) -> None:
        """更新任务计数"""
        updates = []
        params = []
        if total is not None:
            updates.append("total_count=?")
            params.append(total)
        if downloaded is not None:
            updates.append("downloaded_count=?")
            params.append(downloaded)
        if skipped is not None:
            updates.append("skipped_count=?")
            params.append(skipped)
        if failed is not None:
            updates.append("failed_count=?")
            params.append(failed)

        if updates:
            sql = f"UPDATE tasks SET {', '.join(updates)} WHERE task_id=?"
            params.append(task_id)
            await self.execute(sql, tuple(params))
            await self.commit()

    async def update_task_progress(
        self,
        task_id: str,
        percentage: Optional[int] = None,
        current_video_name: Optional[str] = None,
    ) -> None:
        """更新任务下载进度（中间状态）"""
        updates = []
        params = []
        if percentage is not None:
            updates.append("progress_percentage=?")
            params.append(percentage)
        if current_video_name is not None:
            updates.append("current_video_name=?")
            params.append(current_video_name)

        if updates:
            sql = f"UPDATE tasks SET {', '.join(updates)} WHERE task_id=?"
            params.append(task_id)
            await self.execute(sql, tuple(params))
            await self.commit()

    async def get_tasks(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TaskInfo]:
        """获取任务列表"""
        if status:
            rows = await self.fetch_all(
                "SELECT * FROM tasks WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            rows = await self.fetch_all(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )

        return [
            TaskInfo(
                task_id=row[0],
                type=row[1],
                mix_id=row[2],
                mix_name=row[3],
                status=row[4],
                base_path=row[5],
                total_count=row[6] or 0,
                downloaded_count=row[7] or 0,
                skipped_count=row[8] or 0,
                failed_count=row[9] or 0,
                error_message=row[10],
                created_at=row[11],
                completed_at=row[12],
                download_options=row[13] if len(row) > 13 else None,
                progress_percentage=row[14] if len(row) > 14 else None,
                current_video_name=row[15] if len(row) > 15 else None,
            )
            for row in rows
        ]

    async def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        # 先删除关联的视频记录
        await self.execute("DELETE FROM task_videos WHERE task_id=?", (task_id,))
        # 再删除任务
        await self.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
        await self.commit()
        return True

    # ==================== 视频操作 ====================

    async def add_video(self, video_info: TaskVideoInfo) -> int:
        """
        添加视频信息 - 参考F2的add_video_info设计

        Returns:
            video_id: 视频记录ID
        """
        await self.execute(
            """
            INSERT OR REPLACE INTO task_videos 
            (task_id, aweme_id, desc, nickname, sec_user_id,
             create_time, status, file_path, file_size, error_message, download_time,
             video_play_addr, cover, duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_info.task_id,
                video_info.aweme_id,
                video_info.desc,
                video_info.nickname,
                video_info.sec_user_id,
                video_info.create_time,
                video_info.status,
                video_info.file_path,
                video_info.file_size,
                video_info.error_message,
                video_info.download_time,
                video_info.video_play_addr,
                video_info.cover,
                video_info.duration,
            ),
        )
        await self.commit()

        # 获取最后插入的ID
        cursor = await self.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def add_videos_batch(self, videos: List[TaskVideoInfo]) -> None:
        """批量添加视频信息"""
        for video in videos:
            await self.add_video(video)

    async def get_task_videos(
        self, task_id: str, status: Optional[str] = None
    ) -> List[TaskVideoInfo]:
        """获取任务的所有视频，可选按状态过滤"""
        if status:
            rows = await self.fetch_all(
                "SELECT * FROM task_videos WHERE task_id=? AND status=? ORDER BY create_time",
                (task_id, status),
            )
        else:
            rows = await self.fetch_all(
                "SELECT * FROM task_videos WHERE task_id=? ORDER BY create_time",
                (task_id,),
            )
        videos = []
        for row in rows:
            # 兼容旧表结构（列数可能不足）
            row_len = len(row)
            videos.append(
                TaskVideoInfo(
                    id=row[0] if row_len > 0 else 0,
                    task_id=row[1] if row_len > 1 else task_id,
                    aweme_id=row[2] if row_len > 2 else "",
                    desc=row[3] if row_len > 3 else "",
                    nickname=row[4] if row_len > 4 else "",
                    sec_user_id=row[5] if row_len > 5 else None,
                    create_time=row[6] if row_len > 6 else datetime.now().isoformat(),
                    status=row[7] if row_len > 7 else "pending",
                    file_path=row[8] if row_len > 8 else None,
                    file_size=row[9] if row_len > 9 else None,
                    error_message=row[10] if row_len > 10 else None,
                    download_time=row[11] if row_len > 11 else None,
                    video_play_addr=row[12] if row_len > 12 else None,
                    cover=row[13] if row_len > 13 else None,
                    duration=row[14] if row_len > 14 else None,
                )
            )
        return videos

    async def update_video_status(
        self,
        task_id: str,
        aweme_id: str,
        status: str,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """更新视频状态"""
        download_time = datetime.now().isoformat() if status == "downloaded" else None

        await self.execute(
            """
            UPDATE task_videos 
            SET status=?, file_path=?, file_size=?, error_message=?, download_time=?
            WHERE task_id=? AND aweme_id=?
            """,
            (
                status,
                file_path,
                file_size,
                error_message,
                download_time,
                task_id,
                aweme_id,
            ),
        )
        await self.commit()

    # ==================== 统计和清理 ====================

    async def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = await self.fetch_one("SELECT COUNT(*) FROM tasks")
        pending = await self.fetch_one(
            "SELECT COUNT(*) FROM tasks WHERE status='pending'"
        )
        downloading = await self.fetch_one(
            "SELECT COUNT(*) FROM tasks WHERE status='downloading'"
        )
        completed = await self.fetch_one(
            "SELECT COUNT(*) FROM tasks WHERE status='completed'"
        )
        failed = await self.fetch_one(
            "SELECT COUNT(*) FROM tasks WHERE status='failed'"
        )

        return {
            "total": total[0] if total else 0,
            "pending": pending[0] if pending else 0,
            "downloading": downloading[0] if downloading else 0,
            "completed": completed[0] if completed else 0,
            "failed": failed[0] if failed else 0,
        }

    async def cleanup_old_tasks(self, days: int = 30) -> int:
        """清理旧任务"""
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        # 获取要删除的任务ID
        rows = await self.fetch_all(
            """
            SELECT task_id FROM tasks 
            WHERE (status='completed' OR status='failed') 
            AND created_at < datetime(?, 'unixepoch')
            """,
            (cutoff,),
        )

        count = len(rows)
        for row in rows:
            await self.delete_task(row[0])

        return count

    async def export_task_metadata(self, task_id: str) -> Dict[str, Any]:
        """导出任务元数据"""
        task = await self.get_task(task_id)
        if not task:
            return {}

        videos = await self.get_task_videos(task_id)

        return {
            "task": task.to_dict(),
            "videos": [v.to_dict() for v in videos],
            "export_time": datetime.now().isoformat(),
        }

    # 上下文管理器支持
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
