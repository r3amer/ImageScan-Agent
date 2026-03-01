"""
文件名分析器模块

用途：
1. 批量分析镜像层中的文件名
2. 识别可能包含敏感凭证的文件
3. 应用过滤规则（基于配置）
4. 管理分析结果缓存

参考：docs/APP_FLOW.md
"""

import asyncio
from typing import Dict, List, Optional, Set
from datetime import datetime
from pathlib import Path

from .llm_client import get_llm_client, LLMClientError
from ..utils.logger import get_logger
from ..utils.config import get_config
from ..tools.file_tools import file_filter_paths

logger = get_logger(__name__)


class FilenameAnalysisResult:
    """文件名分析结果"""

    def __init__(
        self,
        layer_id: str,
        high_confidence: List[str],
        medium_confidence: List[str],
        low_confidence: List[str],
        filtered_out: int = 0
    ):
        self.layer_id = layer_id
        self.high_confidence = high_confidence
        self.medium_confidence = medium_confidence
        self.low_confidence = low_confidence
        self.filtered_out = filtered_out
        self.analyzed_at = datetime.utcnow()

    @property
    def total_candidates(self) -> int:
        """候选敏感文件总数"""
        return (
            len(self.high_confidence) +
            len(self.medium_confidence) +
            len(self.low_confidence)
        )

    @property
    def high_priority_files(self) -> List[str]:
        """高优先级文件（高 + 中置信度）"""
        return self.high_confidence + self.medium_confidence

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "layer_id": self.layer_id,
            "high_confidence": self.high_confidence,
            "medium_confidence": self.medium_confidence,
            "low_confidence": self.low_confidence,
            "filtered_out": self.filtered_out,
            "total_candidates": self.total_candidates,
            "analyzed_at": self.analyzed_at.isoformat()
        }


