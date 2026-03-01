"""
文件名分析器模块

用途：
1. 批量分析镜像层中的文件名
2. 识别可能包含敏感凭证的文件
3. 应用过滤规则（基于配置）
4. 管理分析结果缓存
5. 三层筛选优化：扩展名黑名单过滤

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


class FileExtensionFilter:
    """
    文件扩展名过滤器（三层筛选的第一层）

    作用：
    - 快速过滤明显的非文本文件
    - 降低 LLM token 消耗
    - 提高扫描效率
    """

    # 黑名单扩展名（这些文件类型几乎不可能包含凭证）
    BLACKLIST_EXTENSIONS = {
        # 媒体文件
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp',
        '.mp4', '.mp3', '.avi', '.mov', '.wav', '.flac', '.ogg', '.wmv',
        '.ttf', '.woff', '.woff2', '.otf', '.eot', '.woff1',
        # 压缩文件
        '.zip', '.tar', '.gz', '.rar', '.7z', '.bz2', '.xz', '.lzma', '.zst',
        # 系统库和二进制
        '.so', '.so.1', '.so.2', '.so.3', '.so.4', '.so.5', '.so.6', '.so.7',
        '.a', '.lib', '.dll', '.exe', '.bin', '.dylib', '.o', '.obj',
        # 编译后的代码
        '.pyc', '.pyo', '.class', '.jar', '.war', '.ear', '.swf', '.dex',
        # 其他非文本
        '.pdf', '.ps', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.db', '.sqlite', '.mdb',
    }

    # 白名单扩展名（这些文件类型很可能包含凭证）
    WHITELIST_EXTENSIONS = {
        # 环境和配置文件
        '.env', '.pem', '.key', '.p12', '.jks', '.cer', '.crt', '.der',
        '.config', '.conf', '.json', '.yaml', '.yml', '.xml', '.toml',
        '.properties', '.ini', '.cfg', '.settings', '.params',
        # 代码文件
        '.txt', '.log', '.sql', '.sh', '.bash', '.zsh', '.fish',
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.c', '.cpp', '.h', '.hpp',
        '.php', '.rb', '.pl', '.lua', '.r', '.scala', '.kt', '.swift',
        # 模板和构建文件
        '.template', '.tpl', '.j2', '.jinja2', '.erb', '.mustache',
        'Makefile', 'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
        '.gradle', '.mvn', 'pom.xml', 'build.gradle', 'setup.py', 'requirements.txt',
        # Web 相关
        '.html', '.htm', '.css', '.scss', '.sass', '.less',
        # 版本控制
        '.gitignore', '.gitattributes', '.gitmodules',
        # CI/CD
        '.gitlab-ci.yml', '.travis.yml', 'jenkins.yml', 'circleci',
        # 其他
        '.md', '.rst', '.adoc',
    }

    @classmethod
    def _get_extension(cls, filename: str) -> str:
        """
        获取文件扩展名

        Args:
            filename: 文件名

        Returns:
            扩展名（包含点号，如 ".txt"）
        """
        # 处理复合扩展名（如 .tar.gz）
        if filename.endswith('.tar.gz') or filename.endswith('.tar.bz2') or filename.endswith('.tar.xz'):
            return filename[filename.rfind('.tar.'):]
        # 处理双重扩展名（如 .min.js）
        parts = filename.rsplit('.', 2)
        if len(parts) >= 3 and len(parts[-2]) <= 4:
            return f'.{parts[-2]}.{parts[-1]}'
        # 普通扩展名
        return Path(filename).suffix.lower()

    def filter_by_extension(
        self,
        filenames: List[str]
    ) -> Dict[str, List[str]]:
        """
        根据扩展名过滤文件

        Args:
            filenames: 文件名列表

        Returns:
            {
                'high_priority': 白名单文件（高优先级）,
                'medium_priority': 未在黑名单也未在白名单（中等优先级）,
                'low_priority': 其他文件（低优先级）,
                'filtered_out': 黑名单文件（已过滤）,
                'stats': 统计信息
            }
        """
        high_priority = []
        medium_priority = []
        low_priority = []
        blacklisted = []

        for filename in filenames:
            ext = self._get_extension(filename)

            if ext in self.BLACKLIST_EXTENSIONS:
                blacklisted.append(filename)
            elif ext in self.WHITELIST_EXTENSIONS:
                high_priority.append(filename)
            elif ext:  # 有扩展名但不在白名单
                medium_priority.append(filename)
            else:  # 无扩展名
                low_priority.append(filename)

        stats = {
            'total': len(filenames),
            'high_priority': len(high_priority),
            'medium_priority': len(medium_priority),
            'low_priority': len(low_priority),
            'filtered_out': len(blacklisted),
            'filter_rate': len(blacklisted) / len(filenames) if filenames else 0
        }

        return {
            'high_priority': high_priority,
            'medium_priority': medium_priority,
            'low_priority': low_priority,
            'filtered_out': blacklisted,
            'stats': stats
        }


class FilenameAnalysisResult:
    """文件名分析结果"""

    def __init__(
        self,
        layer_id: str,
        high_confidence: List[str],
        medium_confidence: List[str],
        low_confidence: List[str],
        filtered_out: int = 0,
        extension_filtered_out: int = 0,
        filter_stats: Optional[Dict] = None
    ):
        self.layer_id = layer_id
        self.high_confidence = high_confidence
        self.medium_confidence = medium_confidence
        self.low_confidence = low_confidence
        self.filtered_out = filtered_out
        self.extension_filtered_out = extension_filtered_out
        self.filter_stats = filter_stats or {}
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
            "extension_filtered_out": self.extension_filtered_out,
            "total_filtered_out": self.filtered_out + self.extension_filtered_out,
            "total_candidates": self.total_candidates,
            "filter_stats": self.filter_stats,
            "analyzed_at": self.analyzed_at.isoformat()
        }


class FilenameAnalyzer:
    """
    文件名分析器

    职责：
    1. 过滤系统目录和低风险文件
    2. 批量分析文件名
    3. 缓存分析结果
    4. 三层筛选：扩展名过滤
    """

    def __init__(self):
        """初始化分析器"""
        self.config = get_config()
        self.llm_client = get_llm_client()
        self._cache: Dict[str, FilenameAnalysisResult] = {}

        # 获取过滤配置
        self.prefixes = self.config.filter_rules.prefix_exclude if hasattr(self.config, 'filter_rules') else []
        self.keywords = self.config.filter_rules.low_probability_keywords if hasattr(self.config, 'filter_rules') else []

        # 初始化扩展名过滤器（三层筛选第一层）
        self.extension_filter = FileExtensionFilter()

        # 检查是否启用三层筛选
        self.three_layer_enabled = (
            hasattr(self.config, 'three_layer_filtering') and
            getattr(self.config.three_layer_filtering, 'enabled', False)
        )

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
    ) -> tuple[List[str], Dict]:
        """
        预处理文件名列表

        - 移除明显的系统目录
        - 应用配置的过滤规则
        - 标准化路径
        - 三层筛选第一层：扩展名过滤

        Args:
            filenames: 文件名列表
            layer_id: 层 ID

        Returns:
            (过滤后的文件名列表, 过滤统计信息)
        """
        # 第一层：扩展名过滤（如果启用）
        extension_stats = {}
        if self.three_layer_enabled:
            filter_result = self.extension_filter.filter_by_extension(filenames)

            # 只保留未在黑名单中的文件
            # 将高、中、低优先级合并
            candidates = (
                filter_result['high_priority'] +
                filter_result['medium_priority'] +
                filter_result['low_priority']
            )
            extension_stats = filter_result['stats']

            logger.info(
                "扩展名过滤完成",
                layer_id=layer_id,
                total=extension_stats['total'],
                high_priority=extension_stats['high_priority'],
                medium_priority=extension_stats['medium_priority'],
                low_priority=extension_stats['low_priority'],
                filtered_out=extension_stats['filtered_out'],
                filter_rate=f"{extension_stats['filter_rate']:.2%}"
            )
        else:
            candidates = filenames

        # 第二步：路径前缀和关键词过滤
        filtered: List[str] = []
        skipped = 0

        for filename in candidates:
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
            extension_filtered_out=extension_stats.get('filtered_out', 0),
            path_filtered_out=skipped,
            final_count=len(filtered)
        )

        return filtered, extension_stats

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

        # 预处理（包含扩展名过滤）
        filtered_filenames, extension_stats = self._preprocess_filenames(filenames, layer_id)

        if not filtered_filenames:
            logger.info("过滤后无文件需要分析", layer_id=layer_id)
            result = FilenameAnalysisResult(
                layer_id=layer_id,
                high_confidence=[],
                medium_confidence=[],
                low_confidence=[],
                filtered_out=len(filenames),
                extension_filtered_out=extension_stats.get('filtered_out', 0),
                filter_stats=extension_stats
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
                filtered_out=len(filenames) - len(filtered_filenames),
                extension_filtered_out=extension_stats.get('filtered_out', 0),
                filter_stats=extension_stats
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
                filtered_out=len(filenames),
                extension_filtered_out=extension_stats.get('filtered_out', 0),
                filter_stats=extension_stats
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
