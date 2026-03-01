"""
镜像层数据模型

用途：定义 Docker 镜像层的数据结构

参考：docs/BACKEND_STRUCTURE.md
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid


class ScanLayer(BaseModel):
    """
    镜像层模型

    属性：
        layer_id: 层 SHA256（唯一标识）
        task_id: 关联扫描任务 ID
        layer_index: 层序号（从0开始）
        size_bytes: 层大小（字节）
        file_count: 文件数
        sensitive_files: 敏感文件数
        credentials_found: 发现凭证数
        processed: 是否已处理
    """
    layer_id: str = Field(..., description="层 SHA256")
    task_id: str = Field(..., description="关联任务 ID")
    layer_index: int = Field(..., ge=0, description="层序号")
    size_bytes: int = Field(..., ge=0, description="层大小（字节）")
    file_count: int = Field(default=0, ge=0, description="文件数")
    sensitive_files: int = Field(default=0, ge=0, description="敏感文件数")
    credentials_found: int = Field(default=0, ge=0, description="发现凭证数")
    processed: bool = Field(default=False, description="是否已处理")

    # 附加字段（从 manifest 解析）
    digest: Optional[str] = Field(None, description="层摘要")
    media_type: Optional[str] = Field(None, description="媒体类型")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# 用于数据库操作的辅助类
class ScanLayerDB:
    """镜像层数据库操作辅助类"""

    @staticmethod
    def from_db_row(row: tuple) -> ScanLayer:
        """从数据库行创建 ScanLayer 对象"""
        return ScanLayer(
            layer_id=row[0],
            task_id=row[1],
            layer_index=row[2],
            size_bytes=row[3],
            file_count=row[4],
            sensitive_files=row[5],
            credentials_found=row[6],
            processed=bool(row[7])
        )


# 便捷函数：格式化层大小
def format_layer_size(size_bytes: int) -> str:
    """
    格式化层大小

    Args:
        size_bytes: 字节数

    Returns:
        格式化的字符串（如 "125.5 MB"）
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


# 便捷函数：缩短 SHA256
def short_sha256(sha256: str) -> str:
    """
    缩短 SHA256 显示

    Args:
        sha256: 完整 SHA256

    Returns:
        缩短版本（前12位）
    """
    return sha256[:12] if len(sha256) > 12 else sha256
