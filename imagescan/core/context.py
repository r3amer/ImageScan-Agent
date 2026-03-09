"""
上下文管理器 - 统一的上下文管理

职责：
1. 构建 L0/L1/L2 三层上下文
2. 协调压缩器和记忆存储
3. 为 LLM 提供优化的 prompt

参考：docs/CONTEXT_OPTIMIZATION_DESIGN.md
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from enum import IntEnum

from ..utils.logger import get_logger

logger = get_logger(__name__)


class CompressionLevel(IntEnum):
    """压缩级别"""
    NONE = 0     # 无压缩：使用 L2 完整上下文
    LIGHT = 1    # 轻度压缩：使用 L1 概述层
    MEDIUM = 2   # 中度压缩：L1 + 生成摘要
    HEAVY = 3    # 深度压缩：仅 L0 摘要


class ContextManager:
    """
    上下文管理器 - 统一的上下文管理

    职责：
    1. 根据压缩级别选择合适的上下文层级
    2. 协调压缩器和记忆存储
    3. 为 LLM 构建优化的 prompt
    """

    def __init__(self, config, memory_store=None):
        """
        初始化上下文管理器

        Args:
            config: 配置对象
            memory_store: 记忆存储（可选）
        """
        self.config = config
        self.memory_store = memory_store

        # 上下文状态
        self._scan_plan_sent = False  # scan_plan 是否已发送

        # 延迟导入，避免循环引用
        self._compressor = None

    @property
    def compressor(self):
        """延迟加载压缩器"""
        if self._compressor is None:
            from .compression import ContextCompressor
            self._compressor = ContextCompressor(self.config)
        return self._compressor

    async def build_prompt_context(
        self,
        full_context: Dict[str, Any],
        max_tokens: Optional[int] = None
    ) -> str:
        """
        构建发送给 LLM 的 prompt

        策略：
        1. 检查是否需要压缩
        2. 根据 compression_level 选择分层
        3. 从 memory_store 加载相关知识

        Args:
            full_context: 完整的上下文（self.context）
            max_tokens: 最大 token 限制（可选）

        Returns:
            格式化的 prompt 文本
        """
        # 1. 检查压缩级别
        level = self.compressor.get_compression_level(full_context, max_tokens)

        # 2. 加载历史记忆（如果有）
        memories = {}
        if self.memory_store:
            memories = await self.memory_store.get_relevant_memories(full_context)

        # 3. 根据压缩级别构建 prompt
        if level == CompressionLevel.HEAVY:
            prompt = self._build_l0_context(full_context, memories)
            logger.info("使用 L0 上下文（摘要）", level="HEAVY")
        elif level == CompressionLevel.MEDIUM:
            prompt = self._build_l1_context_with_summary(full_context, memories)
            logger.info("使用 L1 上下文（概述+摘要）", level="MEDIUM")
        elif level == CompressionLevel.LIGHT:
            prompt = self._build_l1_context(full_context, memories)
            logger.info("使用 L1 上下文（概述）", level="LIGHT")
        else:  # NONE
            prompt = self._build_l2_context(full_context, memories)
            logger.debug("使用 L2 上下文（详情）", level="NONE")

        return prompt

    def _build_l0_context(self, context: Dict, memories: Dict) -> str:
        """
        L0: 一句话摘要

        仅在 Token 紧张时使用，包含最关键的信息
        """
        parts = []

        # 当前状态
        current_state = context.get("current_state", "unknown")
        current_step = context.get("current_step", 0)
        max_steps = context.get("max_steps", 30)

        # 已发现凭证
        credentials_found = context.get("credentials_found", 0)

        parts.append(f"**当前状态**: {current_state}")
        parts.append(f"**进度**: {current_step}/{max_steps}")
        if credentials_found > 0:
            parts.append(f"**已发现**: {credentials_found} 个凭证")

        # 添加记忆信息（如果有）
        if memories.get("image_history"):
            history = memories["image_history"]
            if history.get("last_scan"):
                parts.append(f"**历史参考**: 上次扫描发现 {history.get('credentials_count', 0)} 个凭证")

        return "\n".join(parts)

    def _build_l1_context(self, context: Dict, memories: Dict) -> str:
        """
        L1: 结构化关键信息（概述层）

        正常情况下使用的层级，包含任务状态、扫描统计、最近工具
        """
        parts = []

        # 1. 当前状态
        parts.append("## 当前状态")
        parts.append(f"目标：{context['goal']}")
        parts.append(f"已执行步骤：{context.get('current_step', 0)} / {context.get('max_steps', 30)}")
        parts.append(f"当前阶段：{context.get('current_state', 'initialized')}")

        # 2. 扫描计划（只发送一次）
        if "scan_plan" in context and not self._scan_plan_sent:
            parts.append("\n## 扫描计划")
            parts.append(f"{context['scan_plan']}")
            self._scan_plan_sent = True

        # 3. 扫描统计（如果有）
        stats = self._extract_scan_statistics(context)
        if stats:
            parts.append("\n## 扫描统计")
            for key, value in stats.items():
                parts.append(f"- {key}: {value}")

        # 4. 最近工具（只保留 3 个，只显示 summary）
        if "last_tool" in context:
            parts.append(f"\n## 最近执行的工具：{context['last_tool']}")
            formatted = self._format_tool_result(
                context['last_tool'],
                context.get('last_result', {})
            )
            parts.extend(formatted)

        # 5. 记忆信息（如果有）
        memory_info = self._format_memories(memories)
        if memory_info:
            parts.append("\n## 历史参考")
            parts.extend(memory_info)

        return "\n".join(parts)

    def _build_l1_context_with_summary(self, context: Dict, memories: Dict) -> str:
        """
        L1: 概述 + 压缩摘要

        中度压缩时使用，包含 L1 信息 + 生成的摘要
        """
        # 先压缩上下文
        compressed = self.compressor.compress(context, CompressionLevel.MEDIUM)

        # 构建 L1 上下文
        l1_context = self._build_l1_context(compressed, memories)

        # 添加摘要
        summary = self.compressor.generate_summary(context)

        return f"{summary}\n\n{l1_context}"

    def _build_l2_context(self, context: Dict, memories: Dict) -> str:
        """
        L2: 完整上下文（详情层）

        仅在需要详细信息时使用，包含完整的上下文和最近操作详情
        """
        parts = []

        # 基础状态
        parts.append("## 当前状态")
        parts.append(f"目标：{context['goal']}")
        parts.append(f"已执行步骤：{context.get('current_step', 0)} / {context.get('max_steps', 30)}")
        parts.append(f"当前阶段：{context.get('current_state', 'initialized')}")

        # 扫描计划（只发送一次）
        if "scan_plan" in context and not self._scan_plan_sent:
            parts.append("\n## 扫描计划")
            parts.append(f"{context['scan_plan']}")
            self._scan_plan_sent = True

        # 最近工具执行结果（完整 data）
        if "last_tool" in context:
            parts.append(f"\n## 最近执行的工具：{context['last_tool']}")
            result = context.get('last_result', {})
            parts.append(f"结果：{result.get('summary', 'No summary')}")

            # 显示 data 中的键（如果有）
            if "data" in result and isinstance(result["data"], dict):
                data_keys = list(result["data"].keys())[:5]
                parts.append(f"数据字段：{', '.join(data_keys)}")

        # 工具执行历史（最近 3 个）
        if "tool_history" in context and context["tool_history"]:
            history = context["tool_history"][-3:]
            parts.append("\n## 工具执行历史（最近 3 次）")
            for i, item in enumerate(history, 1):
                parts.append(f"{i}. {item['tool']}")
                parts.append(f"   参数：{self._safe_json(item.get('parameters', {}))}")
                # 结果预览
                result_preview = str(item.get('result', {}))[:200]
                parts.append(f"   结果：{result_preview}...")

        # 错误历史（最近 2 个）
        if "error_history" in context and context["error_history"]:
            errors = context["error_history"][-2:]
            parts.append("\n## 最近的错误")
            for item in errors:
                parts.append(f"- {item.get('tool', 'unknown')}: {item.get('error', 'unknown')}")

        # 记忆信息
        memory_info = self._format_memories(memories)
        if memory_info:
            parts.append("\n## 历史参考")
            parts.extend(memory_info)

        return "\n".join(parts)

    def _extract_scan_statistics(self, context: Dict) -> Dict[str, Any]:
        """从上下文中提取扫描统计信息"""
        stats = {}

        # 从 storage 获取统计
        # 这里假设 storage 可以通过其他方式访问
        # 在实际集成时，需要注入 storage 引用

        return stats

    def _format_tool_result(self, tool_name: str, result: Dict) -> List[str]:
        """
        格式化工具结果

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            格式化的输出行列表
        """
        if isinstance(result, dict) and "summary" in result:
            summary = result["summary"]
            if isinstance(summary, list):
                return [str(line) for line in summary]
            return [str(summary)]

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("error", "执行失败")
            return [f"❌ {tool_name} 执行失败：{error_msg}"]

        return [f"✅ {tool_name} 执行完成"]

    def _format_memories(self, memories: Dict) -> List[str]:
        """
        格式化记忆信息

        Args:
            memories: 记忆数据

        Returns:
            格式化的输出行列表
        """
        if not memories:
            return []

        lines = []

        if "image_history" in memories:
            history = memories["image_history"]
            if history:
                last_scan = history.get("last_scan")
                if last_scan:
                    # 处理 last_scan 可能是字符串的情况（SQLite 返回的 naive datetime）
                    if isinstance(last_scan, str):
                        try:
                            # SQLite 返回的是 naive datetime 字符串，需要转换为 aware
                            naive_dt = datetime.fromisoformat(last_scan)
                            # 假设存储的是 UTC 时间，添加时区信息
                            last_scan = naive_dt.replace(tzinfo=timezone.utc)
                        except (ValueError, AttributeError):
                            # 如果解析失败，只显示凭证数量，不计算时间
                            lines.append(f"- 该镜像有历史扫描记录，发现 {history.get('credentials_count', 0)} 个凭证")
                            last_scan = None  # 标记为无效，跳过后续时间计算

                    if last_scan is not None:  # 只有在有效时才计算时间差
                        days_ago = (datetime.now(timezone.utc) - last_scan).days
                        if days_ago == 0:
                            time_str = "今天"
                        elif days_ago == 1:
                            time_str = "昨天"
                        else:
                            time_str = f"{days_ago} 天前"
                        lines.append(f"- 该镜像上次扫描于 {time_str}，发现 {history.get('credentials_count', 0)} 个凭证")

        if "false_positive_patterns" in memories:
            patterns = memories["false_positive_patterns"]
            if patterns:
                lines.append(f"- 已知误报模式：{len(patterns)} 个")
                # 只显示前 3 个
                for pattern in list(patterns.keys())[:3]:
                    lines.append(f"  • {pattern}")

        return lines

    def _safe_json(self, obj: Any) -> str:
        """安全的 JSON 序列化"""
        try:
            import json
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return str(obj)

    def reset_scan_state(self):
        """重置扫描状态（新任务开始时调用）"""
        self._scan_plan_sent = False