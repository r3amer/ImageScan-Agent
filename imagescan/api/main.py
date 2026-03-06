"""
FastAPI 后端服务 - 主应用入口

职责：
1. 初始化 FastAPI 应用
2. 注册路由
3. 集成 EventBus 到 WebSocket
4. 提供健康检查

参考：progress_frontend.txt 第一阶段
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
from .routes import chat, scan, events
from .websocket.manager import manager
from ..core.event_bus import get_event_bus
from ..utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    启动时：
    - 订阅 EventBus
    - 初始化组件

    关闭时：
    - 清理资源
    """
    # 启动
    logger.info("FastAPI 应用启动中...")

    # 获取事件总线
    event_bus = get_event_bus()

    # 订阅所有事件，转发给 WebSocket 客户端
    event_bus.subscribe_all("api_websocket", _forward_to_websockets)
    logger.info("已订阅 EventBus，事件将转发到 WebSocket")

    yield

    # 关闭
    logger.info("FastAPI 应用关闭中...")
    # TODO: 清理资源


# 创建 FastAPI 应用
app = FastAPI(
    title="ImageScan API",
    description="Docker 镜像敏感凭证扫描 API",
    version="0.1.0",
    lifespan=lifespan
)


async def _forward_to_websockets(event):
    """
    将 EventBus 事件转发给所有 WebSocket 客户端

    Args:
        event: EventBus 事件对象
    """
    from datetime import timezone

    # 转发事件到 WebSocket 客户端
    message = {
        "type": str(event.event_type),  # EventType is a str Enum, already a string value
        "source": event.source,
        "data": event.data,
        "timestamp": event.timestamp.astimezone(timezone.utc).isoformat()
    }

    # 添加日志来诊断事件转发
    logger.debug(
        "转发事件到 WebSocket",
        event_type=str(event.event_type),
        source=event.source,
        connections=manager.get_connection_count()
    )

    await manager.broadcast(message)


# 注册路由
app.include_router(
    chat.router,
    prefix="/api/chat",
    tags=["chat"]
)

app.include_router(
    scan.router,
    prefix="/api/scan",
    tags=["scan"]
)

app.include_router(
    events.router,
    prefix="/api/events",
    tags=["events"]
)


# 根路径
@app.get("/")
async def root():
    """根路径 - API 信息"""
    return {
        "name": "ImageScan API",
        "version": "0.1.0",
        "status": "running",
        "websocket_connections": manager.get_connection_count(),
        "endpoints": {
            "chat": "/api/chat/message",
            "scan": "/api/scan/{task_id}",
            "websocket": "/api/events/ws/{session_id}",
            "docs": "/docs"
        }
    }


# 健康检查
@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "websocket_connections": manager.get_connection_count()
    }
