"""
扫描任务数据模型

用途：定义扫描任务的数据结构和状态

参考：docs/BACKEND_STRUCTURE.md
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
import uuid


class ScanStatus(str, Enum):
    """扫描状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanTask(BaseModel):
    """
    扫描任务模型

    属性：
        task_id: 任务唯一标识（UUID）
        image_name: 镜像名称（如 "nginx:latest"）
        image_id: 镜像 SHA256
        status: 扫描状态
        created_at: 创建时间
        started_at: 开始时间
        completed_at: 完成时间
        error_message: 错误信息
        total_layers: 总层数
        processed_layers: 已处理层数
        total_files: 总文件数
        processed_files: 已处理文件数
        credentials_found: 发现凭证数
    """
    task_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="任务唯一标识"
    )
    image_name: str = Field(..., description="镜像名称")
    image_id: str = Field(..., description="镜像 SHA256")
    status: ScanStatus = Field(
        default=ScanStatus.PENDING,
        description="扫描状态"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="创建时间"
    )
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    error_message: Optional[str] = Field(None, description="错误信息")
    total_layers: int = Field(default=0, ge=0, description="总层数")
    processed_layers: int = Field(default=0, ge=0, description="已处理层数")
    total_files: int = Field(default=0, ge=0, description="总文件数")
    processed_files: int = Field(default=0, ge=0, description="已处理文件数")
    credentials_found: int = Field(default=0, ge=0, description="发现凭证数")

    class Config:
        use_enum_values = True


# 用于数据库操作的辅助类
class ScanTaskDB:
    """扫描任务数据库操作辅助类"""

    @staticmethod
    def from_db_row(row: tuple) -> ScanTask:
        """从数据库行创建 ScanTask 对象"""
        return ScanTask(
            task_id=row[0],
            image_name=row[1],
            image_id=row[2],
            status=row[3],
            created_at=datetime.fromisoformat(row[4]),
            started_at=datetime.fromisoformat(row[5]) if row[5] else None,
            completed_at=datetime.fromisoformat(row[6]) if row[6] else None,
            error_message=row[7],
            total_layers=row[8],
            processed_layers=row[9],
            total_files=row[10],
            processed_files=row[11],
            credentials_found=row[12]
        )
