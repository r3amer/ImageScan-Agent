"""
扫描智能体 - 真正的智能体实现

职责：
1. 自主规划扫描流程
2. 自己决定调用哪个工具
3. 根据中间结果动态调整策略
4. 目标驱动：发现敏感凭证和危险配置

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

import json
import asyncio
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from ..core.agent import Agent
from ..core.events import EventType, Event
from ..core.llm_client import LLMClient
from ..tools.registry import ToolRegistry
from ..utils.summary import SummaryManager
from ..utils.config import Config
from ..utils.logger import get_logger
from ..storage.simple_storage import SimpleStorageManager

logger = get_logger(__name__)


class ScanAgent(Agent):
    """
    扫描智能体 - 自主规划的智能体

    工作流程：
    1. 接收目标：扫描镜像 X，发现凭证
    2. LLM 规划下一步
    3. 执行工具
    4. 观察结果
    5. 更新上下文
    6. 重复直到完成（最多 30 步）
    """

    def __init__(
        self,
        event_bus,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        summary_manager: SummaryManager,
        task_id: str,
        image_name: str,
        config: Config,
        storage: SimpleStorageManager,
        context_manager = None
    ):
        super().__init__("scan_agent", event_bus)

        self.llm = llm_client
        self.tools = tool_registry
        self.summary = summary_manager
        self.task_id = task_id
        self.image_name = image_name
        self.config = config
        self.storage = storage  # 存储管理器
        self.context_manager = context_manager  # 上下文管理器（可选）

        # 从 ContextManager 获取 MemoryStore（如果有）
        self.memory_store = None
        if context_manager:
            self.memory_store = context_manager.memory_store

        # 智能体状态
        self.context = {}
        self.max_steps = 30

        # ===== 调试：上下文快照保存 =====
        self.debug_enabled = config.system.debug_context
        self.debug_context_dir = f"{config.system.debug_context_path}/{self.task_id}"
        if self.debug_enabled:
            os.makedirs(self.debug_context_dir, exist_ok=True)
            logger.info("调试模式已启用", context_dir=self.debug_context_dir)

        # ===== 新增：注册凭证存储监听器 =====
        self._register_credential_listener()

    async def process(self, **kwargs) -> Dict[str, Any]:
        """
        智能体主循环

        Returns:
            扫描结果
        """
        logger.info("ScanAgent 启动", task_id=self.task_id, image=self.image_name)

        start_time = datetime.now(timezone.utc)

        try:
            # 初始化上下文
            self.context = self._initialize_context()

            # 记录扫描开始到 MemoryStore
            if self.memory_store:
                self.memory_store.record_scan_start(self.task_id, self.image_name)

            # 保存初始上下文快照
            self._save_context_snapshot(self.context, step=0, phase="initialization")

            # 发布扫描开始事件
            await self.event_bus.publish(Event(
                event_type=EventType.TASK_STARTED,
                source="scan_agent",
                data={
                    "task_id": self.task_id,
                    "image_name": self.image_name,
                    "max_steps": self.max_steps
                }
            ))

            # ===== 阶段 1: 准备阶段 - 生成扫描计划 =====
            logger.info("准备阶段：生成扫描计划")
            plan = await self._generate_scan_plan()

            if not plan or plan.get("status") == "error":
                logger.error("生成扫描计划失败", plan=plan)
                raise Exception("Failed to generate scan plan")

            logger.info("扫描计划生成成功", plan=plan.get("plan", "No plan"))
            self.context["scan_plan"] = plan.get("plan", "")

            # ===== 阶段 2: 执行阶段 - 按照计划执行工具 =====
            logger.info("执行阶段：按照计划执行")

            for step in range(self.max_steps):
                logger.info(
                    "智能体思考中",
                    step=step + 1,
                    max_steps=self.max_steps,
                    current_state=self.context.get("current_state")
                )

                # 发布进度事件
                percent = (step / self.max_steps) * 100
                await self._publish_progress(
                    step + 1,
                    self.context.get("current_state", "unknown"),
                    percent=percent
                )

                # LLM 规划下一步
                decision = await self._llm_plan_next_step(self.context)

                # 检查是否完成
                if decision.get("action") == "complete":
                    logger.info("LLM 决定完成任务", thought=decision.get("thought"))
                    break

                # 执行工具
                result = await self._execute_tool(decision)

                # 更新上下文
                self.context = self._update_context(self.context, decision, result)

                # 保存上下文快照
                self._save_context_snapshot(
                    self.context,
                    step=step + 1,
                    phase="execution",
                    decision=decision,
                    tool_result=result
                )

                # 记录到摘要
                self.summary.add_message(
                    "tool",
                    f"步骤 {step + 1}: {decision.get('tool', 'unknown')} - {result.get('status', 'unknown')}"
                )

            # 完成扫描
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            # 发布扫描完成事件
            await self._publish_scan_complete(duration)

            return self._build_result(duration)

        except Exception as e:
            logger.error("扫描失败", error=str(e))
            await self._publish_error(str(e))
            raise

    def _initialize_context(self) -> Dict:
        """初始化上下文"""
        # 为每个任务生成唯一的输出路径（基于 task_id）
        unique_output_path = f"{self.config.storage.output_path}/{self.task_id}"

        return {
            "goal": f"扫描 Docker 镜像 {self.image_name}，发现所有敏感凭证和危险配置",
            "current_state": "initialized",
            "image_name": self.image_name,
            "current_step": 0,
            "findings": [],
            "errors": [],
            "output_path": unique_output_path,
            "task_id": self.task_id
        }

    def _save_context_snapshot(
        self,
        context: Dict,
        step: int,
        phase: str = "execution",
        decision: Optional[Dict] = None,
        tool_result: Optional[Dict] = None
    ):
        """
        保存上下文快照用于调试

        Args:
            context: 当前上下文
            step: 步骤编号
            phase: 阶段名称（initialization, planning, execution, completion）
            decision: LLM 决策（可选）
            tool_result: 工具执行结果（可选）
        """
        if not self.debug_enabled:
            return

        try:
            timestamp = datetime.now(timezone.utc).isoformat()

            # 构建快照数据
            snapshot = {
                "metadata": {
                    "task_id": self.task_id,
                    "image_name": self.image_name,
                    "step": step,
                    "phase": phase,
                    "timestamp": timestamp
                },
                "decision": decision,
                "tool_result": self._sanitize_tool_result(tool_result) if tool_result else None,
                "context": self.context # self._sanitize_context(context)
            }

            # 保存到文件
            filename = f"step_{step:03d}_{phase}.json"
            filepath = os.path.join(self.debug_context_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)

            logger.debug("上下文快照已保存", step=step, phase=phase, filepath=filepath)

        except Exception as e:
            logger.warning("保存上下文快照失败", error=str(e))

    def _sanitize_context(self, context: Dict) -> Dict:
        """
        清理上下文数据，避免保存过大的内容

        Args:
            context: 原始上下文

        Returns:
            清理后的上下文
        """
        sanitized = context.copy()

        # 限制 tool_history 的大小
        if "tool_history" in sanitized:
            # 只保留最近的 3 次，且只保留关键字段
            history = []
            for item in sanitized["tool_history"][-3:]:
                history.append({
                    "tool": item.get("tool"),
                    "parameters": item.get("parameters"),
                    "status": item.get("status"),
                    "timestamp": item.get("timestamp")
                    # 不包含完整的 result
                })
            sanitized["tool_history"] = history

        # 限制 error_history 的大小
        if "error_history" in sanitized:
            sanitized["error_history"] = sanitized["error_history"][-2:]

        # 截断 last_result（如果存在）
        if "last_result" in sanitized and sanitized["last_result"]:
            result = sanitized["last_result"]
            if isinstance(result, dict):
                # 只保留摘要，截断详细数据
                if "summary" in result:
                    sanitized["last_result"] = {"summary": result["summary"]}
                else:
                    sanitized["last_result"] = {"status": result.get("status", "unknown")}
                # 如果包含 data 字段且是字典，只记录键
                if "data" in result and isinstance(result["data"], dict):
                    sanitized["last_result"]["data_keys"] = list(result["data"].keys())[:10]

        return sanitized

    def _sanitize_tool_result(self, result: Dict) -> Dict:
        """
        清理工具执行结果，避免保存过大的内容

        Args:
            result: 原始工具结果

        Returns:
            清理后的结果
        """
        if not isinstance(result, dict):
            return {"raw_type": str(type(result))}

        sanitized = {
            "status": result.get("status", "unknown")
        }

        # 只保留 summary 字段
        if "summary" in result:
            sanitized["summary"] = result["summary"]

        # 如果有 success 字段
        if "success" in result:
            sanitized["success"] = result["success"]

        # 如果有 error 字段
        if "error" in result:
            sanitized["error"] = result["error"]

        return sanitized

    async def _generate_scan_plan(self) -> Dict:
        """
        生成扫描计划（准备阶段）

        只告诉 LLM 目标和工具列表，让其生成计划

        Returns:
            计划决策
        """
        # 构建准备阶段的提示词
        system_prompt = self._get_planning_system_prompt()
        user_prompt = self._get_planning_user_prompt()

        # 添加到摘要
        self.summary.add_message("user", user_prompt)

        # 组合完整 prompt
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        try:
            # 使用 think 方法获取计划
            plan = await self.llm.think(
                prompt=full_prompt,
                context=self.context,
                temperature=0.0
            )

            # 记录到摘要
            self.summary.add_message("assistant", json.dumps(plan, ensure_ascii=False))

            return plan

        except Exception as e:
            logger.error("生成计划失败", error=str(e))
            return {
                "status": "error",
                "thought": f"生成计划失败: {str(e)}",
                "error": str(e)
            }

    def _check_repeat_call(self, context: Dict, tool_name: str, parameters: Dict) -> bool:
        """
        检查是否重复调用同一个工具

        Args:
            context: 当前上下文
            tool_name: 工具名称
            parameters: 工具参数

        Returns:
            True 表示重复调用
        """
        tool_history = context.get("tool_history", [])

        # 检查历史中是否有相同工具和参数的调用
        for i in range(min(3, len(tool_history))):  # 检查最近3次
            history_item = tool_history[-(i + 1)]
            if (history_item["tool"] == tool_name and
                history_item["parameters"] == parameters and
                history_item["status"] == "success"):
                return True

        return False

    async def _llm_plan_next_step(self, context: Dict) -> Dict:
        """
        LLM 规划下一步（执行阶段）

        Args:
            context: 当前上下文

        Returns:
            决策：{thought, action, tool, parameters}
        """
        system_prompt = self._get_system_prompt()

        # 使用 ContextManager 构建 prompt（如果启用）
        if self.context_manager and self.config.context_management.enabled:
            user_prompt = await self.context_manager.build_prompt_context(context)
        else:
            user_prompt = self._build_user_prompt(context)

        # 添加到摘要
        self.summary.add_message("user", user_prompt)

        # 组合完整 prompt
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        max_retries = 2  # 429 错误最大重试次数
        for attempt in range(max_retries + 1):
            try:
                # 使用 think 方法
                decision = await self.llm.think(
                    prompt=full_prompt,
                    context=context,
                    temperature=0.0
                )

                # 记录到摘要
                self.summary.add_message("assistant", json.dumps(decision, ensure_ascii=False))

                # 验证返回格式
                if not isinstance(decision, dict):
                    logger.error("LLM 返回格式错误", type=type(decision))
                    return {
                        "action": "error",
                        "thought": f"LLM 返回格式错误: {type(decision)}",
                        "error": "Invalid response format"
                    }

                # 检查重复调用
                if decision.get("action") == "tool_call":
                    tool_name = decision.get("tool")
                    parameters = decision.get("parameters", {})
                    if self._check_repeat_call(context, tool_name, parameters):
                        logger.warning("检测到重复调用", tool=tool_name, parameters=parameters)
                        # 强制完成
                        return {
                            "action": "complete",
                            "thought": f"检测到重复调用工具 {tool_name}，可能已陷入循环。强制完成任务以避免无限循环。",
                            "reason": "repeat_call_detected"
                        }

                return decision

            except Exception as e:
                error_str = str(e)
                error_type = type(e).__name__

                # 检查是否是 429 错误（速率限制）
                is_rate_limit = (
                    "429" in error_str or
                    "rate limit" in error_str.lower() or
                    "too many requests" in error_str.lower() or
                    "quota" in error_str.lower()
                )

                if is_rate_limit and attempt < max_retries:
                    # 429 错误：压缩上下文并重试
                    wait_time = 5 * (attempt + 1)  # 5s, 10s
                    logger.warning(
                        f"遇到速率限制错误 (429)，等待 {wait_time}s 后重试",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error=error_str
                    )

                    # 等待
                    await asyncio.sleep(wait_time)

                    # 压缩上下文
                    logger.info("压缩对话上下文以减少 token 使用")
                    self._compress_context(context)

                    # 重建 prompt（使用压缩后的上下文）
                    if self.context_manager and self.config.context_management.enabled:
                        user_prompt = await self.context_manager.build_prompt_context(context)
                    else:
                        user_prompt = self._build_user_prompt(context)
                    full_prompt = f"{system_prompt}\n\n{user_prompt}"

                    # 继续重试
                    continue

                # 其他错误或重试用尽
                if "JSON" in error_type or "decode" in error_str.lower():
                    logger.error("LLM 响应 JSON 解析失败", error=error_str)
                    return {
                        "action": "error",
                        "thought": f"JSON 解析失败: {error_str}",
                        "error": error_str
                    }
                else:
                    logger.error("LLM 规划失败", error=error_str, error_type=error_type)
                    return {
                        "action": "error",
                        "thought": f"LLM 规划失败: {error_str}",
                        "error": error_str
                    }

    def _compress_context(self, context: Dict):
        """
        压缩上下文以减少 token 使用

        清理不必要的历史数据，保留关键信息
        """
        # 清理工具历史（只保留最近 3 次）
        if "tool_history" in context:
            context["tool_history"] = context["tool_history"][-3:]

        # 清理错误历史（只保留最近 1 次）
        if "error_history" in context:
            context["error_history"] = context["error_history"][-1:]

        # 清理摘要历史
        self.summary.clear_history()

        logger.info(
            "上下文已压缩",
            remaining_tools=len(context.get("tool_history", [])),
            remaining_errors=len(context.get("error_history", []))
        )

    def _is_credential_dict(self, data: Dict) -> bool:
        """
        检查数据是否是凭证字典格式 {file_path: [credentials]}

        Args:
            data: 要检查的数据

        Returns:
            是否是凭证字典
        """
        if not isinstance(data, dict):
            return False

        # 检查是否包含非凭证列表的字段（如 suspicious_files, statistics 等）
        non_credential_fields = {
            "suspicious_files", "statistics", "summary",
            "high_confidence", "medium_confidence", "low_confidence",
            "filtered_count", "total_files", "total_layers"
        }
        if any(key in data for key in non_credential_fields):
            return False

        # 检查是否所有值都是列表
        return all(isinstance(v, list) for v in data.values())

    def _is_valid_credential_object(self, obj: Dict) -> bool:
        """
        检查对象是否是有效的凭证对象

        有效的凭证对象必须包含至少一个凭证相关字段：
        - cred_type
        - confidence
        - context 或 raw_value

        Args:
            obj: 要检查的对象

        Returns:
            是否是有效的凭证对象
        """
        if not isinstance(obj, dict):
            return False

        # 检查是否包含凭证相关字段
        has_cred_fields = any(key in obj for key in [
            "cred_type", "confidence", "context", "raw_value"
        ])

        # 排除只包含 layer_id 和 file_path 的对象（这些是 suspicious_files 元素）
        if "layer_id" in obj and "file_path" in obj and not has_cred_fields:
            return False

        return has_cred_fields

    async def _execute_tool(self, decision: Dict) -> Dict:
        """
        执行工具

        Args:
            decision: LLM 决策

        Returns:
            执行结果
        """
        action = decision.get("action")

        if action == "complete":
            return {"status": "completed"}

        if action == "error":
            return {"status": "error", "error": decision.get("error")}

        if action != "tool_call":
            return {
                "status": "error",
                "error": f"未知操作: {action}"
            }

        tool_name = decision.get("tool")
        parameters = decision.get("parameters", {})

        logger.info("执行工具", tool=tool_name, parameters=parameters)

        try:
            # 调用工具（使用 call 方法）
            result = await self.tools.call(tool_name, **parameters)

            # ===== 新增：检查是否发现凭证，发布事件 =====
            if result.get("success") and isinstance(result, dict):
                data = result.get("data", {})

                # 检查是否包含凭证信息
                # 支持两种格式：
                # 1. 直接包含 credentials 字段
                # 2. data 本身就是凭证字典 {file_path: [credentials]}
                credentials = None
                if "credentials" in data:
                    credentials = data["credentials"]
                elif self._is_credential_dict(data):
                    # data 是 {file_path: [credentials]} 格式
                    # 提取所有凭证到一个列表
                    credentials = []
                    for _file_path, creds in data.items():
                        if isinstance(creds, list):
                            # 验证列表中的元素是凭证对象（包含必要字段）
                            for cred in creds:
                                if isinstance(cred, dict) and self._is_valid_credential_object(cred):
                                    credentials.append(cred)

                if credentials:
                    # 收集文件路径（如果有）
                    file_paths = []
                    if isinstance(credentials, dict):
                        # 格式：{file_path: [credentials]}
                        file_paths = list(credentials.keys())
                    elif isinstance(credentials, list):
                        # 格式：[{credentials}]
                        for cred in credentials:
                            if isinstance(cred, dict) and "file_path" in cred:
                                file_paths.append(cred["file_path"])

                    # 发布凭证发现事件
                    from ..core.events import create_credentials_discovered
                    await self.event_bus.publish(create_credentials_discovered(
                        tool_name=tool_name,
                        task_id=self.task_id,
                        credentials=credentials,
                        file_paths=file_paths
                    ))

                    logger.info(
                        "发布凭证发现事件",
                        tool=tool_name,
                        count=len(credentials)
                    )

            return {
                "status": "success",
                "tool": tool_name,
                "result": result
            }

        except Exception as e:
            logger.error("工具执行失败", tool=tool_name, error=str(e))
            return {
                "status": "error",
                "tool": tool_name,
                "error": str(e)
            }

    def _update_context(self, context: Dict, decision: Dict, result: Dict) -> Dict:
        """
        更新上下文 - 为 Agent 提供完整信息，而不是替 Agent 思考

        Args:
            context: 当前上下文
            decision: LLM 决策
            result: 工具执行结果

        Returns:
            更新后的上下文
        """
        new_context = context.copy()

        # 获取工具信息
        tool_name = result.get("tool")
        status = result.get("status")

        if status == "success":
            # ===== 通用更新：所有工具统一处理 =====
            # 注意：凭证存储已通过事件驱动处理，不再在这里硬编码
            new_context["last_tool"] = tool_name
            new_context["last_result"] = result["result"]
            new_context["last_success"] = True
            new_context["last_error"] = None  # 清除之前的错误

            # 更新状态（用最后执行的工具名）
            new_context["current_state"] = tool_name

            # # 添加到工具历史（让 Agent 可以追溯）
            # if "tool_history" not in new_context:
            #     new_context["tool_history"] = []

            # new_context["tool_history"].append({
            #     "tool": tool_name,
            #     "parameters": decision.get("parameters", {}),
            #     "result": result["result"],  # 存储完整结果
            #     "status": "success",
            #     "timestamp": datetime.now(timezone.utc).isoformat()
            # })

            # # 只保留最近 10 次历史（避免上下文过大）
            # if len(new_context["tool_history"]) > 10:
            #     new_context["tool_history"] = new_context["tool_history"][-10:]

            # 更新步数
            new_context["current_step"] = context.get("current_step", 0) + 1

        elif status == "error":
            # 错误处理
            new_context["last_tool"] = tool_name
            new_context["last_error"] = result.get("error")
            new_context["last_success"] = False

            # 错误历史
            if "error_history" not in new_context:
                new_context["error_history"] = []
            new_context["error_history"].append({
                "tool": tool_name,
                "error": result.get("error"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            # 只保留最近 5 次错误
            if len(new_context["error_history"]) > 5:
                new_context["error_history"] = new_context["error_history"][-5:]

            # 添加到总的错误列表
            if "errors" not in new_context:
                new_context["errors"] = []
            new_context["errors"].append({
                "tool": tool_name,
                "error": result.get("error"),
                "step": context.get("current_step", 0)
            })

        return new_context

    def _build_result(self, duration: float) -> Dict:
        """构建最终结果"""
        # 从存储中获取凭证
        credentials = self.storage.get_credentials()

        return {
            "task_id": self.task_id,
            "image_name": self.image_name,
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
                for cred in credentials
            ],
            "credential_count": len(credentials),
            "steps_taken": self.context.get("current_step", 0),
            "duration_seconds": duration,
            "final_state": self.context.get("current_state"),
            "errors": self.context.get("errors", [])
        }

    def _get_system_prompt(self) -> str:
        """获取执行阶段的 System Prompt"""
        tools_desc = self.tools.list_tools()

        return f"""你是 Docker 镜像安全扫描智能体。

