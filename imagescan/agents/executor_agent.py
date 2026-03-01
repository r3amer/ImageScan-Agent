"""
执行 Agent

职责：
1. 执行镜像解压和层提取
2. 调用文件名分析器
3. 调用内容扫描器
4. 协调扫描流程

参考：docs/APP_FLOW.md
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

from ..core.agent import BaseAgent
from ..core.events import (
    EventType,
    create_task_progress,
    create_credential_found,
    create_error
)
from ..core.event_bus import get_event_bus
from ..tools.docker_tools import (
    docker_save,
    docker_exists,
    docker_pull,
    docker_inspect
)
from ..tools.tar_tools import (
    tar_unpack,
    tar_list_layers,
    tar_extract_file
)
from ..core.filename_analyzer import get_filename_analyzer, FilenameAnalysisResult
from ..core.content_scanner import get_content_scanner, FileScanResult
from ..utils.logger import get_logger
from ..utils.database import Database, get_database
from ..models.credential import Credential, CredentialType, ValidationStatus
from ..models.layer import ScanLayer
from ..utils.config import get_config

logger = get_logger(__name__)


class ExecutorAgent(BaseAgent):
    """
    执行 Agent

    负责实际的扫描工作：
    1. 保存 Docker 镜像为 tar 文件
    2. 解压 tar 并获取层信息
    3. 分析文件名
    4. 扫描文件内容
    5. 保存结果到数据库
    """

    def __init__(self, event_bus=None, database: Optional[Database] = None):
        super().__init__("ExecutorAgent", event_bus)

        self.database = database or get_database()
        self.config = get_config()

        # 分析器和扫描器
        self.filename_analyzer = get_filename_analyzer()
        self.content_scanner = get_content_scanner()

        # 工作目录
        self.work_dir = Path(self.config.storage.output_path)
        self.tar_dir = self.work_dir / "image_tar"
        self.extract_dir = self.work_dir / "extracted"

    async def process(
        self,
        task_id: str,
        image_name: str,
        image_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行扫描任务

        Args:
            task_id: 任务 ID
            image_name: 镜像名称
            image_id: 镜像 ID
            **kwargs: 其他参数

        Returns:
            扫描结果
        """
        logger.info(
            "开始执行扫描",
            task_id=task_id,
            image_name=image_name
        )

        try:
            # 1. 检查镜像是否存在
            if not await docker_exists(image_name):
                logger.info("镜像不存在，尝试拉取", image=image_name)
                await docker_pull(image_name)

            # 2. 获取镜像信息
            inspect_info = await docker_inspect(image_name)
            logger.debug("镜像信息", size=inspect_info.get("Size"))

            # 3. 保存镜像为 tar 文件（docker_save 返回实际的 tar 文件路径）
            tar_dir = self.tar_dir / task_id
            tar_path = await docker_save(image_name, str(tar_dir))
            logger.info("镜像已保存", path=str(tar_path))

            # 4. 解压 tar 文件
            extract_path = self.extract_dir / task_id
            await tar_unpack(str(tar_path), str(extract_path))
            logger.info("Tar 文件已解压", path=str(extract_path))

            # 5. 读取 manifest.json 获取层信息（tar_list_layers 不是 async）
            layers_info = tar_list_layers(str(tar_path))
            total_layers = len(layers_info)
            logger.info("发现镜像层", count=total_layers)

            # 6. 保存层信息到数据库
            for idx, layer_info in enumerate(layers_info):
                layer = ScanLayer(
                    layer_id=layer_info["layer_id"],
                    task_id=task_id,
                    layer_index=idx,
                    size_bytes=layer_info.get("size", 0),
                    file_count=0,
                    processed=False
                )
                await self.database.insert_layer(layer.model_dump())

            # 7. 扫描每一层
            total_credentials = 0
            total_size = sum(l.get("size", 0) for l in layers_info)

            for idx, layer_info in enumerate(layers_info):
                layer_id = layer_info["layer_id"]

                # 发布进度
                await self.publish_event(
                    create_task_progress(
                        source=self.name,
                        task_id=task_id,
                        current_layer=idx + 1,
                        total_layers=total_layers,
                        credentials_found=total_credentials
                    )
                )

                # 扫描层
                credentials = await self._scan_layer(
                    task_id=task_id,
                    layer_id=layer_id,
                    layer_index=idx,
                    extract_path=extract_path
                )

                total_credentials += len(credentials)

                # 更新层状态
                await self.database.update_layer_processed(
                    layer_id,
                    processed=True,
                    credentials_found=len(credentials)
                )

            # 8. 更新任务统计信息到数据库
            # 获取实际扫描的文件数（从层信息中统计）
            layers = await self.database.get_layers_by_task(task_id)
            total_files_scanned = sum(layer.get("file_count", 0) for layer in layers)

            await self.database.update_task_status(
                task_id,
                status="completed",
                total_layers=total_layers,
                processed_layers=total_layers,
                total_files=total_files_scanned,
                processed_files=total_files_scanned,
                credentials_found=total_credentials,
                completed_at=datetime.utcnow().isoformat()
            )

            # 9. 清理临时文件以节省磁盘空间
            await self._cleanup_temp_files(tar_path, extract_path, task_id)

            logger.info(
                "扫描执行完成",
                task_id=task_id,
                layers_processed=total_layers,
                credentials_found=total_credentials
            )

            return {
                "task_id": task_id,
                "status": "success",
                "total_layers": total_layers,
                "total_size": total_size,
                "credentials_found": total_credentials
            }

        except Exception as e:
            logger.error(
                "扫描执行失败",
                task_id=task_id,
                error=str(e)
            )

            await self.publish_event(
                create_error(
                    source=self.name,
                    error_message=str(e),
                    error_type=type(e).__name__,
                    task_id=task_id
                )
            )

            raise

    async def _scan_layer(
        self,
        task_id: str,
        layer_id: str,
        layer_index: int,
        extract_path: Path
    ) -> List[Dict[str, Any]]:
        """
        扫描单个镜像层

        Args:
            task_id: 任务 ID
            layer_id: 层 ID
            layer_index: 层索引
            extract_path: 提取目录

        Returns:
            发现的凭证列表
        """
        logger.debug(
            "开始扫描层",
            task_id=task_id,
            layer_id=layer_id[:12]
        )

        # 1. 列出层文件
        # OCI 格式：layer_id 是完整路径如 "blobs/sha256/<digest>"，该文件本身是 tar.gz
        # Docker v2.2 格式：layer_id 是目录，包含 layer.tar
        layer_tar = extract_path / layer_id

        # 如果是目录，尝试查找 layer.tar（Docker v2.2 格式）
        if layer_tar.is_dir():
            layer_tar = layer_tar / "layer.tar"

        if not layer_tar.exists():
            logger.warning("层文件不存在", layer_id=layer_id[:12])
            return []

        # 读取层文件列表
        from ..tools.tar_tools import tar_list_layer_files

        filenames = tar_list_layer_files(str(layer_tar))

        logger.debug(
            "层文件列表获取完成",
            layer_id=layer_id[:12],
            file_count=len(filenames)
        )

        if not filenames:
            logger.debug("层为空或无文件", layer_id=layer_id[:12])
            return []

        # 2. 分析文件名
        analysis_result = await self.filename_analyzer.analyze_layer(
            filenames=filenames,
            layer_id=layer_id
        )

        logger.debug(
            "文件名分析完成",
            layer_id=layer_id[:12],
            candidates=analysis_result.total_candidates
        )

        # 3. 获取高优先级文件
        high_priority_files = analysis_result.high_priority_files
        if not high_priority_files:
            logger.debug("无高优先级文件", layer_id=layer_id[:12])
            return []

        # 4. 提取并扫描文件内容
        credentials = []

        # 定义进度回调
        async def progress_callback(completed, total, result):
            await self.publish_event(
                create_task_progress(
                    source=self.name,
                    task_id=task_id,
                    current_layer=layer_index + 1,
                    total_layers=0,  # TODO: 从实际层数获取
                    current_file=completed,
                    total_files=total
                )
            )

        # 提取文件到临时位置
        # 创建该层的专用提取目录
        layer_extract_dir = extract_path / f"{layer_id.replace('/', '_')}_extracted"
        layer_extract_dir.mkdir(parents=True, exist_ok=True)

        extracted_files = []
        for filename in high_priority_files:
            try:
                # 从 layer.tar 中提取文件
                from ..tools.tar_tools import tar_extract_file

                extracted_path = await tar_extract_file(
                    tar_path=str(layer_tar),
                    member_path=filename,
                    output_path=str(layer_extract_dir)
                )

                extracted_files.append({
                    "file_path": extracted_path,
                    "layer_id": layer_id
                })
            except Exception as e:
                logger.warning("文件提取失败", file=filename, error=str(e))

        # 构建文件信息列表用于扫描
        files_to_scan = [
            {"file_path": ef["file_path"], "layer_id": layer_id}
            for ef in extracted_files
        ]

        # 批量扫描
        if files_to_scan:
            scan_results = await self.content_scanner.scan_multiple_files(
                files=files_to_scan,
                max_concurrent=5,
                progress_callback=progress_callback
            )

            # 5. 保存凭证到数据库
            for scan_result in scan_results:
                if scan_result.has_credentials:
                    for cred_data in scan_result.credentials:
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
                            file_path=cred_data.get("file_path", scan_result.file_path),
                            line_number=cred_data.get("line_number"),
                            layer_id=layer_id,
                            context=cred_data.get("context", ""),
                            raw_value=cred_data.get("raw_value"),
                            validation_status=ValidationStatus.PENDING,
                            metadata={}
                        )

                        # 保存到数据库
                        cred_id = await self.database.insert_credential(credential.model_dump())

                        # 发布凭证发现事件
                        await self.publish_event(
                            create_credential_found(
                                source=self.name,
                                task_id=task_id,
                                credential_id=cred_id,
                                cred_type=cred_type.value,
                                confidence=credential.confidence,
                                file_path=credential.file_path
                            )
                        )

                        credentials.append(cred_data)

        logger.info(
            "层扫描完成",
            layer_id=layer_id[:12],
            credentials_found=len(credentials)
        )

        return credentials

    async def _cleanup_temp_files(
        self,
        tar_path: str,
        extract_path: Path,
        task_id: str
    ):
        """
        清理临时文件以节省磁盘空间

        策略：
        - 删除tar文件（节省约194MB）
        - 保留extracted目录（便于用户查看凭证位置）

        Args:
            tar_path: tar文件路径（可能是字符串）
            extract_path: 解压目录路径
            task_id: 任务ID
        """
        import shutil

        try:
            # 确保tar_path是Path对象
            tar_path = Path(tar_path) if isinstance(tar_path, str) else tar_path

            # 1. 删除tar文件目录（节省空间）
            tar_dir = tar_path.parent
            if tar_dir.exists():
                dir_size = sum(f.stat().st_size for f in tar_dir.rglob('*') if f.is_file())
                shutil.rmtree(tar_dir)
                logger.info("已清理tar文件目录", path=str(tar_dir), size_mb=f"{dir_size / 1024 / 1024:.2f}")

            # 2. 清理layer提取的临时文件（如果有）
            # 这些是扫描过程中临时提取的文件，已经扫描完成可以删除
            layer_extract_base = extract_path.parent
            for extracted_dir in layer_extract_base.glob(f"{task_id.replace(':', '_').replace('/', '_')}*_extracted"):
                if extracted_dir.is_dir():
                    shutil.rmtree(extracted_dir)
                    logger.info("已清理layer临时提取目录", path=str(extracted_dir))

            # 3. 保留extracted目录（便于用户查看凭证位置）
            logger.info(
                "已保留解压目录供用户查看",
                path=str(extract_path.relative_to(Path.cwd()) if extract_path.is_absolute() else extract_path)
            )

            logger.info("临时文件清理完成", task_id=task_id, kept="extracted_directory")

        except Exception as e:
            logger.warning(
                "清理临时文件失败",
                task_id=task_id,
                error=str(e)
            )
            # 不抛出异常，清理失败不影响扫描结果

