"""
事件总线模块

用途：
1. 实现 Agent 之间的事件发布/订阅机制
2. 异步事件分发
3. 事件历史记录
4. 事件过滤和路由

参考：docs/APP_FLOW.md
"""

import asyncio
from typing import Dict, List, Callable, Optional, Set
from collections import defaultdict, deque
from datetime import datetime

from .events import Event, EventType
from ..utils.logger import get_logger

logger = get_logger(__name__)


# 事件处理器类型
EventHandler = Callable[[Event], None]


class EventBus:
    """
    事件总线

    职责：
    1. 管理事件订阅
    2. 分发事件到订阅者
    3. 记录事件历史
    4. 支持事件过滤
    """

    def __init__(self, history_size: int = 1000):
        """
        初始化事件总线

        Args:
            history_size: 事件历史记录最大数量
        """
        # 事件订阅: {event_type: {agent_name: handler}}
        self._subscriptions: Dict[EventType, Dict[str, EventHandler]] = defaultdict(dict)

        # 全局订阅器（接收所有事件）
        self._global_subscribers: Dict[str, EventHandler] = {}

        # 事件历史（用于调试和追踪）
        self._history: deque = deque(maxlen=history_size)

        # 统计信息
        self._stats = {
            "events_published": 0,
            "events_delivered": 0,
            "events_failed": 0
        }

        logger.info("事件总线初始化", history_size=history_size)

    def subscribe(
        self,
        event_type: EventType,
        agent_name: str,
        handler: EventHandler
    ):
        """
        订阅事件

        Args:
            event_type: 事件类型
            agent_name: 订阅者（Agent 名称）
            handler: 事件处理函数
        """
        self._subscriptions[event_type][agent_name] = handler
        logger.debug(
            "订阅事件",
            agent=agent_name,
            event_type=event_type.value if hasattr(event_type, 'value') else event_type
        )

    def subscribe_all(
        self,
        agent_name: str,
        handler: EventHandler
    ):
        """
        订阅所有事件（全局订阅）

        Args:
            agent_name: 订阅者（Agent 名称）
            handler: 事件处理函数
        """
        self._global_subscribers[agent_name] = handler
        logger.debug("订阅所有事件", agent=agent_name)

    def unsubscribe(
        self,
        event_type: EventType,
        agent_name: str
    ):
        """
        取消订阅

        Args:
            event_type: 事件类型
            agent_name: 订阅者（Agent 名称）
        """
        if agent_name in self._subscriptions[event_type]:
            del self._subscriptions[event_type][agent_name]
            logger.debug(
                "取消订阅",
                agent=agent_name,
                event_type=event_type.value if hasattr(event_type, 'value') else event_type
            )

    def unsubscribe_all(self, agent_name: str):
        """
        取消所有订阅

        Args:
            agent_name: 订阅者（Agent 名称）
        """
        # 从特定事件订阅中移除
        for event_type in self._subscriptions:
            if agent_name in self._subscriptions[event_type]:
                del self._subscriptions[event_type][agent_name]

        # 从全局订阅中移除
        if agent_name in self._global_subscribers:
            del self._global_subscribers[agent_name]

        logger.debug("取消所有订阅", agent=agent_name)

    async def publish(self, event: Event):
        """
        发布事件（异步）

        Args:
            event: 事件对象
        """
        self._stats["events_published"] += 1

        # 记录到历史
        self._history.append(event)

        logger.debug(
            "发布事件",
            event_type=event.event_type,
            source=event.source,
            data_keys=list(event.data.keys())
        )

        # 获取所有订阅者
        subscribers = {}

        # 添加特定事件订阅者
        if event.event_type in self._subscriptions:
            subscribers.update(self._subscriptions[event.event_type])

        # 添加全局订阅者
        subscribers.update(self._global_subscribers)

        # 异步分发事件
        if subscribers:
            await self._deliver_event(event, subscribers)
        else:
            logger.debug("无订阅者", event_type=event.event_type)

    async def _deliver_event(
        self,
        event: Event,
        subscribers: Dict[str, EventHandler]
    ):
        """
        分发事件到订阅者

        Args:
            event: 事件对象
            subscribers: 订阅者字典 {agent_name: handler}
        """
        # 并发调用所有订阅者
        tasks = []
        for agent_name, handler in subscribers.items():
            # 跳过事件发布者（避免自己收到自己的事件）
            if agent_name == event.source:
                continue

            task = self._safe_call_handler(agent_name, handler, event)
            tasks.append(task)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 统计成功/失败
            for result in results:
                if isinstance(result, Exception):
                    self._stats["events_failed"] += 1
                    logger.warning(
                        "事件处理失败",
                        error=str(result),
                        event_type=event.event_type
                    )
                else:
                    self._stats["events_delivered"] += 1

    async def _safe_call_handler(
        self,
        agent_name: str,
        handler: EventHandler,
        event: Event
    ):
        """
        安全调用事件处理器

        Args:
            agent_name: Agent 名称
            handler: 处理器函数
            event: 事件对象

        Returns:
            处理结果
        """
        try:
            # 如果处理器是协程函数，await 它
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)
        except Exception as e:
            logger.error(
                "事件处理器异常",
                agent=agent_name,
                event_type=event.event_type,
                error=str(e)
            )
            raise

    async def publish_and_wait(
        self,
        event: Event,
        timeout: float = 5.0
    ) -> Dict[str, bool]:
        """
        发布事件并等待所有订阅者处理完成

        Args:
            event: 事件对象
            timeout: 超时时间（秒）

        Returns:
            {agent_name: success} 订阅者处理结果
        """
        # 记录到历史
        self._history.append(event)
        self._stats["events_published"] += 1

        # 获取所有订阅者
        subscribers = {}

        if event.event_type in self._subscriptions:
            subscribers.update(self._subscriptions[event.event_type])

        subscribers.update(self._global_subscribers)

        # 过滤掉发布者
        subscribers = {
            name: handler
            for name, handler in subscribers.items()
            if name != event.source
        }

        if not subscribers:
            return {}

        # 并发调用并等待
        results = {}
        tasks = []

        for agent_name, handler in subscribers.items():
            task = self._safe_call_handler(agent_name, handler, event)
            tasks.append((agent_name, task))

        # 等待所有任务完成（带超时）
        for agent_name, task in tasks:
            try:
                await asyncio.wait_for(task, timeout=timeout)
                results[agent_name] = True
            except asyncio.TimeoutError:
                logger.warning(
                    "事件处理超时",
                    agent=agent_name,
                    timeout=timeout
                )
                results[agent_name] = False
            except Exception as e:
                logger.error(
                    "事件处理失败",
                    agent=agent_name,
                    error=str(e)
                )
                results[agent_name] = False

        return results

    def get_history(
        self,
        event_type: Optional[EventType] = None,
        source: Optional[str] = None,
        limit: int = 100
    ) -> List[Event]:
        """
        获取事件历史

        Args:
            event_type: 事件类型过滤（None 表示所有类型）
            source: 事件源过滤（None 表示所有源）
            limit: 返回数量限制

        Returns:
            事件列表
        """
        events = list(self._history)

        # 过滤
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        if source:
            events = [e for e in events if e.source == source]

        # 限制数量并反转（最新的在前）
        events = events[-limit:][::-1]

        return events

    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return {
            **self._stats,
            "history_size": len(self._history),
            "active_subscriptions": sum(
                len(subs) for subs in self._subscriptions.values()
            ),
            "global_subscribers": len(self._global_subscribers)
        }

    def clear_history(self):
        """清空事件历史"""
        self._history.clear()
        logger.debug("事件历史已清空")

    def get_subscription_count(self, event_type: Optional[EventType] = None) -> int:
        """
        获取订阅数量

        Args:
            event_type: 事件类型（None 表示所有类型）

        Returns:
            订阅数量
        """
        if event_type:
            return len(self._subscriptions.get(event_type, {}))
        else:
            return sum(len(subs) for subs in self._subscriptions.values())


# 全局事件总线实例（延迟加载）
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """
    获取全局事件总线实例（单例模式）

    Returns:
        事件总线实例
    """
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus
