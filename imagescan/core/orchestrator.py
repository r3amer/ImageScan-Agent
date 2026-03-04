"""
扫描编排器 - 协调扫描流程

职责：
1. 初始化所有依赖（LLMClient、ToolRegistry、RuleEngine 等）
2. 创建 ScanAgent
3. 运行 ScanAgent（所有步骤由 LLM 规划，包括准备阶段）
4. 收集并返回结果

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from .event_bus import get_event_bus, EventBus
from .llm_client import get_llm_client, LLMClient
from .events import Event, create_task_created
from ..tools.registry import registry
from ..utils.rules import RuleEngine, register_rule_engine_tools, set_rule_engine_instance
from ..utils.summary import SummaryManager
from ..utils.config import Config
from ..storage.simple_storage import SimpleStorageManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ScanOrchestrator:
    """
    扫描编排器

    简化设计 - 让 LLM 完全自主规划所有步骤：
    1. 初始化依赖
    2. 创建 ScanAgent
    3. ScanAgent 自主决定所有操作（包括 docker.save、tar.unpack 等）
    4. 收集结果
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        config: Optional[Config] = None
    ):
        """
        初始化编排器

        Args:
            event_bus: 事件总线（默认使用全局实例）
            config: 配置对象（默认自动加载）
        """
        self.event_bus = event_bus or get_event_bus()
        self.config = config or Config()

        # 存储管理器
        self.storage = SimpleStorageManager()

        # 依赖（在 scan_image 中初始化）
        self.llm_client: Optional[LLMClient] = None
        self.rule_engine: Optional[RuleEngine] = None
        self.summary_manager: Optional[SummaryManager] = None

    async def scan_image(
        self,
        image_name: str,
        output_file: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        扫描镜像主流程

        Args:
            image_name: Docker 镜像名称
            output_file: 输出 JSON 文件路径（可选）

        Returns:
            扫描结果字典
        """
        # 生成任务 ID
        task_id = str(uuid.uuid4())

        logger.info("开始扫描", task_id=task_id, image=image_name)

        # 设置元数据
        self.storage.set_metadata("task_id", task_id)
        self.storage.set_metadata("image_name", image_name)
        self.storage.set_metadata("started_at", datetime.utcnow().isoformat())

        try:
            # 1. 初始化依赖
            await self._initialize()

            # 发布任务创建事件
            await self._publish_event(create_task_created(
                source="scan_orchestrator",
                task_id=task_id,
                image_name=image_name,
                image_id=image_name  # 使用 image_name 作为 image_id
            ))

            # 2. 创建 ScanAgent
            scan_agent = self._create_scan_agent(image_name, task_id)

            # 3. 运行 ScanAgent（所有步骤由 LLM 自主规划）
            logger.info("Agent 开始自主扫描", task_id=task_id)
            agent_result = await scan_agent.process()

            # 4. 构建结果
            result = await self._build_result(agent_result)

            # 5. 保存到文件（如果指定）
            if output_file:
                self.storage.save_to_json(output_file)
                logger.info("结果已保存", path=output_file)

            # 更新完成时间
            self.storage.set_metadata("completed_at", datetime.utcnow().isoformat())

            logger.info("扫描完成", task_id=task_id, credentials=result["credential_count"])
            return result

        except Exception as e:
            logger.error("扫描失败", task_id=task_id, error=str(e))
            await self._publish_error(task_id, str(e))
            raise

    async def _initialize(self):
        """初始化所有依赖"""
        logger.debug("初始化依赖")

        # LLM 客户端（使用全局单例，不接受参数）
        self.llm_client = get_llm_client()

        # # 规则引擎
        # self.rule_engine = RuleEngine(self.config)

        # # 设置全局 RuleEngine 实例并注册工具
        # set_rule_engine_instance(self.rule_engine)
        # register_rule_engine_tools()

        # 摘要管理器
        self.summary_manager = SummaryManager(
            token_threshold=self.config.api.summary_token_threshold,
            keep_recent=5
        )

    def _create_scan_agent(self, image_name: str, task_id: str):
        """
        创建 ScanAgent

        Args:
            image_name: 镜像名称
            task_id: 任务 ID

        Returns:
            ScanAgent 实例
        """
        from ..agents.scan_agent import ScanAgent

        return ScanAgent(
            event_bus=self.event_bus,
            llm_client=self.llm_client,
            tool_registry=registry,
            rule_engine=self.rule_engine,
            summary_manager=self.summary_manager,
            task_id=task_id,
            image_name=image_name,
            config=self.config,
            storage=self.storage
        )

    async def _build_result(self, agent_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建最终结果

        Args:
            agent_result: Agent 返回结果

        Returns:
            最终结果字典
        """
        # 获取摘要
        summary = self.storage.get_summary()

        # 构建结果
        result = {
            "task_id": self.storage.get_metadata("task_id"),
            "image_name": self.storage.get_metadata("image_name"),
            "status": "completed",
            "credentials": [
                {
                    "type": cred.cred_type,
                    "confidence": cred.confidence,
                    "file_path": cred.file_path,
                    "layer_id": cred.layer_id,
                    "line_number": cred.line_number,
                    "validation_status": cred.validation_status
                }
                for cred in self.storage.get_credentials()
            ],
            "credential_count": summary["total_credentials"],
            "risk_level": summary["risk_level"],
            "statistics": summary["statistics"],
            "token_usage": summary["token_usage"],
            "duration": agent_result.get("duration", 0),
            "steps_taken": agent_result.get("steps_taken", 0),
            "started_at": self.storage.get_metadata("started_at"),
            "completed_at": self.storage.get_metadata("completed_at")
        }

        return result

    async def _publish_event(self, event: Event):
        """发布事件"""
        await self.event_bus.publish(event)

    async def _publish_error(self, task_id: str, error_message: str):
        """发布错误事件"""
        from .events import create_error
        await self._publish_event(create_error(
            source="scan_orchestrator",
            error_message=error_message,
            error_type="ScanError",
            task_id=task_id
        ))

    def get_storage(self) -> SimpleStorageManager:
        """获取存储管理器"""
        return self.storage
