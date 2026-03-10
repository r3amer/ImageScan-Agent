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

        关键：不只是控制显示，而是主动删除不需要的数据

        Args:
            context: 原始上下文
            level: 目标压缩级别

        Returns:
            压缩后的上下文（新字典，不修改原 context）
        """
        if level == CompressionLevel.NONE:
            return context

        # 创建压缩后的副本（避免修改原始上下文）
        compressed = context.copy()

        if level >= CompressionLevel.LIGHT:
            # 🔥 关键：主动清理 tool_history，只保留需要的数量
            if "tool_history" in compressed:
                # L1: 只保留最近 3 次，并压缩为摘要
                compressed["tool_history"] = self._compress_tool_history(
                    compressed["tool_history"],
                    keep_count=3,
                    keep_detail=False  # 只保留摘要，不保留完整参数
                )

        if level >= CompressionLevel.MEDIUM:
            # MEDIUM: 只保留最近 2 次的摘要
            if "tool_history" in compressed:
                compressed["tool_history"] = self._compress_tool_history(
                    compressed["tool_history"],
                    keep_count=2,
                    keep_detail=False
                )
            # 清理 error_history（只保留最近 1 个）
            if "error_history" in compressed:
                compressed["error_history"] = compressed["error_history"][-1:]

        if level == CompressionLevel.HEAVY:
            # 🔥 HEAVY: 清空 tool_history，只保留统计信息
            if "tool_history" in compressed:
                compressed["tool_history"] = []
            # 只保留最关键的信息
            compressed = {
                "current_state": compressed.get("current_state"),
                "current_step": compressed.get("current_step"),
                "max_steps": compressed.get("max_steps"),
                "credentials_found": compressed.get("credentials_found", 0),
                "last_error": compressed.get("last_error"),
                "goal": compressed.get("goal"),
                "image_name": compressed.get("image_name")
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

    def _compress_tool_history(
        self,
        history: List[Dict],
        keep_count: int,
        keep_detail: bool
    ) -> List[Dict]:
        """
        压缩工具历史

        Args:
            history: 原始历史
            keep_count: 保留条数
            keep_detail: 是否保留完整参数（True=保留，False=只保留摘要）

        Returns:
            压缩后的历史
        """
        if not history:
            return []

        # 只保留最近 N 次
        compressed = history[-keep_count:]

        if not keep_detail:
            # 只保留摘要，删除完整参数和结果
            for item in compressed:
                # 保存参数摘要
                item["parameters_summary"] = self._summarize_parameters(
                    item.get("parameters", {})
                )
                # 保存结果摘要
                item["result_summary"] = self._summarize_result(
                    item.get("result", {})
                )
                # 删除详细数据（减少内存占用）
                item.pop("parameters", None)
                item.pop("result", None)

        return compressed

    def _summarize_parameters(self, parameters: Dict) -> str:
        """
        将参数摘要为短字符串

        Args:
            parameters: 工具参数

        Returns:
            参数摘要字符串
        """
        if not parameters:
            return "无参数"

        # 只保留关键参数名和值（截断）
        items = []
        for key, value in list(parameters.items())[:5]:
            value_str = str(value)
            if len(value_str) > 30:
                value_str = value_str[:30] + "..."
            items.append(f"{key}={value_str}")

        return ", ".join(items)

    def _summarize_result(self, result: Dict) -> str:
        """
        将结果摘要为短字符串

        Args:
            result: 工具执行结果

        Returns:
            结果摘要字符串
        """
        if not result:
            return "无结果"

        # 优先使用 summary 字段
        if "summary" in result:
            summary = result["summary"]
            if isinstance(summary, list):
                return summary[0] if summary else ""
            return str(summary)

        # 回退：使用 success 状态
        if result.get("success"):
            return "执行成功"
        elif result.get("success") is False:
            return f"执行失败: {result.get('error', '未知错误')}"

        return "完成"

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