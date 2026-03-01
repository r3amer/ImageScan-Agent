"""
凭证数据模型

用途：定义检测到的敏感凭证的数据结构

参考：docs/BACKEND_STRUCTURE.md
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
import uuid


class CredentialType(str, Enum):
    """凭证类型枚举"""
    API_KEY = "api_key"
    PASSWORD = "password"
    TOKEN = "token"
    CERTIFICATE = "certificate"
    PRIVATE_KEY = "private_key"
    DATABASE_URL = "database_url"
    AWS_KEY = "aws_key"
    SSH_KEY = "ssh_key"
    UNKNOWN = "unknown"


class ValidationStatus(str, Enum):
    """验证状态枚举"""
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


class Credential(BaseModel):
    """
    凭证模型

    属性：
        credential_id: 凭证唯一标识（UUID）
        task_id: 关联的扫描任务 ID
        cred_type: 凭证类型
        confidence: 置信度 (0.0 - 1.0)
        file_path: 文件路径
        line_number: 行号
        layer_id: 所在层 SHA256
        context: 上下文（脱敏后）
        raw_value: 原始值（加密存储）
        validation_status: 验证状态
        verified_at: 验证时间
        metadata: 额外元数据
    """
    credential_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="凭证唯一标识"
    )
    task_id: str = Field(..., description="关联任务 ID")
    cred_type: CredentialType = Field(..., description="凭证类型")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="置信度"
    )
    file_path: str = Field(..., description="文件路径")
    line_number: Optional[int] = Field(None, description="行号")
    layer_id: str = Field(..., description="所在层 SHA256")
    context: str = Field(..., description="上下文（脱敏）")
    raw_value: Optional[str] = Field(None, description="原始值（加密存储）")
    validation_status: ValidationStatus = Field(
        default=ValidationStatus.PENDING,
        description="验证状态"
    )
    verified_at: Optional[datetime] = Field(None, description="验证时间")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="额外元数据"
    )

    class Config:
        use_enum_values = True


# 用于风险评估的辅助类
class RiskLevel(str, Enum):
    """风险等级"""
    HIGH = "high"        # 高风险（置信度 > 0.9）
    MEDIUM = "medium"    # 中风险（置信度 0.7 - 0.9）
    LOW = "low"         # 低风险（置信度 < 0.7）


def get_risk_level(confidence: float) -> RiskLevel:
    """
    根据置信度计算风险等级

    Args:
        confidence: 置信度（0.0 - 1.0）

    Returns:
        风险等级
    """
    if confidence >= 0.9:
        return RiskLevel.HIGH
    elif confidence >= 0.7:
        return RiskLevel.MEDIUM
    else:
        return RiskLevel.LOW


# 用于数据库操作的辅助类
class CredentialDB:
    """凭证数据库操作辅助类"""

    @staticmethod
    def from_db_row(row: tuple) -> Credential:
        """从数据库行创建 Credential 对象"""
        return Credential(
            credential_id=row[0],
            task_id=row[1],
            cred_type=row[2],
            confidence=row[3],
            file_path=row[4],
            line_number=row[5],
            layer_id=row[6],
            context=row[7],
            raw_value=row[8],
            validation_status=row[9],
            verified_at=datetime.fromisoformat(row[10]) if row[10] else None,
            metadata=eval(row[11]) if row[11] else {}
        )
