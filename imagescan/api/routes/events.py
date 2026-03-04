"""
WebSocket 路由 - 实时事件推送

职责：
1. 建立 WebSocket 连接
2. 处理心跳机制
3. 推送扫描事件

参考：progress_frontend.txt 第一阶段
"""

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..websocket.manager import manager
from ...utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str
):
    """
    WebSocket 端点 - 实时事件推送

    前端连接示例：
    ```javascript
    const ws = new WebSocket('ws://localhost:8000/api/events/ws/session-123');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('收到事件:', data);
    };
    ```

    Args:
        websocket: WebSocket 连接
        session_id: 会话 ID（用于区分不同用户会话）
    """
    await manager.connect(websocket, session_id)
    logger.info("WebSocket 连接建立", session_id=session_id)

    try:
        # 发送欢迎消息
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "message": "WebSocket 连接成功"
        })

        # 持续接收消息
        while True:
            data = await websocket.receive_text()

            # 处理心跳
            if data == "ping":
                await websocket.send_text("pong")
                logger.debug("收到心跳", session_id=session_id)
            else:
                # 处理其他消息（目前暂不支持）
                logger.debug("收到客户端消息", message=data, session_id=session_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
        logger.info("WebSocket 连接断开", session_id=session_id)
    except Exception as e:
        logger.error("WebSocket 错误", error=str(e), session_id=session_id)
        manager.disconnect(websocket, session_id)
