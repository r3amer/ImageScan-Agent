"""
核心模块

导出所有核心组件：
- LLMClient: LLM 客户端
- FilenameAnalyzer: 文件名分析器
- ContentScanner: 内容扫描器
- Event, EventType: 事件系统
- EventBus: 事件总线
- Agent, BaseAgent: Agent 基类
"""

from .llm_client import LLMClient, LLMClientError, get_llm_client
from .filename_analyzer import (
    FilenameAnalyzer,
    FilenameAnalysisResult,
    get_filename_analyzer
)
from .content_scanner import (
    ContentScanner,
    FileScanResult,
    get_content_scanner
)
from .events import (
    Event,
    EventType,
    TaskEvent,
    LayerEvent,
    CredentialEvent,
    ProgressEvent,
    ErrorEvent,
    create_task_created,
    create_task_progress,
    create_credential_found,
    create_error
)
from .event_bus import EventBus, get_event_bus
from .agent import Agent, BaseAgent, AgentState

__all__ = [
    # LLM Client
    "LLMClient",
    "LLMClientError",
    "get_llm_client",

    # Filename Analyzer
    "FilenameAnalyzer",
    "FilenameAnalysisResult",
    "get_filename_analyzer",

    # Content Scanner
    "ContentScanner",
    "FileScanResult",
    "get_content_scanner",

    # Events
    "Event",
    "EventType",
    "TaskEvent",
    "LayerEvent",
    "CredentialEvent",
    "ProgressEvent",
    "ErrorEvent",
    "create_task_created",
    "create_task_progress",
    "create_credential_found",
    "create_error",

    # Event Bus
    "EventBus",
    "get_event_bus",

    # Agent
    "Agent",
    "BaseAgent",
    "AgentState",
]