class FilenameAnalyzer:
    """
    文件名分析器

    职责：
    1. 过滤系统目录和低风险文件
    2. 批量分析文件名
    3. 缓存分析结果
    """

    def __init__(self):
        """初始化分析器"""
        self.config = get_config()
        self.llm_client = get_llm_client()
        self._cache: Dict[str, FilenameAnalysisResult] = {}

        # 获取过滤配置
        self.prefixes = self.config.filter_rules.prefix_exclude if hasattr(self.config, 'filter_rules') else []
        self.keywords = self.config.filter_rules.low_probability_keywords if hasattr(self.config, 'filter_rules') else []

    def _should_skip_path(self, path: str) -> bool:
        """
        判断是否应该跳过该路径

        Args:
            path: 文件路径

        Returns:
            是否跳过
        """
        # 使用 file_tools 的过滤函数
        # file_filter_paths 返回**通过过滤的文件列表**
        # 如果为空，说明文件被过滤掉了，应该跳过
        # 如果非空，说明文件通过了过滤，不应该跳过
        filtered = file_filter_paths(
            [path],
            prefix_exclude=self.prefixes,
            keywords_exclude=self.keywords
        )

        return len(filtered) == 0

    def _preprocess_filenames(
        self,
        filenames: List[str],
        layer_id: Optional[str] = None
    ) -> List[str]:
        """
        预处理文件名列表

        - 移除明显的系统目录
        - 应用配置的过滤规则
        - 标准化路径

        Args:
            filenames: 文件名列表
            layer_id: 层 ID

        Returns:
            过滤后的文件名列表
        """
        filtered: List[str] = []
        skipped = 0

        for filename in filenames:
            # 标准化路径
            normalized = filename.lstrip("/")

            # 检查是否应该跳过
            if self._should_skip_path(normalized):
                skipped += 1
                continue

            filtered.append(normalized)

        logger.debug(
            "文件名预处理完成",
            layer_id=layer_id,
            original_count=len(filenames),
            filtered_count=len(filtered),
            skipped_count=skipped
        )

        return filtered

    async def analyze_layer(
        self,
        filenames: List[str],
        layer_id: str,
        use_cache: bool = True
    ) -> FilenameAnalysisResult:
        """
        分析单个层的文件名

        Args:
            filenames: 文件名列表
            layer_id: 层 ID
            use_cache: 是否使用缓存

        Returns:
            分析结果
        """
        # 检查缓存
        if use_cache and layer_id in self._cache:
            logger.debug("使用缓存的分析结果", layer_id=layer_id)
            return self._cache[layer_id]

        logger.info(
            "开始分析文件名",
            layer_id=layer_id,
            filename_count=len(filenames)
        )

        # 预处理
        filtered_filenames = self._preprocess_filenames(filenames, layer_id)

        if not filtered_filenames:
            logger.info("过滤后无文件需要分析", layer_id=layer_id)
            result = FilenameAnalysisResult(
                layer_id=layer_id,
                high_confidence=[],
                medium_confidence=[],
                low_confidence=[],
                filtered_out=len(filenames)
            )
            self._cache[layer_id] = result
            return result

        # 调用 LLM 分析
        try:
            llm_result = await self.llm_client.analyze_filenames(
                filtered_filenames,
                layer_id=layer_id
            )

            # 构建结果
            result = FilenameAnalysisResult(
                layer_id=layer_id,
                high_confidence=llm_result.get("high_confidence", []),
                medium_confidence=llm_result.get("medium_confidence", []),
                low_confidence=llm_result.get("low_confidence", []),
                filtered_out=len(filenames) - len(filtered_filenames)
            )

            # 缓存结果
            self._cache[layer_id] = result

            logger.info(
                "文件名分析完成",
                layer_id=layer_id,
                high_count=len(result.high_confidence),
                medium_count=len(result.medium_confidence),
                low_count=len(result.low_confidence),
                total_candidates=result.total_candidates
            )

            return result

        except LLMClientError as e:
            logger.error(
                "文件名分析失败",
                layer_id=layer_id,
                error=str(e)
            )
            # 返回空结果
            return FilenameAnalysisResult(
                layer_id=layer_id,
                high_confidence=[],
                medium_confidence=[],
                low_confidence=[],
                filtered_out=len(filenames)
            )

    async def analyze_multiple_layers(
        self,
        layers: Dict[str, List[str]],
        max_concurrent: int = 5
    ) -> Dict[str, FilenameAnalysisResult]:
        """
        并发分析多个层

        Args:
            layers: {layer_id: filenames}
            max_concurrent: 最大并发数

        Returns:
            {layer_id: FilenameAnalysisResult}
        """
        logger.info(
            "开始批量分析文件名",
            layer_count=len(layers),
            max_concurrent=max_concurrent
        )

        # 创建信号量限制并发
        semaphore = asyncio.Semaphore(max_concurrent)

        async def analyze_single(layer_id: str, filenames: List[str]):
            async with semaphore:
                return await self.analyze_layer(filenames, layer_id)

        # 并发执行
        tasks = [
            analyze_single(layer_id, filenames)
            for layer_id, filenames in layers.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 组装结果字典
        result_dict: Dict[str, FilenameAnalysisResult] = {}
        for layer_id, result in zip(layers.keys(), results):
            if isinstance(result, Exception):
                logger.error(
                    "层分析失败",
                    layer_id=layer_id,
                    error=str(result)
                )
            else:
                result_dict[layer_id] = result

        # 统计
        total_candidates = sum(r.total_candidates for r in result_dict.values())
        total_high = sum(len(r.high_confidence) for r in result_dict.values())

        logger.info(
            "批量分析完成",
            layers_analyzed=len(result_dict),
            total_candidates=total_candidates,
            total_high_priority=total_high
        )

        return result_dict

    def get_high_priority_files(
        self,
        layer_results: Dict[str, FilenameAnalysisResult],
        threshold: str = "medium"
    ) -> Dict[str, List[str]]:
        """
        获取所有高优先级文件

        Args:
            layer_results: 层分析结果字典
            threshold: 置信度阈值（"high" 或 "medium"）

        Returns:
            {layer_id: [file_paths]}
        """
        result: Dict[str, List[str]] = {}

        for layer_id, analysis in layer_results.items():
            if threshold == "high":
                files = analysis.high_confidence
            else:  # medium
                files = analysis.high_priority_files

            if files:
                result[layer_id] = files

        return result

    def clear_cache(self, layer_id: Optional[str] = None):
        """
        清除缓存

        Args:
            layer_id: 指定层 ID（None 表示清除全部）
        """
        if layer_id:
            self._cache.pop(layer_id, None)
            logger.debug("清除缓存", layer_id=layer_id)
        else:
            self._cache.clear()
            logger.debug("清除所有缓存")

    def get_cache_stats(self) -> Dict:
        """获取缓存统计"""
        return {
            "cached_layers": len(self._cache),
            "cached_layer_ids": list(self._cache.keys())
        }


# 全局文件名分析器实例（延迟加载）
_global_analyzer: Optional[FilenameAnalyzer] = None


def get_filename_analyzer() -> FilenameAnalyzer:
    """
    获取全局文件名分析器实例（单例模式）

    Returns:
        文件名分析器实例
    """
    global _global_analyzer
    if _global_analyzer is None:
        _global_analyzer = FilenameAnalyzer()
    return _global_analyzer