## 目标
扫描 Docker 镜像，发现所有敏感凭证（API Keys、密码、Tokens、证书等）和危险配置。

## 可用工具
{tools_desc}

## 重要原则
1. **避免重复调用**：不要重复调用相同的工具和参数，这会浪费资源
2. **检查返回值**：每个工具返回后，检查返回值，决定下一步
3. **进度追踪**：关注工具执行历史，了解已完成的步骤
4. **完成条件**：当所有文件已扫描完成，或没有更多文件需要处理时，调用 complete
5. 在控制对话长度的条件下进行扫描

## 决策格式（严格遵守）
你必须严格按照以下 JSON 格式返回决策：

```json
{{
    "thought": "你的思考过程",
    "action": "tool_call",
    "tool": "工具名称（必须是上面可用工具列表中的一个）",
    "parameters": {{
        "参数名1": "参数值1",
        "参数名2": "参数值2"
    }}
}}
```

或者完成扫描时：
```json
{{
    "thought": "扫描已完成的原因",
    "action": "complete"
}}
```

## 关键字段说明
- action: 必须是 "tool_call" 或 "complete"，不能是其他值
- tool: 当 action 为 "tool_call" 时，必须提供工具名称
- parameters: 工具参数，根据工具描述填写

## 错误示例（不要这样做）
❌ {{"action": "tool_code", "tool_code": "xxx"}} - 错误的 action
❌ {{"action": "execute", "command": "xxx"}} - 错误的 action
✅ {{"action": "tool_call", "tool": "xxx", "parameters": {{}}}} - 正确
"""

    def _get_planning_system_prompt(self) -> str:
        """获取准备阶段的 System Prompt"""
        tools_desc = self.tools.list_tools()

        return f"""你是 Docker 镜像安全扫描智能体。

