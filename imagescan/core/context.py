"""
上下文管理器 - 构建动态上下文

职责：
1. 为 LLM 构建动态上下文部分
2. 生成执行轨迹摘要
3. 格式化工具执行结果

参考：docs/CONTEXT_OPTIMIZATION_DESIGN.md
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from enum import IntEnum

from ..utils.logger import get_logger

logger = get_logger(__name__)


class CompressionLevel(IntEnum):
    """压缩级别（保留用于压缩器）"""
    NONE = 0
    LIGHT = 1
    MEDIUM = 2
    HEAVY = 3


class ContextManager:
    """
    上下文管理器 - 构建动态上下文

    生成格式：
    ## 当前状态
    目标：扫描 xxx
    已执行步骤：5 / 30

    ## 执行轨迹 (L1 摘要)
    经过一系列动作 (docker.exists -> docker.save -> tar.unpack)，目前进展：解压完成，共 18 层。

    ## 最近工具执行明细
    调用了 tar.analyze_all_layer_files，发现了 28 个可疑文件。
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
        构建动态上下文部分（Dynamic Context）

        格式：
        ## 当前状态
        目标：扫描 xxx
        已执行步骤：5 / 30

        ## 执行轨迹 (L1 摘要)
        经过一系列动作 (docker.exists -> docker.save -> tar.unpack)，目前进展：解压完成，共 18 层。

        ## 最近工具执行明细
        调用了 tar.analyze_all_layer_files，发现了 28 个可疑文件。

        Args:
            full_context: 完整的上下文（self.context）
            max_tokens: 最大 token 限制（可选）

        Returns:
            格式化的动态上下文文本
        """
        parts = []

        # 1. 当前状态
        parts.append("## 当前状态")
        parts.append(f"目标：{full_context.get('goal', '扫描镜像')}")
        parts.append(f"已执行步骤：{full_context.get('current_step', 0)} / {full_context.get('max_steps', 30)}")
        parts.append(f"输出路径：{full_context.get('output_path', './output')}")

        # 2. 执行轨迹 (L1 摘要)
        trajectory = self._build_trajectory_summary(full_context)
        if trajectory:
            parts.append("\n## 执行轨迹")
            parts.append(trajectory)

        # 3. 最近工具执行明细
        if "last_tool" in full_context:
            parts.append("\n## 最近工具执行明细")
            detail = self._build_last_tool_detail(full_context)
            parts.append(detail)

        return "\n".join(parts)

    def _build_trajectory_summary(self, context: Dict) -> str:
        """
        生成执行轨迹摘要 (L1)

        格式：经过一系列动作 (docker.exists -> docker.save -> tar.unpack)，目前进展：解压完成，共 18 层。

        Args:
            context: 上下文字典

        Returns:
            轨迹摘要字符串
        """
        tool_history = context.get("tool_history", [])
        if not tool_history:
            return "初始化完成"

        # 提取最近执行的工具（最多 5 个）
        recent_tools = [op["tool"] for op in tool_history[-5:]]
        tool_sequence = " -> ".join(recent_tools)

        # 从最近的结果中提取进展信息
        last_result = context.get("last_result", {})
        progress = self._extract_progress_from_result(last_result)

        if progress:
            return f"经过一系列动作 ({tool_sequence})，目前进展：{progress}"
        else:
            return f"经过一系列动作 ({tool_sequence})"

    def _build_last_tool_detail(self, context: Dict) -> str:
        """
        生成最近工具执行明细

        格式：调用了 tar.analyze_all_layer_files，发现了 28 个可疑文件。

        Args:
            context: 上下文字典

        Returns:
            工具执行明细字符串
        """
        tool_name = context.get("last_tool", "")
        result = context.get("last_result", {})

        if not tool_name:
            return ""

        # 从 result 中提取摘要信息
        if isinstance(result, dict) and "summary" in result:
            summary = result["summary"]
            if isinstance(summary, list):
                summary = summary[0] if summary else ""
            # 清理 summary 中的表情符号和多余空格
            summary = str(summary).replace("✅ ", "").strip()
            return f"调用了 {tool_name}，{summary}"

        # 回退：从 data 中提取关键信息
        if isinstance(result, dict) and "data" in result:
            data = result["data"]
            if isinstance(data, dict):
                # 尝试提取统计信息
                if "statistics" in data:
                    stats = data["statistics"]
                    if "suspicious_files" in stats or "filtered_count" in stats:
                        count = stats.get("suspicious_files", stats.get("filtered_count", 0))
                        return f"调用了 {tool_name}，发现了 {count} 个可疑文件"
                    if "scanned_files" in stats:
                        return f"调用了 {tool_name}，已扫描 {stats['scanned_files']} 个文件"

        return f"调用了 {tool_name}，执行完成"

    def _extract_progress_from_result(self, result: Dict) -> str:
        """
        从工具结果中提取进展信息

        Args:
            result: 工具执行结果

        Returns:
            进展描述字符串
        """
        if not isinstance(result, dict):
            return ""

        data = result.get("data", {})
        if not isinstance(data, dict):
            return ""

        # 从 summary 提取
        if "summary" in result:
            summary = result["summary"]
            if isinstance(summary, list):
                summary = summary[0] if summary else ""
            summary = str(summary).replace("✅ ", "").strip()
            return summary

        # 从 data 提取
        if "layers_count" in data:
            return f"解压完成，共 {data['layers_count']} 层"
        if "size_mb" in data:
            return f"镜像保存完成 ({data['size_mb']:.2f} MB)"
        if "suspicious_files" in data:
            return f"筛选出 {data['suspicious_files']} 个可疑文件"
        if "statistics" in data:
            stats = data["statistics"]
            if "filtered_count" in stats:
                return f"筛选出 {stats['filtered_count']} 个可疑文件"

        return ""

    def reset_scan_state(self):
        """重置扫描状态（新任务开始时调用）"""
        pass  # 当前实现不需要状态重置
