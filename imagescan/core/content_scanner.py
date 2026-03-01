"""
内容扫描器模块

用途：
1. 扫描文件内容，检测敏感凭证
2. 批量处理多个文件
3. 聚合扫描结果
4. 管理扫描状态和进度

参考：docs/APP_FLOW.md
"""

import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from .llm_client import get_llm_client, LLMClientError
from ..utils.logger import get_logger
from ..models.credential import Credential, CredentialType, ValidationStatus

logger = get_logger(__name__)


class FileScanResult:
    """单个文件扫描结果"""

    def __init__(
        self,
        file_path: str,
        layer_id: str,
        credentials: List[Dict[str, Any]],
        scan_error: Optional[str] = None
    ):
        self.file_path = file_path
        self.layer_id = layer_id
        self.credentials = credentials
        self.scan_error = scan_error
        self.scanned_at = datetime.utcnow()

    @property
    def has_credentials(self) -> bool:
        """是否发现凭证"""
        return len(self.credentials) > 0

    @property
    def success(self) -> bool:
        """扫描是否成功"""
        return self.scan_error is None

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "file_path": self.file_path,
            "layer_id": self.layer_id,
            "credentials": self.credentials,
            "has_credentials": self.has_credentials,
            "credential_count": len(self.credentials),
            "scan_error": self.scan_error,
            "scanned_at": self.scanned_at.isoformat()
        }


