"""
WebSocket 连接管理器

职责：
1. 管理 WebSocket 连接（加入/离开）
2. 广播消息给所有客户端
3. 发送个人消息
4. 维护会话状态

参考：progress_frontend.txt 第一阶段
"""

from fastapi import WebSocket
from typing import Dict, List
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    WebSocket 连接管理器

    功能：
    - 管理多个会话的连接
    - 支持广播和单播
    - 自动清理断开的连接
    """

    def __init__(self):
        # {session_id: [WebSocket, ...]}
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """
        接受新的 WebSocket 连接

        Args:
            websocket: WebSocket 连接对象
            session_id: 会话 ID
        """
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        logger.info(
            "WebSocket 连接已建立",
            session_id=session_id,
            total_connections=len(self.active_connections)
        )

    def disconnect(self, websocket: WebSocket, session_id: str):
        """
        断开 WebSocket 连接

        Args:
            websocket: WebSocket 连接对象
            session_id: 会话 ID
        """
        if session_id in self.active_connections:
            try:
                self.active_connections[session_id].remove(websocket)
            except ValueError:
                pass  # 连接可能已被移除

            # 如果该会话没有连接了，删除会话
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

        logger.info(
            "WebSocket 连接已断开",
            session_id=session_id,
            remaining_connections=len(self.active_connections)
        )

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """
        发送消息给特定连接

        Args:
            message: 消息内容（字典）
            websocket: WebSocket 连接对象
        """
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error("发送个人消息失败", error=str(e))

    async def broadcast(self, message: dict, session_id: str = None):
        """
        广播消息

        Args:
            message: 消息内容（字典）
            session_id: 会话 ID（如果指定，只广播给该会话的所有连接）
        """
        if session_id:
            # 只广播给特定会话
            connections = self.active_connections.get(session_id, [])
        else:
            # 广播给所有连接
            connections = []
            for conns in self.active_connections.values():
                connections.extend(conns)

        # 发送消息
        disconnected = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning("发送广播消息失败，标记连接为断开", error=str(e))
                disconnected.append(connection)

        # 清理断开的连接
        for conn in disconnected:
            # 找到并移除断开的连接
            for sid, conns in list(self.active_connections.items()):
                if conn in conns:
                    conns.remove(conn)
                    if not conns:
                        del self.active_connections[sid]
                    break

        logger.debug(
            "广播消息完成",
            recipients=len(connections),
            failed=len(disconnected)
        )

    def get_connection_count(self) -> int:
        """获取当前连接总数"""
        return sum(len(conns) for conns in self.active_connections.values())

    def get_session_count(self) -> int:
        """获取当前会话总数"""
        return len(self.active_connections)


# 全局单例
manager = ConnectionManager()
