"""
文件名过滤器模块 - 规则引擎过滤

职责：
1. 使用规则引擎过滤文件路径
2. 路径前缀排除（系统目录）
3. 扩展名黑名单排除

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

from typing import List, Dict
from datetime import datetime, timezone

from ..utils.rules import RuleEngine


class FilenameFilterResult:
    """文件名过滤结果"""

    def __init__(
        self,
        filtered_files: List[str],
        excluded_count: int,
        total_count: int
    ):
        self.filtered_files = filtered_files
        self.excluded_count = excluded_count
        self.total_count = total_count
        self.filtered_at = datetime.now(timezone.utc)

    @property
    def pass_rate(self) -> float:
        """通过率"""
        if self.total_count == 0:
            return 0.0
        return len(self.filtered_files) / self.total_count

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "filtered_files": self.filtered_files,
            "excluded_count": self.excluded_count,
            "total_count": self.total_count,
            "pass_count": len(self.filtered_files),
            "pass_rate": self.pass_rate,
            "filtered_at": self.filtered_at.isoformat()
        }


class FilenameFilter:
    """
    文件名过滤器 - 基于规则的过滤

    职责：
    1. 应用规则引擎过滤文件列表
    2. 路径前缀排除
    3. 扩展名黑名单排除
    """

    def __init__(self, rule_engine: RuleEngine):
        """
        初始化过滤器

        Args:
            rule_engine: 规则引擎实例
        """
        self.rule_engine = rule_engine

    def filter_files(self, files: List[str]) -> FilenameFilterResult:
        """
        过滤文件列表

        Args:
            files: 文件路径列表

        Returns:
            FilenameFilterResult: 过滤结果
        """
        filtered = self.rule_engine.filter_files(files)

        return FilenameFilterResult(
            filtered_files=filtered,
            excluded_count=len(files) - len(filtered),
            total_count=len(files)
        )
