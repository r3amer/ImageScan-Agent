"""
对话相关数据模型

参考：progress_frontend.txt 第一阶段
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any


class ChatMessage(BaseModel):
    """用户消息"""
    message: str = Field(..., description="用户输入的对话内容")
    session_id: Optional[str] = Field(None, description="会话 ID")


class Intent(BaseModel):
    """解析后的意图"""
    action: Literal["scan", "query", "unknown"] = Field(
        ..., description="用户意图：扫描/查询/未知"
    )
    image_name: Optional[str] = Field(None, description="要扫描的镜像名称")
    confidence: float = Field(..., description="置信度 0-1")
    reasoning: str = Field(..., description="推理过程")


class ChatResponse(BaseModel):
    """AI 响应"""
    message: str = Field(..., description="AI 回复内容")
    type: Literal["text", "scan_started", "scan_complete", "error"] = Field(
        "text", description="响应类型"
    )
    task_id: Optional[str] = Field(None, description="任务 ID（如果是扫描任务）")
    data: Optional[Dict[str, Any]] = Field(None, description="附加数据")
