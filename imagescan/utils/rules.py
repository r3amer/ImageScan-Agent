"""
规则引擎 - 文件路径和扩展名过滤

职责：
- 路径前缀过滤（排除系统目录）
- 扩展名黑名单过滤（排除媒体、压缩包等）
"""

import os
from typing import List, Optional

# 全局 RuleEngine 实例（用于工具调用）
# 使用字符串作为类型提示（forward reference）
_rule_engine_instance: Optional["RuleEngine"] = None


class RuleEngine:
    """
    规则引擎

    用于过滤不需要扫描的文件
    """

    def __init__(self, config):
        """
        初始化规则引擎

        Args:
            config: 配置对象，需要包含 filter_rules 属性
        """
        # 从配置中获取规则
        self.prefix_exclude = config.filter_rules.prefix_exclude
        self.extension_blacklist = config.filter_rules.extension_blacklist

    def filter_files(self, files: List[str]) -> List[str]:
        """
        过滤文件列表

        应用规则：
        1. 路径前缀排除（优先）
        2. 扩展名黑名单排除
        3. 跳过错误文件

        Args:
            files: 文件路径列表

        Returns:
            过滤后的文件路径列表
        """
        filtered = []

        for file_path in files:
            try:
                # 1. 路径前缀过滤
                if self._match_prefix_exclude(file_path):
                    continue

                # 2. 扩展名黑名单过滤
                if self._match_extension_blacklist(file_path):
                    continue

                # 通过所有过滤规则
                filtered.append(file_path)

            except Exception:
                # 3. 跳过错误文件，继续处理
                # 不抛出异常，保证流程继续
                continue

        return filtered

    def _match_prefix_exclude(self, file_path: str) -> bool:
        """
        检查文件路径是否匹配前缀排除规则

        Args:
            file_path: 文件路径

        Returns:
            True: 应该排除
            False: 不排除
        """
        for prefix in self.prefix_exclude:
            if file_path.startswith(prefix):
                return True
        return False

    def _match_extension_blacklist(self, file_path: str) -> bool:
        """
        检查文件扩展名是否在黑名单中

        大小写不敏感

        Args:
            file_path: 文件路径

        Returns:
            True: 应该排除
            False: 不排除
        """
        # 提取扩展名
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()  # 转为小写，实现大小写不敏感

        return ext in self.extension_blacklist


def set_rule_engine_instance(engine: RuleEngine):
    """设置全局 RuleEngine 实例"""
    global _rule_engine_instance
    _rule_engine_instance = engine


def get_rule_engine_instance() -> Optional[RuleEngine]:
    """获取全局 RuleEngine 实例"""
    return _rule_engine_instance


# 工具函数：注册到 ToolRegistry
# 注意：需要延迟导入 registry，避免循环依赖
def _filter_files_tool(files: List[str]) -> List[str]:
    """
    工具函数：使用规则引擎过滤文件列表

    参数：files(文件路径列表)
    返回：过滤后的文件路径列表
    """
    engine = get_rule_engine_instance()
    if engine is None:
        # 如果没有初始化，直接返回原列表
        return files
    return engine.filter_files(files)


def register_rule_engine_tools():
    """注册规则引擎工具到 ToolRegistry"""
    from ..tools.registry import registry

    registry.register(
        "rule_engine.filter_files",
        description="使用规则过滤文件列表（路径前缀 + 扩展名黑名单）。参数：files(文件路径列表)。返回：过滤后的文件路径列表"
    )(_filter_files_tool)
