"""
上下文压缩器 - 自动分级压缩

职责：
1. 检测上下文大小，自动触发压缩
2. 实现 3 级压缩策略
3. 生成上下文摘要

参考：docs/CONTEXT_OPTIMIZATION_DESIGN.md
"""

import json
from typing import Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass

from .context import CompressionLevel
from ..utils.logger import get_logger
from ..utils.config import Config

logger = get_logger(__name__)


@dataclass
class CompressionTrigger:
    """压缩触发条件"""
    level: int
    name: str
    token_threshold: int
    tool_history_threshold: int


class ContextCompressor:
    """
    上下文压缩器

    实现自动分级压缩，根据上下文大小自动选择压缩级别
    """

    def __init__(self, config: Config):
        """
        初始化压缩器

        Args:
            config: 配置对象
        """
        self.config = config

        # 默认触发条件
        self.triggers = [
            CompressionTrigger(
                level=CompressionLevel.LIGHT,
                name="轻度压缩",
                token_threshold=12000,
                tool_history_threshold=8
            ),
            CompressionTrigger(
                level=CompressionLevel.MEDIUM,
                name="中度压缩",
                token_threshold=25000,
                tool_history_threshold=15
            ),
            CompressionTrigger(
                level=CompressionLevel.HEAVY,
                name="深度压缩",
                token_threshold=40000,
                tool_history_threshold=20
            ),
        ]

        # 从配置加载触发条件（如果有）
        if (hasattr(config, 'context_management') and
            config.context_management and
            config.context_management.compression_triggers):
            self.triggers = []
            for trigger_cfg in config.context_management.compression_triggers:
                self.triggers.append(CompressionTrigger(
                    level=CompressionLevel(trigger_cfg.level),
                    name=trigger_cfg.name,
                    token_threshold=trigger_cfg.token_threshold,
                    tool_history_threshold=trigger_cfg.tool_history_threshold
                ))
            logger.info("从配置加载压缩触发条件", count=len(self.triggers))

    def get_compression_level(
        self,
        context: Dict[str, Any],
        max_tokens: int = None
    ) -> CompressionLevel:
        """
        检查并返回当前需要的压缩级别

        Args:
            context: 当前上下文
            max_tokens: 最大 token 限制（可选）

        Returns:
            CompressionLevel: 压缩级别
        """
        # 估算 token 数量
        token_count = self._estimate_tokens(context)

        # 检查 tool_history 大小
        history_size = len(context.get("tool_history", []))

        # 匹配触发条件（从高到低检查）
        for trigger in sorted(self.triggers, key=lambda t: t.level, reverse=True):
            if token_count >= trigger.token_threshold or history_size >= trigger.tool_history_threshold:
                return trigger.level

        return CompressionLevel.NONE

    def compress(
        self,
        context: Dict[str, Any],
        level: CompressionLevel
    ) -> Dict[str, Any]:
        """
        执行压缩

        Args:
            context: 原始上下文
            level: 目标压缩级别

        Returns:
            压缩后的上下文（注意：会修改原 context）
        """
        if level == CompressionLevel.NONE:
            return context

        # 创建压缩后的副本（避免修改原始上下文）
        compressed = context.copy()

        if level >= CompressionLevel.LIGHT:
            # 清理 tool_history（只保留最近 3 个）
            if "tool_history" in compressed:
                compressed["tool_history"] = compressed["tool_history"][-3:]

        if level >= CompressionLevel.MEDIUM:
            # 清理 error_history（只保留最近 2 个）
            if "error_history" in compressed:
                compressed["error_history"] = compressed["error_history"][-2:]

            # 清理 findings（只保留摘要统计）
            if "findings" in compressed and len(compressed["findings"]) > 10:
                compressed["findings_summary"] = f"发现 {len(compressed['findings'])} 个项目"
                del compressed["findings"]

        if level == CompressionLevel.HEAVY:
            # 只保留最关键的信息
            compressed = {
                "current_state": compressed.get("current_state"),
                "current_step": compressed.get("current_step"),
                "max_steps": compressed.get("max_steps"),
                "credentials_found": compressed.get("credentials_found", 0),
                "last_error": compressed.get("last_error")
            }

        logger.info(
            "上下文已压缩",
            level=level.name,
            original_tokens=self._estimate_tokens(context),
            compressed_tokens=self._estimate_tokens(compressed),
            history_size=len(context.get("tool_history", [])),
            compressed_history_size=len(compressed.get("tool_history", []))
        )

        return compressed

    def generate_summary(self, context: Dict[str, Any]) -> str:
        """
        生成上下文摘要

        Args:
            context: 当前上下文

        Returns:
            摘要文本
        """
        summary_parts = []

        # 对话轮次
        current_step = context.get("current_step", 0)
        max_steps = context.get("max_steps", 30)
        summary_parts.append(f"已完成步骤：{current_step}/{max_steps}")

        # 调用的工具
        tool_history = context.get("tool_history", [])
        if tool_history:
            called_tools = set(item.get("tool") for item in tool_history)
            summary_parts.append(f"调用工具：{', '.join(sorted(called_tools))}")

        # 当前进度
        credentials_found = context.get("credentials_found", 0)
        if credentials_found > 0:
            summary_parts.append(f"发现凭证：{credentials_found} 个")

        # 错误信息
        if "last_error" in context:
            summary_parts.append(f"最近错误：{context['last_error']}")

        return "\n".join(summary_parts)

    def _estimate_tokens(self, context: Dict[str, Any]) -> int:
        """
        估算上下文的 token 数量

        Args:
            context: 上下文字典

        Returns:
            估算的 token 数量（粗略：1 token ≈ 4 字符）
        """
        # 将上下文转换为 JSON 字符串，估算 token 数
        try:
            json_str = json.dumps(context, ensure_ascii=False, default=str)
            # 粗略估算：1 token ≈ 4 字符
            return len(json_str) // 4
        except Exception:
            # 如果序列化失败，使用字段数量估算
            count = 0
            for value in context.values():
                if isinstance(value, (list, dict)):
                    count += len(value)
                else:
                    count += 1
            return count * 10  # 每个字段估算 10 token