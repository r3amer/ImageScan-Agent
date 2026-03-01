"""
扫描元数据模型

用途：定义扫描任务的整体统计和元数据

参考：docs/BACKEND_STRUCTURE.md
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum
import uuid


class ScanMetadata(BaseModel):
    """
    扫描元数据模型

    属性：
        task_id: 任务 ID
        image_name: 镜像名称
        image_id: 镜像 ID
        scanner_version: 扫描器版本
        scan_duration_seconds: 扫描耗时（秒）
        total_size_bytes: 镜像总大小
        layers_scanned: 扫描层数
        files_scanned: 扫描文件数
        credentials_found: 发现凭证数
        false_positive_count: 误报数
        statistics: 统计信息
    """
    task_id: str = Field(..., description="任务 ID")
    image_name: str = Field(..., description="镜像名称")
    image_id: str = Field(..., description="镜像 ID")
    scanner_version: str = Field(default="1.0.0", description="扫描器版本")
    scan_duration_seconds: float = Field(..., ge=0, description="扫描耗时（秒）")
    total_size_bytes: int = Field(..., ge=0, description="镜像总大小")
    layers_scanned: int = Field(..., ge=0, description="扫描层数")
    files_scanned: int = Field(..., ge=0, description="扫描文件数")
    credentials_found: int = Field(..., ge=0, description="发现凭证数")
    false_positive_count: int = Field(default=0, ge=0, description="误报数")
    statistics: Dict[str, Any] = Field(
        default_factory=dict,
        description="统计信息"
    )


class ScanStatistics(BaseModel):
    """
    扫描统计信息

    属性：
        confidence_distribution: 置信度分布
        credential_type_distribution: 凭证类型分布
        layer_distribution: 层分布
        high_risk_count: 高风险凭证数
        medium_risk_count: 中风险凭证数
        low_risk_count: 低风险凭证数
        comparison_with_trufflehog: 与 TruffleHog 对比
    """
    confidence_distribution: Dict[str, int] = Field(
        default_factory=lambda: {"high": 0, "medium": 0, "low": 0},
        description="置信度分布"
    )
    credential_type_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="凭证类型分布"
    )
    layer_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="层分布"
    )
    high_risk_count: int = Field(default=0, ge=0, description="高风险凭证数")
    medium_risk_count: int = Field(default=0, ge=0, description="中风险凭证数")
    low_risk_count: int = Field(default=0, ge=0, description="低风险凭证数")
    comparison_with_trufflehog: Optional[Dict[str, Any]] = Field(
        None,
        description="与 TruffleHog 对比结果"
    )

    def calculate_totals(self) -> int:
        """计算总凭证数"""
        return self.high_risk_count + self.medium_risk_count + self.low_risk_count

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "confidence_distribution": self.confidence_distribution,
            "credential_type_distribution": self.credential_type_distribution,
            "layer_distribution": self.layer_distribution,
            "high_risk_count": self.high_risk_count,
            "medium_risk_count": self.medium_risk_count,
            "low_risk_count": self.low_risk_count,
            "total_count": self.calculate_totals()
        }


# 用于生成最终报告
class ScanReport(BaseModel):
    """
    完整扫描报告

    整合任务、凭证、层和元数据
    """
    metadata: ScanMetadata
    credentials: list  # Credential 列表
    layers: list  # ScanLayer 列表
    statistics: ScanStatistics
    errors: list = Field(default_factory=list, description="错误列表")

    def to_json(self) -> dict:
        """转换为 JSON 格式"""
        return {
            "version": "1.0.0",
            "metadata": self.metadata.dict(),
            "credentials": [cred.dict() for cred in self.credentials],
            "layers": [layer.dict() for layer in self.layers],
            "statistics": self.statistics.to_dict(),
            "errors": self.errors
        }