## 目标
扫描 Docker 镜像，发现所有敏感凭证（API Keys、密码、Tokens、证书等）和危险配置。

## 可用工具
{tools_desc}

## 任务
生成一个详细的扫描计划，说明如何使用上述工具完成扫描目标。

## 计划格式
返回 JSON：
{{
    "thought": "你的思考过程",
    "plan": "步骤 1：...\\n步骤 2：...\\n..."
}}
"""

    def _get_planning_user_prompt(self) -> str:
        """获取准备阶段的 User Prompt"""
        return f"""## 扫描任务
目标：{self.context['goal']}
镜像名称：{self.image_name}
输出路径：{self.context['output_path']}

请生成一个详细的扫描计划。"""

    def _format_tool_result(self, tool_name: str, result: Any) -> List[str]:
        """
        通用工具结果格式化

        不再硬编码每个工具的处理逻辑，而是让工具自己返回 summary

        Args:
            tool_name: 工具名称
            result: 工具执行结果

        Returns:
            格式化的输出行列表
        """
        # 如果结果包含 summary，直接使用
        if isinstance(result, dict) and "summary" in result:
            summary = result["summary"]
            if isinstance(summary, list):
                return [str(line) for line in summary]
            return [str(summary)]

        # 如果结果包含 success 字段且为 False，显示错误
        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("error", "执行失败")
            return [f"❌ {tool_name} 执行失败：{error_msg}"]

        # 默认格式化
        return [f"✅ {tool_name} 执行完成"]

    def _build_user_prompt(self, context: Dict) -> str:
        """构建 User Prompt - 动态展示工具执行结果"""
        context_parts = [
            f"## 当前状态",
            f"目标：{context['goal']}",
            f"已执行步骤：{context.get('current_step', 0)} / {self.max_steps}",
            f"当前阶段：{context.get('current_state', 'initialized')}",
        ]

        # 显示计划
        if "scan_plan" in context:
            context_parts.append(f"\n## 扫描计划")
            context_parts.append(f"{context['scan_plan']}")

        # 最近工具执行结果
        if "last_tool" in context:
            context_parts.append(f"\n## 最近执行的工具：{context['last_tool']}")

            # 通用格式化工具结果（不再硬编码）
            formatted = self._format_tool_result(
                context['last_tool'],
                context['last_result']
            )
            context_parts.extend(formatted)

        # 工具执行历史（最近 5 次）
        if "tool_history" in context and context["tool_history"]:
            history = context["tool_history"][-5:]
            context_parts.append(f"\n## 工具执行历史（最近 {len(history)} 次）")
            for i, item in enumerate(history, 1):
                result_preview = str(item['result'])[:100]
                context_parts.append(f"{i}. {item['tool']}")
                context_parts.append(f"   参数：{json.dumps(item['parameters'], ensure_ascii=False)}")
                context_parts.append(f"   结果：{result_preview}...")

        # 错误历史
        if "error_history" in context and context["error_history"]:
            context_parts.append(f"\n## 最近的错误")
            for item in context["error_history"][-3:]:
                context_parts.append(f"- {item['tool']}: {item['error']}")

        context_parts.append(f"\n## 请规划下一步")
        context_parts.append(f"根据上述工具执行结果和你的目标，决定下一步操作。")

        return "\n".join(context_parts)

    async def _publish_error(self, error_message: str):
        """发布错误事件"""
        await self.event_bus.publish(Event(
            event_type=EventType.TASK_FAILED,
            source="scan_agent",
            data={
                "task_id": self.task_id,
                "image_name": self.image_name,
                "error": error_message
            }
        ))

    async def _publish_progress(
        self,
        step: int,
        current_state: str,
        tool_name: Optional[str] = None,
        percent: float = 0.0
    ):
        """发布进度事件"""
        await self.event_bus.publish(Event(
            event_type=EventType.TASK_PROGRESS,
            source="scan_agent",
            data={
                "task_id": self.task_id,
                "step": step,
                "max_steps": self.max_steps,
                "current_state": current_state,
                "tool": tool_name,
                "percent": percent
            }
        ))

    async def _publish_credential_found(
        self,
        cred_type: str,
        confidence: float,
        file_path: str
    ):
        """发布凭证发现事件"""
        await self.event_bus.publish(Event(
            event_type=EventType.FILE_CREDENTIAL_FOUND,
            source="scan_agent",
            data={
                "task_id": self.task_id,
                "cred_type": cred_type,
                "confidence": confidence,
                "file_path": file_path
            }
        ))

    async def _publish_scan_complete(self, duration: float):
        """发布扫描完成事件"""
        # 保存完成时的上下文快照
        final_step = self.context.get("current_step", 0)
        self._save_context_snapshot(
            self.context,
            step=final_step,
            phase="completion",
            decision={"action": "complete", "thought": "扫描完成"},
            tool_result=None
        )

        credentials = self.storage.get_credentials()
        stats = self.storage.get_statistics()

        # 记录扫描完成到 MemoryStore
        if self.memory_store:
            self.memory_store.record_scan_complete(
                task_id=self.task_id,
                image_name=self.image_name,
                total_layers=stats.total_layers,
                total_files=stats.total_files,
                scanned_files=stats.scanned_files,
                credentials_count=len(credentials)
            )

        # 转换凭证格式为前端期望的格式
        credentials_list = []
        for cred in credentials:
            credentials_list.append({
                "type": cred.cred_type,
                "confidence": cred.confidence,
                "file_path": cred.file_path,
                "line_number": getattr(cred, 'line_number', None),
                "layer_id": getattr(cred, 'layer_id', None),
                "context": getattr(cred, 'context', None),
            })

        await self.event_bus.publish(Event(
            event_type=EventType.TASK_COMPLETED,
            source="scan_agent",
            data={
                "task_id": self.task_id,
                "image_name": self.image_name,
                "duration": duration,
                "credentials_count": len(credentials_list),
                "credentials": credentials_list,  # 添加完整的凭证列表
                "statistics": stats.to_dict(),  # 使用 ScanStatistics.to_dict() 方法
            }
        ))

    def _register_credential_listener(self):
        """
        注册凭证存储监听器

        监听 CREDENTIALS_DISCOVERED 事件，自动将凭证存储到 SimpleStorageManager
        这是事件驱动架构的关键：工具和存储解耦
        """
        from ..core.events import EventType

        async def on_credentials_discovered(event):
            """
            凭证发现事件处理器

            Args:
                event: Event 对象，包含 credentials, task_id 等信息
            """
            data = event.data
            credentials = data.get("credentials", [])

            if not credentials:
                return

            # 存储每个凭证到 SimpleStorageManager
            for cred_data in credentials:
                self.storage.add_credential_from_dict({
                    "cred_type": cred_data.get("cred_type", "UNKNOWN"),
                    "confidence": cred_data.get("confidence", 0.0),
                    "file_path": cred_data.get("file_path", ""),
                    "layer_id": cred_data.get("layer_id"),
                    "line_number": cred_data.get("line_number"),
                    "context": cred_data.get("context")
                })

                # 记录凭证模式到 MemoryStore（用于历史学习）
                if self.memory_store:
                    cred_type = cred_data.get("cred_type", "UNKNOWN")
                    confidence = cred_data.get("confidence", 0.0)
                    context = cred_data.get("context", "")

                    # 生成模式字符串（用于识别重复模式）
                    pattern = f"{cred_type} in {cred_data.get('file_path', '')}"
                    if context:
                        # 截取前 100 字符作为模式的一部分
                        pattern += f": {context[:100]}"

                    self.memory_store.record_credential_pattern(
                        pattern=pattern,
                        confidence=confidence,
                        context=context
                    )

            logger.info(
                "凭证已自动存储到 Storage",
                count=len(credentials),
                source=event.source,
                file_paths=data.get("file_paths", [])
            )

        # 订阅凭证发现事件
        self.event_bus.subscribe(
            EventType.CREDENTIALS_DISCOVERED,
            "scan_agent",  # agent_name
            on_credentials_discovered
        )

        logger.info(
            "凭证存储监听器已注册",
            event_type=EventType.CREDENTIALS_DISCOVERED
        )

