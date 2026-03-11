"""
对话路由 - 处理用户对话和命令解析

职责：
1. 接收用户消息
2. 使用 LLM 解析用户意图
3. 如果是扫描命令，启动扫描任务
4. 返回 AI 回复

参考：progress_frontend.txt 第一阶段
"""

import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks
from ..models.chat import ChatMessage, ChatResponse, Intent
from ...core.llm_client import get_llm_client
from ...core.orchestrator import ScanOrchestrator
from ...utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()
llm_client = get_llm_client()


@router.post("/message", response_model=ChatResponse)
async def handle_message(
    message: ChatMessage,
    background_tasks: BackgroundTasks
):
    """
    处理用户消息

    流程：
    1. LLM 解析用户意图
    2. 如果是扫描命令，启动后台扫描任务
    3. 返回 AI 回复

    Args:
        message: 用户消息
        background_tasks: FastAPI 后台任务

    Returns:
        ChatResponse: AI 响应
    """
    try:
        # 解析用户意图
        logger.info("收到用户消息", message=message.message, session_id=message.session_id)
        intent = await _parse_intent(message.message)

        if intent.action == "scan" and intent.image_name:
            # 启动扫描任务
            task_id = str(uuid.uuid4())
            logger.info(
                "识别到扫描意图",
                image_name=intent.image_name,
                task_id=task_id
            )

            # 后台启动扫描（不阻塞响应）
            background_tasks.add_task(
                _run_scan_task,
                task_id=task_id,
                image_name=intent.image_name,
                session_id=message.session_id or "default"
            )

            return ChatResponse(
                message=f"好的，开始扫描镜像 `{intent.image_name}`",
                type="scan_started",
                task_id=task_id,
                data={
                    "image_name": intent.image_name,
                    "confidence": intent.confidence
                }
            )

        elif intent.action == "query":
            # 普通查询
            response = await _handle_query(message.message)
            return ChatResponse(
                message=response,
                type="text"
            )

        else:
            # 未知意图
            return ChatResponse(
                message="抱歉，我只支持扫描 Docker 镜像。请说类似：'扫描 nginx:latest' 或 'scan nginx:latest'",
                type="text"
            )

    except Exception as e:
        logger.error("处理消息失败", error=str(e))
        raise HTTPException(status_code=500, detail=f"处理失败：{str(e)}")


async def _parse_intent(user_message: str) -> Intent:
    """
    使用 LLM 解析用户意图

    Args:
        user_message: 用户消息

    Returns:
        Intent: 解析后的意图
    """
    prompt = f"""你是一个意图识别助手。分析用户输入，判断其意图。

用户输入：{user_message}

请识别：
1. action - 用户想要做什么？
   - "scan": 用户想扫描 Docker 镜像
   - "query": 用户想查询或询问其他问题
   - "unknown": 无法识别

2. image_name - 如果 action 是 "scan"，提取镜像名称（如 "nginx:latest"）

3. confidence - 你的置信度（0-1）

返回 JSON 格式：
{{
    "action": "scan" | "query" | "unknown",
    "image_name": "镜像名称（如果适用）",
    "confidence": 0.95,
    "reasoning": "推理过程"
}}

规则：
- 如果用户说"扫描"、"scan"、"分析"等词，判定为 "scan"
- 镜像名称可能包含版本号（如 :latest、:v1.0）
- 如果用户只是问候或询问，判定为 "query"
"""

    try:
        result = await llm_client.think(prompt, temperature=0.0)

        # 确保 result 包含必需字段
        action = result.get("action", "unknown")
        image_name = result.get("image_name")
        confidence = result.get("confidence", 0.0)
        reasoning = result.get("reasoning", "")

        # 验证 action 值
        if action not in ["scan", "query", "unknown"]:
            action = "unknown"

        return Intent(
            action=action,
            image_name=image_name,
            confidence=confidence,
            reasoning=reasoning
        )

    except Exception as e:
        logger.error("解析意图失败", error=str(e))
        # 返回默认意图
        return Intent(
            action="unknown",
            confidence=0.0,
            reasoning="解析失败"
        )


async def _handle_query(user_message: str) -> str:
    """
    处理普通查询

    Args:
        user_message: 用户消息

    Returns:
        str: AI 回复
    """
    prompt = f"""用户问题：{user_message}

请简洁回答（不超过 50 字）。
如果是问候，请友好回应。
如果是关于 ImageScan 的问题，请介绍功能。
"""

    try:
        result = await llm_client.think(prompt, temperature=0.7)
        return result.get("answer", "抱歉，我没理解。请告诉我你想扫描哪个 Docker 镜像？")
    except Exception as e:
        logger.error("处理查询失败", error=str(e))
        return "抱歉，我遇到了一些问题。请稍后再试。"


async def _run_scan_task(task_id: str, image_name: str, session_id: str):
    """
    后台执行扫描任务

    Args:
        task_id: 任务 ID
        image_name: 镜像名称
        session_id: 会话 ID（当前未使用，保留以兼容 API 签名）
    """
    # session_id 参数保留以兼容 API 签名，但实际不再使用
    # 所有 WebSocket 事件现在通过 EventBus 广播给所有客户端
    _ = session_id  # 标记为有意未使用

    from ..websocket.manager import manager
    from ...utils.config import Config

    logger.info(
        "后台扫描任务启动",
        task_id=task_id,
        image_name=image_name
    )

    try:
        # 创建编排器（显式传递配置）
        config = Config()
        orchestrator = ScanOrchestrator(
            task_id=task_id,
            config=config
        )

        # 执行扫描
        result = await orchestrator.scan_image(image_name=image_name, output_file=f"output/{task_id}/result.json")

        # 扫描完成，发送 WebSocket 通知
        # 注意：scan_agent 已经通过 EventBus 发送了 task.completed 事件
        # 这里不再重复发送，避免事件类型不一致的问题
        # main.py 中的 _forward_to_websockets 会将所有 EventBus 事件转发给所有 WebSocket 客户端

        logger.info(
            "后台扫描任务完成",
            task_id=task_id,
            credential_count=result.get("credential_count", 0)
        )

    except Exception as e:
        logger.error("后台扫描任务失败", task_id=task_id, error=str(e))

        # 发送错误通知到所有 WebSocket 客户端（不限制 session）
        # 注意：scan_agent 应该已经发送了 TASK_FAILED 事件
        # 这里只发送简单的错误通知作为后备
        await manager.broadcast({
            "type": "error",
            "task_id": task_id,
            "source": "chat_router",
            "data": {
                "error_message": str(e),
                "error_type": "ScanError",
                "task_id": task_id
            }
        })
