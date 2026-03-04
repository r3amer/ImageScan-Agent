"""
摘要管理器 - 规则生成摘要

职责：
1. 追踪对话历史
2. 规则生成摘要（非 LLM）
3. 超过阈值时压缩上下文

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

import json
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class CredentialRecord:
    """凭证记录"""
    file_path: str
    credential_type: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ErrorRecord:
    """错误记录"""
    error_message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class SummaryManager:
    """
    摘要管理器

    使用规则生成摘要，压缩对话历史
    """

    def __init__(self, token_threshold: int = 10000, keep_recent: int = 5):
        """
        初始化摘要管理器

        Args:
            token_threshold: Token 阈值，超过时触发摘要
            keep_recent: 摘要时保留的最近对话轮次
        """
        self.token_threshold = token_threshold
        self.keep_recent = keep_recent

        # 对话历史
        self.conversation_history: List[Dict] = []

        # 摘要数据
        self.tool_calls: List[str] = []
        self.credentials: List[CredentialRecord] = []
        self.errors: List[ErrorRecord] = []

        # 进度信息
        self.current_progress: Optional[str] = None

    def add_message(self, role: str, content: str):
        """
        添加对话消息

        Args:
            role: 角色 (system/user/assistant/tool)
            content: 内容
        """
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })

    def record_tool_call(self, tool_name: str):
        """
        记录工具调用

        Args:
            tool_name: 工具名称
        """
        if tool_name not in self.tool_calls:
            self.tool_calls.append(tool_name)

    def record_credential(self, file_path: str, credential_type: str):
        """
        记录发现的凭证

        Args:
            file_path: 文件路径
            credential_type: 凭证类型
        """
        self.credentials.append(CredentialRecord(
            file_path=file_path,
            credential_type=credential_type
        ))

    def record_error(self, error_message: str):
        """
        记录错误

        Args:
            error_message: 错误信息
        """
        self.errors.append(ErrorRecord(error_message=error_message))

    def update_progress(self, progress: str):
        """
        更新当前进度

        Args:
            progress: 进度描述（如 "已扫描 3/5 层"）
        """
        self.current_progress = progress

    def should_summarize(self) -> bool:
        """
        判断是否需要生成摘要

        Returns:
            是否需要摘要
        """
        # 估算 Token 数量（粗略：1 token ≈ 4 字符）
        total_chars = sum(len(msg.get("content", "")) for msg in self.conversation_history)
        estimated_tokens = total_chars / 4

        return estimated_tokens > self.token_threshold

    def summarize(self) -> str:
        """
        生成摘要（规则方式）

        Returns:
            摘要文本
        """
        summary_parts = []

        # 1. 对话轮次
        summary_parts.append(f"对话轮次: {len(self.conversation_history)}")

        # 2. 调用的工具
        if self.tool_calls:
            summary_parts.append(f"调用工具: {', '.join(self.tool_calls)}")

        # 3. 发现凭证的文件路径
        if self.credentials:
            credential_files = [c.file_path for c in self.credentials]
            summary_parts.append(f"发现凭证的文件: {', '.join(credential_files)}")

        # 4. 凭证类型统计
        if self.credentials:
            type_counts = {}
            for cred in self.credentials:
                cred_type = cred.credential_type
                type_counts[cred_type] = type_counts.get(cred_type, 0) + 1

            type_str = ", ".join([f"{t}: {c}" for t, c in type_counts.items()])
            summary_parts.append(f"凭证类型: {type_str}")

        # 5. 错误信息
        if self.errors:
            error_messages = [e.error_message for e in self.errors]
            summary_parts.append(f"错误: {', '.join(error_messages)}")

        # 6. 当前进度
        if self.current_progress:
            summary_parts.append(f"进度: {self.current_progress}")

        return "\n".join(summary_parts)

    def get_context(self) -> List[Dict]:
        """
        获取用于 LLM 调用的上下文

        如果超过阈值，返回摘要 + 最近 N 轮对话
        否则返回完整对话历史

        Returns:
            上下文消息列表
        """
        if self.should_summarize():
            # 生成摘要
            summary = self.summarize()

            # 摘要 + 最近 N 轮对话
            recent_messages = self.conversation_history[-self.keep_recent:]

            return [
                {"role": "system", "content": f"以下是之前的对话摘要:\n{summary}"},
                *recent_messages
            ]
        else:
            return self.conversation_history

    def get_summary_dict(self) -> Dict:
        """
        获取摘要的字典格式

        Returns:
            摘要字典
        """
        # 凭证类型统计
        type_counts = {}
        for cred in self.credentials:
            cred_type = cred.credential_type
            type_counts[cred_type] = type_counts.get(cred_type, 0) + 1

        return {
            "tool_calls": self.tool_calls,
            "credential_files": [c.file_path for c in self.credentials],
            "credential_types": type_counts,
            "total_turns": len(self.conversation_history),
            "errors": [e.error_message for e in self.errors],
            "progress": self.current_progress
        }

    def clear_history(self):
        """清除对话历史（保留摘要数据）"""
        self.conversation_history.clear()

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "total_messages": len(self.conversation_history),
            "tool_calls_count": len(self.tool_calls),
            "credentials_count": len(self.credentials),
            "errors_count": len(self.errors),
            "estimated_tokens": sum(len(msg.get("content", "")) for msg in self.conversation_history) / 4
        }
