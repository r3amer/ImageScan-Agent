"""
主控 Agent

职责：
1. 接收扫描任务
2. 制定扫描计划
3. 协调从 Agent 工作
4. 汇总扫描结果
5. 生成最终报告

参考：docs/APP_FLOW.md
"""

import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid

from ..core.agent import BaseAgent, AgentState
from ..core.events import (
    EventType,
    create_task_created,
    create_task_progress,
    create_error
)
from ..core.event_bus import get_event_bus
from ..utils.logger import get_logger
from ..utils.database import Database, get_database
from ..models.task import ScanTask, ScanStatus

logger = get_logger(__name__)


class MasterAgent(BaseAgent):
    """
    主控 Agent

    扫描任务的中央协调器，负责：
    1. 任务生命周期管理
    2. 协调 Executor、Validation、Knowledge、Reflection Agent
    3. 进度追踪和结果汇总
    """

    def __init__(
        self,
        event_bus=None,
        database: Optional[Database] = None
    ):
        super().__init__("MasterAgent", event_bus)

        self.database = database or get_database()

        # 当前任务
        self.current_task: Optional[ScanTask] = None

        # 从 Agent 引用（延迟初始化）
        self.executor_agent = None
        self.validation_agent = None
        self.knowledge_agent = None
        self.reflection_agent = None

        # 扫描统计
        self.scan_stats = {
            "total_layers": 0,
            "processed_layers": 0,
            "total_files": 0,
            "processed_files": 0,
            "credentials_found": 0,
            "credentials_confirmed": 0,
            "start_time": None,
            "end_time": None
        }

    def set_agents(
        self,
        executor_agent,
        validation_agent,
        knowledge_agent,
        reflection_agent
    ):
        """
        设置从 Agent 引用

        Args:
            executor_agent: 执行 Agent
            validation_agent: 验证 Agent
            knowledge_agent: 知识 Agent
            reflection_agent: 研判 Agent
        """
        self.executor_agent = executor_agent
        self.validation_agent = validation_agent
        self.knowledge_agent = knowledge_agent
        self.reflection_agent = reflection_agent

        logger.info("从 Agent 已设置", name=self.name)

    async def _subscribe_events(self):
        """订阅事件"""
        await super()._subscribe_events()

        # 订阅进度事件
        self.register_handler(EventType.TASK_PROGRESS, self._on_progress)
        self.register_handler(EventType.FILE_CREDENTIAL_FOUND, self._on_credential_found)
        self.register_handler(EventType.ERROR_OCCURRED, self._on_error)

    async def process(
        self,
        image_name: str,
        image_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理扫描任务

        Args:
            image_name: 镜像名称
            image_id: 镜像 ID
            **kwargs: 其他参数

        Returns:
            扫描结果
        """
        logger.info(
            "开始处理扫描任务",
            image_name=image_name,
            image_id=image_id
        )

        # 创建任务
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = ScanTask(
            task_id=task_id,
            image_name=image_name,
            image_id=image_id,
            status=ScanStatus.PENDING
        )

        self.current_task = task

        # 发布任务创建事件
        await self.publish_event(
            create_task_created(
                source=self.name,
                task_id=task_id,
                image_name=image_name,
                image_id=image_id
            )
        )

        # 保存到数据库
        await self.database.insert_task(task.model_dump())

        # 更新状态
        await self.database.update_task_status(
            task_id,
            ScanStatus.RUNNING,
            started_at=datetime.utcnow()
        )

        self.state = AgentState.RUNNING
        self.scan_stats["start_time"] = datetime.utcnow()

        try:
            # 1. 调用 Executor Agent 执行扫描
            logger.info("调用 Executor Agent", task_id=task_id)
            scan_result = await self.executor_agent.process(
                task_id=task_id,
                image_name=image_name,
                image_id=image_id
            )

            # 2. 调用 Reflection Agent 进行研判
            logger.info("调用 Reflection Agent", task_id=task_id)
            reflection_result = await self.reflection_agent.process(
                task_id=task_id,
                scan_result=scan_result
            )

            # 3. 更新任务完成状态
            await self.database.update_task_status(
                task_id,
                ScanStatus.COMPLETED,
                completed_at=datetime.utcnow(),
                credentials_found=reflection_result.get("total_credentials", 0)
            )

            # 4. 生成最终报告
            report = await self._generate_report(task_id, scan_result, reflection_result)

            self.scan_stats["end_time"] = datetime.utcnow()
            self.state = AgentState.READY

            logger.info(
                "扫描任务完成",
                task_id=task_id,
                credentials_found=reflection_result.get("total_credentials", 0)
            )

            return {
                "task_id": task_id,
                "status": "completed",
                "report": report
            }

        except Exception as e:
            logger.error(
                "扫描任务失败",
                task_id=task_id,
                error=str(e)
            )

            # 更新任务失败状态
            await self.database.update_task_status(
                task_id,
                ScanStatus.FAILED,
                completed_at=datetime.utcnow(),
                error_message=str(e)
            )

            # 发布错误事件
            await self.publish_event(
                create_error(
                    source=self.name,
                    error_message=str(e),
                    error_type=type(e).__name__,
                    task_id=task_id
                )
            )

            self.state = AgentState.ERROR
            raise

    async def _on_progress(self, event):
        """处理进度事件"""
        data = event.data

        # 更新统计
        self.scan_stats["processed_layers"] = data.get("current_layer", 0)
        self.scan_stats["total_layers"] = data.get("total_layers", 0)
        self.scan_stats["processed_files"] = data.get("current_file", 0)
        self.scan_stats["total_files"] = data.get("total_files", 0)
        self.scan_stats["credentials_found"] = data.get("credentials_found", 0)

        # 转发进度事件（让外部订阅者也能收到）
        await self.publish_event(event)

        logger.debug(
            "任务进度更新",
            task_id=data.get("task_id"),
            progress=f"{data.get('current_layer', 0)}/{data.get('total_layers', 0)} 层"
        )

    async def _on_credential_found(self, event):
        """处理凭证发现事件"""
        self.scan_stats["credentials_found"] += 1

        # 转发事件
        await self.publish_event(event)

        logger.info(
            "发现凭证",
            task_id=event.data.get("task_id"),
            cred_type=event.data.get("cred_type"),
            confidence=event.data.get("confidence")
        )

    async def _on_error(self, event):
        """处理错误事件"""
        logger.error(
            "扫描错误",
            task_id=event.data.get("task_id"),
            error=event.data.get("error_message")
        )

        # 转发错误事件
        await self.publish_event(event)

    async def _generate_report(
        self,
        task_id: str,
        scan_result: Dict[str, Any],
        reflection_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成最终报告

        Args:
            task_id: 任务 ID
            scan_result: 扫描结果
            reflection_result: 研判结果

        Returns:
            报告数据
        """
        from ..core.llm_client import get_llm_client

        llm_client = get_llm_client()

        # 准备元数据
        scan_metadata = {
            "task_id": task_id,
            "image_name": self.current_task.image_name,
            "image_id": self.current_task.image_id,
            "scan_duration_seconds": (
                self.scan_stats["end_time"] - self.scan_stats["start_time"]
            ).total_seconds() if self.scan_stats["end_time"] else 0,
            "total_size_bytes": scan_result.get("total_size", 0),
            "layers_scanned": self.scan_stats["processed_layers"],
            "files_scanned": self.scan_stats["processed_files"],
            "credentials_found": self.scan_stats["credentials_found"]
        }

        # 获取凭证列表
        credentials = await self.database.get_credentials_by_task(task_id)

        # 调用 LLM 生成报告摘要
        try:
            summary = await llm_client.generate_scan_report(
                scan_metadata=scan_metadata,
                credentials=[cred.model_dump() for cred in credentials]
            )
        except Exception as e:
            logger.warning("LLM 报告生成失败", error=str(e))
            summary = {
                "summary": "扫描完成",
                "risk_level": "UNKNOWN",
                "key_findings": [],
                "recommendations": []
            }

        # 组装完整报告
        report = {
            "metadata": scan_metadata,
            "statistics": reflection_result.get("statistics", {}),
            "summary": summary,
            "credentials": [
                {
                    "cred_type": cred["cred_type"],
                    "confidence": cred["confidence"],
                    "file_path": cred["file_path"],
                    "layer_id": cred["layer_id"],
                    "validation_status": cred["validation_status"]
                }
                for cred in credentials
            ],
            "scan_details": scan_result,
            "generated_at": datetime.utcnow().isoformat()
        }

        return report

    def get_scan_progress(self) -> Dict[str, Any]:
        """获取当前扫描进度"""
        return {
            "task_id": self.current_task.task_id if self.current_task else None,
            "status": self.state.value,
            "stats": self.scan_stats.copy()
        }
