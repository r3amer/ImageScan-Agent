"""
事件系统模块

用途：
1. 定义所有 Agent 之间通信的事件类型
2. 事件数据结构
3. 事件序列化和反序列化

参考：docs/APP_FLOW.md
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class EventType(str, Enum):
    """事件类型枚举"""

    # ========== 任务管理 ==========
    TASK_CREATED = "task.created"              # 任务创建
    TASK_STARTED = "task.started"              # 任务开始
    TASK_PROGRESS = "task.progress"            # 任务进度更新
    TASK_COMPLETED = "task.completed"          # 任务完成
    TASK_FAILED = "task.failed"                # 任务失败
    TASK_CANCELLED = "task.cancelled"          # 任务取消

    # ========== 层处理 ==========
    LAYER_DISCOVERED = "layer.discovered"      # 发现新层
    LAYER_ANALYSIS_STARTED = "layer.analysis_started"  # 层分析开始
    LAYER_ANALYSIS_COMPLETED = "layer.analysis_completed"  # 层分析完成
    LAYER_FILES_FILTERED = "layer.files_filtered"  # 文件过滤完成

    # ========== 文件扫描 ==========
    FILE_SCAN_STARTED = "file.scan_started"    # 文件扫描开始
    FILE_SCAN_COMPLETED = "file.scan_completed"  # 文件扫描完成
    FILE_CREDENTIAL_FOUND = "file.credential_found"  # 发现凭证

    # ========== 凭证验证 ==========
    CREDENTIAL_DETECTED = "credential.detected"  # 检测到凭证
    CREDENTIAL_VALIDATION_STARTED = "credential.validation_started"  # 验证开始
    CREDENTIAL_VALIDATION_COMPLETED = "credential.validation_completed"  # 验证完成
    CREDENTIAL_CONFIRMED = "credential.confirmed"  # 确认为真凭证
    CREDENTIAL_REJECTED = "credential.rejected"  # 判定为误报

    # ========== 知识检索 ==========
    KNOWLEDGE_QUERY = "knowledge.query"          # 查询知识库
    KNOWLEDGE_RESULT = "knowledge.result"        # 知识库结果

    # ========== 研判反思 ==========
    REFLECTION_STARTED = "reflection.started"    # 研判开始
    REFLECTION_COMPLETED = "reflection.completed"  # 研判完成
    CONFIDENCE_ADJUSTED = "confidence.adjusted"  # 置信度调整

    # ========== 错误处理 ==========
    ERROR_OCCURRED = "error.occurred"            # 发生错误
    ERROR_RECOVERED = "error.recovered"          # 错误恢复

    # ========== 系统控制 ==========
    AGENT_READY = "agent.ready"                  # Agent 就绪
    AGENT_SHUTDOWN = "agent.shutdown"            # Agent 关闭


class Event(BaseModel):
    """
    事件基类

    属性：
        event_id: 事件唯一标识
        event_type: 事件类型
        timestamp: 时间戳
        source: 事件源（哪个 Agent 发出的）
        data: 事件数据
        correlation_id: 关联 ID（用于追踪相关事件）
    """
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str  # Agent 名称
    data: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None  # 用于关联同一流程的多个事件

    class Config:
        use_enum_values = True


# ========== 具体事件类型 ==========

class TaskEvent(Event):
    """任务事件"""

    def __init__(
        self,
        event_type: EventType,
        source: str,
        task_id: str,
        **kwargs
    ):
        super().__init__(
            event_type=event_type,
            source=source,
            data={
                "task_id": task_id,
                **kwargs
            },
            correlation_id=task_id
        )


class LayerEvent(Event):
    """层事件"""

    def __init__(
        self,
        event_type: EventType,
        source: str,
        task_id: str,
        layer_id: str,
        **kwargs
    ):
        super().__init__(
            event_type=event_type,
            source=source,
            data={
                "task_id": task_id,
                "layer_id": layer_id,
                **kwargs
            },
            correlation_id=task_id
        )


class CredentialEvent(Event):
    """凭证事件"""

    def __init__(
        self,
        event_type: EventType,
        source: str,
        task_id: str,
        credential_id: str,
        **kwargs
    ):
        super().__init__(
            event_type=event_type,
            source=source,
            data={
                "task_id": task_id,
                "credential_id": credential_id,
                **kwargs
            },
            correlation_id=task_id
        )


class ProgressEvent(Event):
    """进度事件"""

    def __init__(
        self,
        event_type: EventType,
        source: str,
        task_id: str,
        **kwargs
    ):
        super().__init__(
            event_type=event_type,
            source=source,
            data={
                "task_id": task_id,
                **kwargs
            },
            correlation_id=task_id
        )


class ErrorEvent(Event):
    """错误事件"""

    def __init__(
        self,
        event_type: EventType,
        source: str,
        error_message: str,
        error_type: str,
        **kwargs
    ):
        super().__init__(
            event_type=event_type,
            source=source,
            data={
                "error_message": error_message,
                "error_type": error_type,
                **kwargs
            }
        )


# ========== 便捷创建函数 ==========

def create_task_created(
    source: str,
    task_id: str,
    image_name: str,
    image_id: str
) -> TaskEvent:
    """创建任务开始事件"""
    return TaskEvent(
        event_type=EventType.TASK_CREATED,
        source=source,
        task_id=task_id,
        image_name=image_name,
        image_id=image_id
    )


def create_task_progress(
    source: str,
    task_id: str,
    current_layer: int,
    total_layers: int,
    current_file: int = 0,
    total_files: int = 0,
    credentials_found: int = 0
) -> ProgressEvent:
    """创建任务进度事件"""
    return ProgressEvent(
        event_type=EventType.TASK_PROGRESS,
        source=source,
        task_id=task_id,
        current_layer=current_layer,
        total_layers=total_layers,
        current_file=current_file,
        total_files=total_files,
        credentials_found=credentials_found
    )


def create_credential_found(
    source: str,
    task_id: str,
    credential_id: str,
    cred_type: str,
    confidence: float,
    file_path: str
) -> CredentialEvent:
    """创建凭证发现事件"""
    return CredentialEvent(
        event_type=EventType.FILE_CREDENTIAL_FOUND,
        source=source,
        task_id=task_id,
        credential_id=credential_id,
        cred_type=cred_type,
        confidence=confidence,
        file_path=file_path
    )


def create_error(
    source: str,
    error_message: str,
    error_type: str,
    task_id: Optional[str] = None
) -> ErrorEvent:
    """创建错误事件"""
    data = {}
    if task_id:
        data["task_id"] = task_id

    return ErrorEvent(
        event_type=EventType.ERROR_OCCURRED,
        source=source,
        error_message=error_message,
        error_type=error_type,
        **data
    )
