"""
记忆存储 - SQLite 持久化

职责：
1. 记录扫描统计
2. 记录文件模式和误报模式
3. 记录凭证模式
4. 提供历史记忆查询

参考：docs/CONTEXT_OPTIMIZATION_DESIGN.md
"""

import sqlite3
import json
import hashlib
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

from ..utils.logger import get_logger

logger = get_logger(__name__)


class MemoryStore:
    """
    记忆存储 - SQLite 持久化

    提供跨任务的知识复用：
    - 镜像历史扫描统计
    - 高频误报文件模式
    - 常见凭证提取模式
    """

    def __init__(self, db_path: str = "./data/memory.db"):
        """
        初始化记忆存储

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = None
        self._init_database()

    def _init_database(self):
        """初始化数据库表"""
        # 确保目录存在
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

        # 创建表
        self._create_tables()

        logger.info("记忆存储初始化完成", db_path=self.db_path)

    def _create_tables(self):
        """创建数据库表"""
        # 扫描统计表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                image_name TEXT NOT NULL,
                total_layers INTEGER,
                total_files INTEGER,
                scanned_files INTEGER,
                credentials_count INTEGER,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                last_scan TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(image_name, task_id)
            )
        """)

        # 文件模式表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS file_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_pattern TEXT NOT NULL,
                scan_count INTEGER DEFAULT 1,
                total_credentials INTEGER DEFAULT 0,
                false_positive_count INTEGER DEFAULT 0,
                last_scan TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(file_pattern)
            )
        """)

        # 凭证模式表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS credential_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_hash TEXT NOT NULL UNIQUE,
                pattern TEXT NOT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confidence REAL,
                occurrence_count INTEGER DEFAULT 1,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 误报模式表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS false_positive_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_pattern TEXT NOT NULL,
                reason TEXT,
                report_count INTEGER DEFAULT 1,
                last_reported TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(file_pattern)
            )
        """)

        # 创建索引
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_stats_image
            ON scan_stats(image_name)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_patterns_scan_count
            ON file_patterns(scan_count DESC)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_credential_patterns_confidence
            ON credential_patterns(confidence DESC)
        """)

        self.conn.commit()

    # ========== 扫描统计 ==========

    def record_scan_start(self, task_id: str, image_name: str):
        """记录扫描开始"""
        self.conn.execute("""
            INSERT INTO scan_stats (task_id, image_name, started_at)
            VALUES (?, ?, ?)
        """, (task_id, image_name, datetime.now(timezone.utc)))
        self.conn.commit()

    def record_scan_complete(
        self,
        task_id: str,
        image_name: str,
        total_layers: int,
        total_files: int,
        scanned_files: int,
        credentials_count: int
    ):
        """记录扫描完成"""
        self.conn.execute("""
            INSERT INTO scan_stats
            (task_id, image_name, total_layers, total_files, scanned_files,
             credentials_count, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(image_name, task_id) DO UPDATE SET
                total_layers = excluded.total_layers,
                total_files = excluded.total_files,
                scanned_files = excluded.scanned_files,
                credentials_count = excluded.credentials_count,
                completed_at = excluded.completed_at
        """, (task_id, image_name, total_layers, total_files, scanned_files,
               credentials_count, datetime.now(timezone.utc)))
        self.conn.commit()

    def get_image_history(self, image_name: str) -> Optional[Dict]:
        """获取镜像的历史扫描记录"""
        row = self.conn.execute("""
            SELECT
                total_layers, total_files, scanned_files, credentials_count,
                last_scan, completed_at
            FROM scan_stats
            WHERE image_name = ?
            ORDER BY last_scan DESC
            LIMIT 1
        """, (image_name,)).fetchone()

        if row:
            return {
                "total_layers": row["total_layers"],
                "total_files": row["total_files"],
                "scanned_files": row["scanned_files"],
                "credentials_count": row["credentials_count"],
                "last_scan": row["last_scan"],
                "completed_at": row["completed_at"]
            }
        return None

    # ========== 文件模式 ==========

    def increment_file_scan_count(self, file_path: str):
        """增加文件扫描计数"""
        # 提取文件模式（如 "appsettings*.json"）
        pattern = self._extract_file_pattern(file_path)

        self.conn.execute("""
            INSERT INTO file_patterns (file_pattern, scan_count, last_scan)
            VALUES (?, 1, ?)
            ON CONFLICT(file_pattern) DO UPDATE SET
                scan_count = scan_count + 1,
                last_scan = ?
        """, (pattern, datetime.now(timezone.utc), datetime.now(timezone.utc)))
        self.conn.commit()

    def record_file_pattern_credentials(
        self,
        file_pattern: str,
        credentials_count: int
    ):
        """记录文件模式发现的凭证数量"""
        self.conn.execute("""
            INSERT INTO file_patterns (file_pattern, scan_count, total_credentials)
            VALUES (?, 1, ?)
            ON CONFLICT(file_pattern) DO UPDATE SET
                total_credentials = total_credentials + excluded.total_credentials
        """, (file_pattern, credentials_count))
        self.conn.commit()

    def record_false_positive(
        self,
        file_pattern: str,
        reason: str
    ):
        """记录误报模式"""
        self.conn.execute("""
            INSERT INTO false_positive_patterns (file_pattern, reason, report_count)
            VALUES (?, ?, 1)
            ON CONFLICT(file_pattern) DO UPDATE SET
                report_count = report_count + 1,
                last_reported = ?
        """, (file_pattern, reason, datetime.now(timezone.utc)))
        self.conn.commit()

    def get_false_positive_patterns(self) -> List[Dict]:
        """获取所有误报模式（按报告次数排序）"""
        rows = self.conn.execute("""
            SELECT file_pattern, reason, report_count
            FROM false_positive_patterns
            ORDER BY report_count DESC
        """).fetchall()

        return [
            {
                "pattern": row["file_pattern"],
                "reason": row["reason"],
                "count": row["report_count"]
            }
            for row in rows
        ]

    def _extract_file_pattern(self, file_path: str) -> str:
        """
        从文件路径提取模式

        例如：
        - "app/settings.json" -> "app/settings.json"
        - "app/appsettings.Production.json" -> "app/appsettings.*.json"
        - "migrations/001_init.sql" -> "migrations/*.sql"
        """
        # 获取文件名部分
        parts = file_path.split("/")
        filename = parts[-1] if parts else file_path

        # 检查是否有扩展名
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            # 如果文件名包含数字、版本号，转换为通配符
            import re
            if re.search(r'\d+', name):
                # "appsettings.Production" -> "appsettings.*"
                name = re.sub(r'\d+', '*', name)
            return f"{parts[-2]}/{name}*.{ext}" if len(parts) > 1 else f"{name}*.{ext}"
        else:
            return file_path

    # ========== 凭证模式 ==========

    def record_credential_pattern(
        self,
        pattern: str,
        confidence: float,
        context: Optional[str] = None
    ):
        """记录凭证模式"""
        content_hash = hashlib.md5(pattern.encode()).hexdigest()
        now = datetime.now(timezone.utc)

        self.conn.execute("""
            INSERT INTO credential_patterns (content_hash, pattern, first_seen, confidence)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(content_hash) DO UPDATE SET
                occurrence_count = occurrence_count + 1,
                confidence = MAX(excluded.confidence, ?),
                last_seen = ?
        """, (content_hash, pattern, now, confidence, confidence, now))
        self.conn.commit()

    def get_credential_patterns(self) -> List[Dict]:
        """获取所有凭证模式（按出现次数和置信度排序）"""
        rows = self.conn.execute("""
            SELECT pattern, occurrence_count, confidence, first_seen
            FROM credential_patterns
            ORDER BY occurrence_count DESC, confidence DESC
            LIMIT 20
        """).fetchall()

        return [
            {
                "pattern": row["pattern"],
                "count": row["occurrence_count"],
                "confidence": row["confidence"],
                "first_seen": row["first_seen"]
            }
            for row in rows
        ]

    # ========== 记忆查询 ==========

    async def get_relevant_memories(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取相关的历史记忆

        Args:
            context: 当前上下文

        Returns:
            记忆字典
        """
        memories = {}
        image_name = context.get("image_name", "")

        # 1. 镜像历史
        if image_name:
            history = self.get_image_history(image_name)
            if history:
                memories["image_history"] = history

        # 2. 误报模式（如果在文件分析阶段，步骤 >= 5）
        current_step = context.get("current_step", 0)
        if current_step >= 5:
            false_positives = self.get_false_positive_patterns()
            if false_positives:
                memories["false_positive_patterns"] = {
                    "patterns": false_positives,
                    "total_count": len(false_positives)
                }

        # 3. 凭证模式（如果已经发现凭证）
        credentials_found = context.get("credentials_found", 0)
        if credentials_found > 0:
            credential_patterns = self.get_credential_patterns()
            if credential_patterns:
                memories["credential_patterns"] = {
                    "patterns": credential_patterns,
                    "total_count": len(credential_patterns)
                }

        return memories

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        """支持上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """支持上下文管理器"""
        self.close()
        return False