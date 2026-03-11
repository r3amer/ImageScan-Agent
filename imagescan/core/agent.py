"""
Agent 基类模块

用途：
1. 定义所有 Agent 的通用接口
2. 提供 Agent 生命周期管理
3. 实现事件订阅和发布
4. 管理Agent状态

参考：docs/APP_FLOW.md
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum

from .events import Event, EventType
from .event_bus import EventBus, get_event_bus
from ..utils.logger import get_logger

logger = get_logger(__name__)


class AgentState(str, Enum):
    """Agent 状态"""
    INITIALIZING = "initializing"  # 初始化中
    READY = "ready"                # 就绪
    RUNNING = "running"            # 运行中
    PAUSED = "paused"              # 暂停
    STOPPING = "stopping"          # 停止中
    STOPPED = "stopped"            # 已停止
    ERROR = "error"                # 错误状态


class Agent(ABC):
    """
    Agent 基类

    所有 Agent 的基础实现，提供：
    1. 生命周期管理
    2. 事件订阅/发布
    3. 状态管理
    4. 错误处理
    """

    def __init__(
        self,
        name: str,
        event_bus: Optional[EventBus] = None
    ):
        """
        初始化 Agent

        Args:
            name: Agent 名称
            event_bus: 事件总线（默认使用全局实例）
        """
        self.name = name
        self.event_bus = event_bus or get_event_bus()
        self.state = AgentState.INITIALIZING
        self._tasks: List[asyncio.Task] = []
        self._context: Dict[str, Any] = {}

        logger.info("Agent 初始化", name=name)

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self.state == AgentState.RUNNING

    @property
    def is_ready(self) -> bool:
        """是否就绪"""
        return self.state == AgentState.READY

    async def initialize(self):
        """
        初始化 Agent

        子类可以重写此方法以执行初始化逻辑
        """
        logger.info("Agent 开始初始化", name=self.name)

        # 订阅事件
        await self._subscribe_events()

        # 状态变更
        self.state = AgentState.READY

        # 发布就绪事件
        await self._publish_ready_event()

        logger.info("Agent 初始化完成", name=self.name)

    async def _subscribe_events(self):
        """
        订阅事件

        子类可以重写此方法以订阅特定事件
        """
        pass

    async def _publish_ready_event(self):
        """发布就绪事件"""
        from .events import Event

        event = Event(
            event_type=EventType.AGENT_READY,
            source=self.name,
            data={
                "agent_name": self.name,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        await self.event_bus.publish(event)

    @abstractmethod
    async def process(self, **kwargs) -> Any:
        """
        处理任务（抽象方法）

        子类必须实现此方法

        Args:
            **kwargs: 任务参数

        Returns:
            处理结果
        """
        pass

    async def start(self):
        """启动 Agent"""
        if self.state == AgentState.RUNNING:
            logger.warning("Agent 已在运行", name=self.name)
            return

        logger.info("Agent 启动", name=self.name)
        self.state = AgentState.RUNNING

    async def pause(self):
        """暂停 Agent"""
        if self.state != AgentState.RUNNING:
            logger.warning("Agent 未在运行", name=self.name)
            return

        logger.info("Agent 暂停", name=self.name)
        self.state = AgentState.PAUSED

    async def resume(self):
        """恢复 Agent"""
        if self.state != AgentState.PAUSED:
            logger.warning("Agent 未暂停", name=self.name)
            return

        logger.info("Agent 恢复", name=self.name)
        self.state = AgentState.RUNNING

    async def stop(self):
        """停止 Agent"""
        if self.state == AgentState.STOPPED:
            logger.warning("Agent 已停止", name=self.name)
            return

        logger.info("Agent 停止中", name=self.name)
        self.state = AgentState.STOPPING

        # 取消所有任务
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # 等待任务取消
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        # 取消事件订阅
        self.event_bus.unsubscribe_all(self.name)

        self.state = AgentState.STOPPED
        logger.info("Agent 已停止", name=self.name)

    async def publish_event(self, event: Event):
        """
        发布事件

        Args:
            event: 事件对象
        """
        await self.event_bus.publish(event)

    def set_context(self, key: str, value: Any):
        """
        设置上下文数据

        Args:
            key: 键
            value: 值
        """
        self._context[key] = value
        logger.debug("上下文设置", name=self.name, key=key)

    def get_context(self, key: str, default: Any = None) -> Any:
        """
        获取上下文数据

        Args:
            key: 键
            default: 默认值

        Returns:
            上下文值
        """
        return self._context.get(key, default)

    def clear_context(self):
        """清空上下文"""
        self._context.clear()
        logger.debug("上下文已清空", name=self.name)

    def create_task(self, coro):
        """
        创建异步任务

        Args:
            coro: 协程对象

        Returns:
            Task 对象
        """
        task = asyncio.create_task(coro)
        self._tasks.append(task)

        # 清理已完成的任务
        self._tasks = [t for t in self._tasks if not t.done()]

        return task

    async def handle_event(self, event: Event):
        """
        处理事件（默认实现）

        子类可以重写此方法

        Args:
            event: 事件对象
        """
        logger.debug(
            "收到事件",
            name=self.name,
            event_type=event.event_type,
            source=event.source
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} state={self.state.value}>"


class BaseAgent(Agent):
    """
    基础 Agent 实现

    提供事件处理的默认实现
    """

    def __init__(self, name: str, event_bus: Optional[EventBus] = None):
        super().__init__(name, event_bus)
        self._event_handlers: Dict[EventType, callable] = {}

    def register_handler(self, event_type: EventType, handler: callable):
        """
        注册事件处理器

        Args:
            event_type: 事件类型
            handler: 处理函数
        """
        self._event_handlers[event_type] = handler
        logger.debug(
            "注册事件处理器",
            name=self.name,
            event_type=event_type.value
        )

    async def _subscribe_events(self):
        """订阅所有注册的事件"""
        for event_type in self._event_handlers:
            self.event_bus.subscribe(
                event_type,
                self.name,
                self.handle_event
            )

    async def handle_event(self, event: Event):
        """
        处理事件

        Args:
            event: 事件对象
        """
        # 查找处理器
        handler = self._event_handlers.get(event.event_type)

        if handler:
            try:
                # 调用处理器
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(
                    "事件处理失败",
                    name=self.name,
                    event_type=event.event_type,
                    error=str(e)
                )
        else:
            # 调用父类默认处理
            await super().handle_event(event)
