"""
简单存储管理器 - MVP 阶段

特点：
- 内存中收集结果
- 最后保存为 JSON
- 无数据库依赖
- 为后续 RAG 集成预留接口

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field


@dataclass
class CredentialRecord:
    """
    凭证记录

    Attributes:
        cred_type: 凭证类型
        confidence: 置信度 (0-1)
        file_path: 文件路径
        layer_id: 所在层 ID
        line_number: 行号（可选）
        context: 上下文内容
        validation_status: 验证状态
        created_at: 创建时间
    """
    cred_type: str
    confidence: float
    file_path: str
    layer_id: Optional[str] = None
    line_number: Optional[int] = None
    context: Optional[str] = None
    validation_status: str = "PENDING"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ScanStatistics:
    """
    扫描统计信息

    Attributes:
        total_layers: 总层数
        processed_layers: 已处理层数
        total_files: 总文件数
        scanned_files: 已扫描文件数
        filtered_files: 被过滤的文件数
        high_confidence: 高置信度凭证数
        medium_confidence: 中置信度凭证数
        low_confidence: 低置信度凭证数
    """
    total_layers: int = 0
    processed_layers: int = 0
    total_files: int = 0
    scanned_files: int = 0
    filtered_files: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_layers": self.total_layers,
            "processed_layers": self.processed_layers,
            "total_files": self.total_files,
            "scanned_files": self.scanned_files,
            "filtered_files": self.filtered_files,
            "high_confidence": self.high_confidence,
            "medium_confidence": self.medium_confidence,
            "low_confidence": self.low_confidence
        }


class SimpleStorageManager:
    """
    简单存储管理器

    MVP 阶段的存储方案：
    - 在内存中收集所有扫描结果
    - 最后统一保存为 JSON 文件
    - 为后续集成 RAG 预留接口

    扩展计划：
    - 阶段 2: 添加 SQLite 持久化
    - 阶段 3: 添加 ChromaDB 向量检索（RAG）
    """

    def __init__(self):
        """初始化存储管理器"""
        # 凭证记录
        self._credentials: List[CredentialRecord] = []

        # 统计信息
        self._statistics = ScanStatistics()

        # 扫描元数据
        self._metadata: Dict[str, Any] = {
            "started_at": None,
            "completed_at": None,
            "image_name": None,
            "task_id": None
        }

        # Token 使用统计
        self._token_usage: Dict[str, int] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "call_count": 0
        }

    # ========== 凭证管理 ==========

    def add_credential(self, credential: CredentialRecord):
        """
        添加凭证记录

        Args:
            credential: 凭证记录
        """
        self._credentials.append(credential)

        # 更新置信度统计
        conf = credential.confidence
        if conf >= 0.8:
            self._statistics.high_confidence += 1
        elif conf >= 0.5:
            self._statistics.medium_confidence += 1
        else:
            self._statistics.low_confidence += 1

    def add_credential_from_dict(self, cred_data: Dict[str, Any]):
        """
        从字典添加凭证记录（便捷方法）

        Args:
            cred_data: 凭证数据字典
        """
        credential = CredentialRecord(
            cred_type=cred_data.get("cred_type", "UNKNOWN"),
            confidence=cred_data.get("confidence", 0.0),
            file_path=cred_data.get("file_path", ""),
            layer_id=cred_data.get("layer_id"),
            line_number=cred_data.get("line_number"),
            context=cred_data.get("context"),
            validation_status=cred_data.get("validation_status", "PENDING"),
            created_at=cred_data.get("created_at", datetime.now(timezone.utc).isoformat())
        )
        self.add_credential(credential)

    def get_credentials(self) -> List[CredentialRecord]:
        """
        获取所有凭证记录

        Returns:
            凭证记录列表
        """
        return self._credentials.copy()

    def get_credentials_by_type(self, cred_type: str) -> List[CredentialRecord]:
        """
        按类型获取凭证

        Args:
            cred_type: 凭证类型

        Returns:
            匹配的凭证列表
        """
        return [c for c in self._credentials if c.cred_type == cred_type]

    def get_high_confidence_credentials(self, threshold: float = 0.8) -> List[CredentialRecord]:
        """
        获取高置信度凭证

        Args:
            threshold: 置信度阈值

        Returns:
            高置信度凭证列表
        """
        return [c for c in self._credentials if c.confidence >= threshold]

    # ========== 统计管理 ==========

    def update_stat(self, key: str, value: Any):
        """
        更新统计项

        Args:
            key: 统计项名称
            value: 新值
        """
        if hasattr(self._statistics, key):
            setattr(self._statistics, key, value)

    def increment_stat(self, key: str, delta: int = 1):
        """
        增加统计项

        Args:
            key: 统计项名称
            delta: 增量
        """
        if hasattr(self._statistics, key):
            current = getattr(self._statistics, key)
            setattr(self._statistics, key, current + delta)

    def get_statistics(self) -> ScanStatistics:
        """
        获取统计信息

        Returns:
            统计信息对象
        """
        return self._statistics

    # ========== 元数据管理 ==========

    def set_metadata(self, key: str, value: Any):
        """
        设置元数据

        Args:
            key: 键
            value: 值
        """
        self._metadata[key] = value

    def get_metadata(self, key: str = None) -> Any:
        """
        获取元数据

        Args:
            key: 键（None 返回所有元数据）

        Returns:
            元数据值或全部元数据
        """
        if key is None:
            return self._metadata.copy()
        return self._metadata.get(key)

    # ========== Token 统计 ==========

    def update_token_usage(self, **kwargs):
        """
        更新 Token 使用统计

        Args:
            **kwargs: Token 统计项
        """
        for key, value in kwargs.items():
            if key in self._token_usage:
                self._token_usage[key] = value

    def get_token_usage(self) -> Dict[str, int]:
        """
        获取 Token 使用统计

        Returns:
            Token 使用统计
        """
        return self._token_usage.copy()

    # ========== 结果输出 ==========

    def get_summary(self) -> Dict[str, Any]:
        """
        获取扫描摘要

        Returns:
            摘要字典
        """
        total = len(self._credentials)
        high_conf = self._statistics.high_confidence

        # 风险等级评估
        if high_conf >= 10:
            risk_level = "HIGH"
        elif high_conf >= 3:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        # 凭证类型分布
        type_counts = {}
        for cred in self._credentials:
            cred_type = cred.cred_type
            type_counts[cred_type] = type_counts.get(cred_type, 0) + 1

        return {
            "total_credentials": total,
            "high_confidence": high_conf,
            "medium_confidence": self._statistics.medium_confidence,
            "low_confidence": self._statistics.low_confidence,
            "risk_level": risk_level,
            "credential_types": type_counts,
            "statistics": self._statistics.to_dict(),
            "token_usage": self._token_usage
        }

    def save_to_json(self, output_path: str):
        """
        保存结果为 JSON

        Args:
            output_path: 输出文件路径
        """
        # 构建结果数据
        result_data = {
            "metadata": self._metadata,
            "summary": self.get_summary(),
            "credentials": [
                {
                    "type": cred.cred_type,
                    "confidence": cred.confidence,
                    "file_path": cred.file_path,
                    "layer_id": cred.layer_id,
                    "line_number": cred.line_number,
                    "context": cred.context,
                    "validation_status": cred.validation_status,
                    "created_at": cred.created_at
                }
                for cred in self._credentials
            ]
        }

        # 保存到文件
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)

    # ========== 清理 ==========

    def clear(self):
        """清空所有数据"""
        self._credentials.clear()
        self._statistics = ScanStatistics()
        self._metadata = {
            "started_at": None,
            "completed_at": None,
            "image_name": None,
            "task_id": None
        }
        self._token_usage = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "call_count": 0
        }

    def __repr__(self) -> str:
        """字符串表示"""
        return (f"SimpleStorageManager("
                f"credentials={len(self._credentials)}, "
                f"risk_level={self.get_summary()['risk_level']})")