class ContentScanner:
    """
    内容扫描器

    职责：
    1. 读取文件内容
    2. 调用 LLM 扫描敏感凭证
    3. 聚合扫描结果
    4. 追踪扫描进度
    """

    def __init__(self):
        """初始化扫描器"""
        self.llm_client = get_llm_client()
        self._scanned_files: Dict[str, FileScanResult] = {}

    async def _read_file_content(self, file_path: str) -> str:
        """
        读取文件内容

        Args:
            file_path: 文件路径

        Returns:
            文件内容

        Raises:
            FileNotFoundError: 文件不存在
            IOError: 读取失败
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 限制文件大小（1MB）
        max_size = 1024 * 1024
        file_size = path.stat().st_size

        if file_size > max_size:
            logger.warning(
                "文件过大，只读取部分内容",
                file_path=file_path,
                file_size=file_size,
                max_size=max_size
            )

        # 读取文件内容
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                # 读取前 max_size 字节
                content = f.read(max_size)
                return content
        except Exception as e:
            logger.error("文件读取失败", file_path=file_path, error=str(e))
            raise IOError(f"无法读取文件 {file_path}: {e}")

    async def scan_file(
        self,
        file_path: str,
        layer_id: str,
        use_cache: bool = True
    ) -> FileScanResult:
        """
        扫描单个文件

        Args:
            file_path: 文件路径
            layer_id: 层 ID
            use_cache: 是否使用缓存

        Returns:
            扫描结果
        """
        # 检查缓存
        cache_key = f"{layer_id}:{file_path}"
        if use_cache and cache_key in self._scanned_files:
            logger.debug("使用缓存的扫描结果", file_path=file_path)
            return self._scanned_files[cache_key]

        logger.debug("开始扫描文件", file_path=file_path, layer_id=layer_id)

        try:
            # 读取文件内容
            content = await self._read_file_content(file_path)

            if not content or not content.strip():
                logger.debug("文件为空，跳过扫描", file_path=file_path)
                result = FileScanResult(
                    file_path=file_path,
                    layer_id=layer_id,
                    credentials=[]
                )
                self._scanned_files[cache_key] = result
                return result

            # 调用 LLM 扫描
            credentials = await self.llm_client.analyze_file_contents(
                file_path=file_path,
                content=content,
                layer_id=layer_id
            )

            result = FileScanResult(
                file_path=file_path,
                layer_id=layer_id,
                credentials=credentials
            )

            # 缓存结果
            self._scanned_files[cache_key] = result

            if result.has_credentials:
                logger.info(
                    "文件中发现凭证",
                    file_path=file_path,
                    layer_id=layer_id,
                    credential_count=len(credentials)
                )

            return result

        except (FileNotFoundError, IOError) as e:
            logger.warning(
                "文件扫描失败（IO错误）",
                file_path=file_path,
                error=str(e)
            )
            result = FileScanResult(
                file_path=file_path,
                layer_id=layer_id,
                credentials=[],
                scan_error=str(e)
            )
            return result

        except LLMClientError as e:
            logger.error(
                "文件扫描失败（LLM错误）",
                file_path=file_path,
                error=str(e)
            )
            result = FileScanResult(
                file_path=file_path,
                layer_id=layer_id,
                credentials=[],
                scan_error=str(e)
            )
            return result

    async def scan_multiple_files(
        self,
        files: List[Dict[str, str]],
        max_concurrent: int = 10,
        progress_callback: Optional[callable] = None
    ) -> List[FileScanResult]:
        """
        批量扫描多个文件

        Args:
            files: 文件列表，格式：[{"file_path": "...", "layer_id": "..."}]
            max_concurrent: 最大并发数
            progress_callback: 进度回调函数

        Returns:
            扫描结果列表
        """
        logger.info(
            "开始批量扫描文件",
            file_count=len(files),
            max_concurrent=max_concurrent
        )

        # 创建信号量限制并发
        semaphore = asyncio.Semaphore(max_concurrent)

        total_files = len(files)
        completed_count = 0

        async def scan_single(file_info: Dict[str, str]):
            nonlocal completed_count

            async with semaphore:
                result = await self.scan_file(
                    file_info["file_path"],
                    file_info["layer_id"]
                )

                completed_count += 1

                # 调用进度回调
                if progress_callback:
                    await progress_callback(completed_count, total_files, result)

                return result

        # 并发执行
        tasks = [scan_single(f) for f in files]
        results = await asyncio.gather(*tasks)

        # 统计
        successful_scans = sum(1 for r in results if r.success)
        files_with_credentials = sum(1 for r in results if r.has_credentials)
        total_credentials = sum(len(r.credentials) for r in results)

        logger.info(
            "批量扫描完成",
            total_files=total_files,
            successful=successful_scans,
            with_credentials=files_with_credentials,
            total_credentials=total_credentials
        )

        return results

    def aggregate_results(
        self,
        scan_results: List[FileScanResult]
    ) -> Dict[str, Any]:
        """
        聚合扫描结果

        Args:
            scan_results: 扫描结果列表

        Returns:
            聚合统计
        """
        all_credentials: List[Dict[str, Any]] = []

        for result in scan_results:
            if result.has_credentials:
                all_credentials.extend(result.credentials)

        # 按置信度分组
        high_conf = [c for c in all_credentials if c.get("confidence", 0) >= 0.8]
        medium_conf = [c for c in all_credentials if 0.5 <= c.get("confidence", 0) < 0.8]
        low_conf = [c for c in all_credentials if c.get("confidence", 0) < 0.5]

        # 按类型分组
        by_type: Dict[str, int] = {}
        for cred in all_credentials:
            cred_type = cred.get("cred_type", "UNKNOWN")
            by_type[cred_type] = by_type.get(cred_type, 0) + 1

        # 按层分组
        by_layer: Dict[str, int] = {}
        for cred in all_credentials:
            layer_id = cred.get("layer_id", "unknown")
            by_layer[layer_id] = by_layer.get(layer_id, 0) + 1

        aggregation = {
            "total_credentials": len(all_credentials),
            "by_confidence": {
                "high": len(high_conf),
                "medium": len(medium_conf),
                "low": len(low_conf)
            },
            "by_type": by_type,
            "by_layer": by_layer,
            "files_scanned": len(scan_results),
            "files_with_credentials": sum(1 for r in scan_results if r.has_credentials)
        }

        logger.info(
            "结果聚合完成",
            total_credentials=aggregation["total_credentials"],
            files_with_credentials=aggregation["files_with_credentials"]
        )

        return aggregation

    def convert_to_credential_models(
        self,
        scan_results: List[FileScanResult],
        task_id: str
    ) -> List[Credential]:
        """
        将扫描结果转换为凭证模型

        Args:
            scan_results: 扫描结果列表
            task_id: 任务 ID

        Returns:
            凭证模型列表
        """
        credentials: List[Credential] = []

        for result in scan_results:
            if not result.has_credentials:
                continue

            for cred_data in result.credentials:
                try:
                    # 映射凭证类型
                    cred_type_str = cred_data.get("cred_type", "UNKNOWN")
                    try:
                        cred_type = CredentialType[cred_type_str]
                    except KeyError:
                        cred_type = CredentialType.UNKNOWN

                    # 创建凭证模型
                    credential = Credential(
                        task_id=task_id,
                        cred_type=cred_type,
                        confidence=cred_data.get("confidence", 0.0),
                        file_path=cred_data.get("file_path", result.file_path),
                        line_number=cred_data.get("line_number"),
                        layer_id=cred_data.get("layer_id", result.layer_id),
                        context=cred_data.get("context", ""),
                        raw_value=cred_data.get("raw_value"),
                        validation_status=ValidationStatus.PENDING,
                        metadata=cred_data.get("metadata", {})
                    )

                    credentials.append(credential)

                except Exception as e:
                    logger.warning(
                        "凭证模型转换失败",
                        file_path=result.file_path,
                        error=str(e)
                    )

        logger.info(
            "凭证模型转换完成",
            input_count=sum(len(r.credentials) for r in scan_results),
            output_count=len(credentials)
        )

        return credentials

    def get_scan_stats(self) -> Dict[str, Any]:
        """获取扫描统计"""
        cached_results = list(self._scanned_files.values())

        return {
            "cached_files": len(cached_results),
            "files_with_credentials": sum(1 for r in cached_results if r.has_credentials),
            "total_credentials_found": sum(len(r.credentials) for r in cached_results)
        }

    def clear_cache(self):
        """清除缓存"""
        self._scanned_files.clear()
        logger.debug("清除扫描缓存")


# 全局内容扫描器实例（延迟加载）
_global_scanner: Optional[ContentScanner] = None


def get_content_scanner() -> ContentScanner:
    """
    获取全局内容扫描器实例（单例模式）

    Returns:
        内容扫描器实例
    """
    global _global_scanner
    if _global_scanner is None:
        _global_scanner = ContentScanner()
    return _global_scanner
