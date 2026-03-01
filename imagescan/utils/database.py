"""
数据库模块

用途：
1. SQLite 数据库初始化
2. 表创建和数据库连接管理
3. CRUD 操作
4. 事务支持

参考：docs/BACKEND_STRUCTURE.md
"""

import aiosqlite
import sqlite3
from pathlib import Path
from typing import List, Optional, Any, Dict
from contextlib import asynccontextmanager

from ..utils.logger import get_logger
from ..utils.config import get_config

logger = get_logger(__name__)


class Database:
    """
    数据库管理类

    提供数据库初始化、连接管理和基本 CRUD 操作
    """

    def __init__(self, db_path: str):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._connection_pool: Optional[aiosqlite.Connection] = None

    async def init(self):
        """
        初始化数据库

        - 创建数据库文件（如果不存在）
        - 启用外键约束
        - 创建所有表
        - 创建索引

        Raises:
            Exception: 初始化失败
        """
        # 确保数据库目录存在
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        logger.info("初始化数据库", path=self.db_path)

        try:
            # 使用同步连接创建表（aiosqlite 不支持 DDL）
            await self._create_tables()
            logger.info("数据库初始化成功")
        except Exception as e:
            logger.error("数据库初始化失败", error=str(e))
            raise

    async def _create_tables(self):
        """创建所有表"""
        # 创建同步连接用于 DDL 操作
        async with aiosqlite.connect(self.db_path) as db:
            # 启用外键约束
            await db.execute("PRAGMA foreign_keys = ON")
            logger.debug("外键约束已启用")

            # 创建 scan_tasks 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scan_tasks (
                    task_id TEXT PRIMARY KEY,
                    image_name TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    total_layers INTEGER NOT NULL DEFAULT 0,
                    processed_layers INTEGER NOT NULL DEFAULT 0,
                    total_files INTEGER NOT NULL DEFAULT 0,
                    processed_files INTEGER NOT NULL DEFAULT 0,
                    credentials_found INTEGER NOT NULL DEFAULT 0
                )
            """)
            logger.debug("scan_tasks 表已创建")

            # 创建 credentials 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS credentials (
                    credential_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    cred_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    file_path TEXT NOT NULL,
                    line_number INTEGER,
                    layer_id TEXT NOT NULL,
                    context TEXT NOT NULL,
                    raw_value TEXT,
                    validation_status TEXT NOT NULL,
                    verified_at TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (task_id) REFERENCES scan_tasks(task_id) ON DELETE CASCADE
                )
            """)
            logger.debug("credentials 表已创建")

            # 创建 scan_layers 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scan_layers (
                    task_id TEXT NOT NULL,
                    layer_id TEXT NOT NULL,
                    layer_index INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    file_count INTEGER NOT NULL,
                    sensitive_files INTEGER NOT NULL DEFAULT 0,
                    credentials_found INTEGER NOT NULL DEFAULT 0,
                    processed BOOLEAN NOT NULL DEFAULT FALSE,
                    PRIMARY KEY (task_id, layer_id),
                    FOREIGN KEY (task_id) REFERENCES scan_tasks(task_id) ON DELETE CASCADE
                )
            """)
            logger.debug("scan_layers 表已创建")

            # 创建 scan_metadata 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scan_metadata (
                    task_id TEXT PRIMARY KEY,
                    image_name TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    scanner_version TEXT NOT NULL,
                    scan_duration_seconds REAL NOT NULL,
                    total_size_bytes INTEGER NOT NULL,
                    layers_scanned INTEGER NOT NULL,
                    files_scanned INTEGER NOT NULL,
                    credentials_found INTEGER NOT NULL,
                    false_positive_count INTEGER NOT NULL DEFAULT 0,
                    statistics TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES scan_tasks(task_id) ON DELETE CASCADE
                )
            """)
            logger.debug("scan_metadata 表已创建")

            # 创建索引
            await self._create_indexes(db)
            logger.debug("索引已创建")

            await db.commit()

    async def _create_indexes(self, db: aiosqlite.Connection):
        """创建索引"""
        # credentials 表索引
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_credentials_task_id
            ON credentials(task_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_credentials_type
            ON credentials(cred_type)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_credentials_confidence
            ON credentials(confidence)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_credentials_layer_id
            ON credentials(layer_id)
        """)

        # scan_layers 表索引
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_layers_task_id
            ON scan_layers(task_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_layers_processed
            ON scan_layers(processed)
        """)

    @asynccontextmanager
    async def get_connection(self):
        """
        获取数据库连接（上下文管理器）

        用法:
            async with db.get_connection() as conn:
                await conn.execute(...)

        Returns:
            数据库连接
        """
        async with aiosqlite.connect(self.db_path) as conn:
            # 启用外键约束
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    # ==================== scan_tasks 表操作 ====================

    async def insert_task(self, task_data: Dict[str, Any]) -> str:
        """
        插入扫描任务

        Args:
            task_data: 任务数据字典

        Returns:
            task_id: 任务 ID
        """
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO scan_tasks (
                    task_id, image_name, image_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_data["task_id"],
                    task_data["image_name"],
                    task_data["image_id"],
                    task_data["status"],
                    task_data["created_at"].isoformat()
                )
            )
            await db.commit()
            logger.debug("任务已插入", task_id=task_data["task_id"])
            return task_data["task_id"]

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        **kwargs
    ) -> bool:
        """
        更新任务状态

        Args:
            task_id: 任务 ID
            status: 新状态
            **kwargs: 其他更新字段

        Returns:
            是否成功
        """
        async with self.get_connection() as db:
            updates = ["status = ?"]
            values = [status]

            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(value)

            values.append(task_id)

            await db.execute(
                f"UPDATE scan_tasks SET {', '.join(updates)} WHERE task_id = ?",
                values
            )
            await db.commit()
            logger.debug("任务状态已更新", task_id=task_id, status=status)
            return True

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务信息

        Args:
            task_id: 任务 ID

        Returns:
            任务数据或 None
        """
        async with self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM scan_tasks WHERE task_id = ?",
                (task_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    # ==================== credentials 表操作 ====================

    async def insert_credential(self, cred_data: Dict[str, Any]) -> str:
        """
        插入凭证

        Args:
            cred_data: 凭证数据字典

        Returns:
            credential_id: 凭证 ID
        """
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO credentials (
                    credential_id, task_id, cred_type, confidence,
                    file_path, line_number, layer_id, context,
                    validation_status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cred_data["credential_id"],
                    cred_data["task_id"],
                    cred_data["cred_type"],
                    cred_data["confidence"],
                    cred_data["file_path"],
                    cred_data.get("line_number"),
                    cred_data["layer_id"],
                    cred_data["context"],
                    cred_data["validation_status"],
                    str(cred_data.get("metadata", {}))
                )
            )
            await db.commit()
            logger.debug("凭证已插入", credential_id=cred_data["credential_id"])
            return cred_data["credential_id"]

    async def get_credentials_by_task(self, task_id: str) -> List[Dict[str, Any]]:
        """
        获取任务的所有凭证

        Args:
            task_id: 任务 ID

        Returns:
            凭证列表
        """
        async with self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM credentials
                WHERE task_id = ?
                ORDER BY confidence DESC
                """,
                (task_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ==================== scan_layers 表操作 ====================

    async def insert_layer(self, layer_data: Dict[str, Any]) -> str:
        """
        插入镜像层

        Args:
            layer_data: 层数据字典

        Returns:
            layer_id: 层 ID
        """
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO scan_layers (
                    layer_id, task_id, layer_index, size_bytes,
                    file_count, sensitive_files, credentials_found, processed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    layer_data["layer_id"],
                    layer_data["task_id"],
                    layer_data["layer_index"],
                    layer_data["size_bytes"],
                    layer_data["file_count"],
                    layer_data.get("sensitive_files", 0),
                    layer_data.get("credentials_found", 0),
                    layer_data.get("processed", False)
                )
            )
            await db.commit()
            logger.debug("层已插入", layer_id=layer_data["layer_id"])
            return layer_data["layer_id"]

    async def update_layer_processed(
        self,
        layer_id: str,
        processed: bool = True,
        **kwargs
    ) -> bool:
        """
        更新层处理状态

        Args:
            layer_id: 层 ID
            processed: 是否已处理
            **kwargs: 其他更新字段

        Returns:
            是否成功
        """
        async with self.get_connection() as db:
            updates = ["processed = ?"]
            values = [processed]

            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(value)

            values.append(layer_id)

            await db.execute(
                f"UPDATE scan_layers SET {', '.join(updates)} WHERE layer_id = ?",
                values
            )
            await db.commit()
            logger.debug("层状态已更新", layer_id=layer_id, processed=processed)
            return True

    async def get_layers_by_task(self, task_id: str) -> List[Dict[str, Any]]:
        """
        获取任务的所有层

        Args:
            task_id: 任务 ID

        Returns:
            层列表
        """
        async with self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM scan_layers
                WHERE task_id = ?
                ORDER BY layer_index
                """,
                (task_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ==================== scan_metadata 表操作 ====================

    async def insert_metadata(self, metadata: Dict[str, Any]) -> bool:
        """
        插入扫描元数据

        Args:
            metadata: 元数据字典

        Returns:
            是否成功
        """
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO scan_metadata (
                    task_id, image_name, image_id, scanner_version,
                    scan_duration_seconds, total_size_bytes,
                    layers_scanned, files_scanned, credentials_found,
                    false_positive_count, statistics
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata["task_id"],
                    metadata["image_name"],
                    metadata["image_id"],
                    metadata["scanner_version"],
                    metadata["scan_duration_seconds"],
                    metadata["total_size_bytes"],
                    metadata["layers_scanned"],
                    metadata["files_scanned"],
                    metadata["credentials_found"],
                    metadata["false_positive_count"],
                    str(metadata["statistics"])
                )
            )
            await db.commit()
            logger.debug("元数据已插入", task_id=metadata["task_id"])
            return True

    # ==================== 查询操作 ====================

    async def get_all_tasks(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        获取所有任务

        Args:
            limit: 限制数量
            offset: 偏移量

        Returns:
            任务列表
        """
        async with self.get_connection() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM scan_tasks
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_task(self, task_id: str) -> bool:
        """
        删除任务（级联删除关联的凭证、层、元数据）

        Args:
            task_id: 任务 ID

        Returns:
            是否成功
        """
        async with self.get_connection() as db:
            await db.execute("DELETE FROM scan_tasks WHERE task_id = ?", (task_id,))
            await db.commit()
            logger.info("任务已删除", task_id=task_id)
            return True


# 全局数据库实例（延迟加载）
_global_db: Optional[Database] = None


def get_database() -> Database:
    """
    获取全局数据库实例（单例模式）

    Returns:
        数据库实例
    """
    global _global_db
    if _global_db is None:
        config = get_config()
        _global_db = Database(config.storage.database_path)
    return _global_db
