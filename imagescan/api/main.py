"""
FastAPI 后端服务 - 主应用入口

职责：
1. 初始化 FastAPI 应用
2. 配置 CORS
3. 注册路由
4. 集成 EventBus 到 WebSocket
5. 提供健康检查

参考：progress_frontend.txt 第一阶段
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    event_bus.subscribe("*", _forward_to_websockets)
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


def _forward_to_websockets(event):
    """
    将 EventBus 事件转发给所有 WebSocket 客户端

    Args:
        event: EventBus 事件对象
    """
    import asyncio
    from datetime import timezone

    # 异步转发（避免阻塞 EventBus）
    async def _forward():
        await manager.broadcast({
            "type": event.event_type,
            "source": event.source,
            "data": event.data,
            "timestamp": event.timestamp.astimezone(timezone.utc).isoformat()
        })

    # 在新的事件循环中运行（或使用现有的事件循环）
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_forward())
    except RuntimeError:
        # 没有运行中的事件循环，创建一个新的
        asyncio.run(_forward())


# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js 开发服务器
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
