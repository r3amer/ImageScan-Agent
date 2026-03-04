"""
扫描相关数据模型

参考：progress_frontend.txt 第一阶段
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


class Credential(BaseModel):
    """凭证信息"""
    type: str = Field(..., description="凭证类型")
    confidence: float = Field(..., description="置信度 0-1")
    file_path: str = Field(..., description="文件路径")
    layer_id: Optional[str] = Field(None, description="镜像层 ID")
    line_number: Optional[int] = Field(None, description="行号")
    validation_status: Optional[str] = Field(None, description="验证状态")


class ScanStatistics(BaseModel):
    """扫描统计"""
    total_layers: int = Field(..., description="总层数")
    processed_layers: int = Field(..., description="已处理层数")
    total_files: int = Field(..., description="总文件数")
    scanned_files: int = Field(..., description="已扫描文件数")


class ScanResult(BaseModel):
    """扫描结果"""
    task_id: str = Field(..., description="任务 ID")
    image_name: str = Field(..., description="镜像名称")
    status: Literal["running", "completed", "failed"] = Field(
        ..., description="扫描状态"
    )
    credentials: List[Credential] = Field(default_factory=list, description="发现的凭证")
    statistics: Optional[ScanStatistics] = Field(None, description="扫描统计")
    token_usage: Optional[Dict[str, int]] = Field(None, description="Token 使用统计")
    duration: Optional[float] = Field(None, description="扫描耗时（秒）")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")


class ScanTask(BaseModel):
    """扫描任务"""
    image_name: str = Field(..., description="镜像名称")
    session_id: Optional[str] = Field(None, description="会话 ID")
