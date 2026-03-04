"""API 数据模型"""

from .chat import ChatMessage, ChatResponse, Intent
from .scan import ScanTask, ScanResult

__all__ = [
    "ChatMessage",
    "ChatResponse",
    "Intent",
    "ScanTask",
    "ScanResult",
]
