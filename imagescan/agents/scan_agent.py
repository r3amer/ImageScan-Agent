"""
扫描智能体 - 真正的智能体实现

职责：
1. 自主规划扫描流程
2. 自己决定调用哪个工具
3. 根据中间结果动态调整策略
4. 目标驱动：发现敏感凭证

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

import json
import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..core.agent import Agent
from ..core.events import EventType, Event
from ..core.llm_client import LLMClient
from ..tools.registry import ToolRegistry
from ..utils.rules import RuleEngine
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
        rule_engine: RuleEngine,
        summary_manager: SummaryManager,
        task_id: str,
        image_name: str,
        config: Config,
        storage: SimpleStorageManager
    ):
        super().__init__("scan_agent", event_bus)

        self.llm = llm_client
        self.tools = tool_registry
        self.rule_engine = rule_engine
        self.summary = summary_manager
        self.task_id = task_id
        self.image_name = image_name
        self.config = config
        self.storage = storage  # 存储管理器

        # 智能体状态
        self.context = {}
        self.max_steps = 30

    async def process(self, **kwargs) -> Dict[str, Any]:
        """
        智能体主循环

        Returns:
            扫描结果
        """
        logger.info("ScanAgent 启动", task_id=self.task_id, image=self.image_name)

        start_time = datetime.utcnow()

        try:
            # 初始化上下文
            self.context = self._initialize_context()

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

                # 记录到摘要
                self.summary.add_message(
                    "tool",
                    f"步骤 {step + 1}: {decision.get('tool', 'unknown')} - {result.get('status', 'unknown')}"
                )

            # 完成扫描
            duration = (datetime.utcnow() - start_time).total_seconds()
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
            "goal": f"扫描 Docker 镜像 {self.image_name}，发现所有敏感凭证",
            "current_state": "initialized",
            "image_name": self.image_name,
            "current_step": 0,
            "findings": [],
            "errors": [],
            "output_path": unique_output_path,
            "task_id": self.task_id
        }

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
            # ===== 特殊处理：file.analyze_contents 工具 =====
            if tool_name == "file.analyze_contents":
                # 新格式：{success, data, summary}
                tool_result = result["result"]
                credentials_result = tool_result.get("data", {})

                # 计算统计信息
                total_files = len(credentials_result)
                files_with_credentials = sum(1 for creds in credentials_result.values() if creds)
                total_credentials = sum(len(creds) for creds in credentials_result.values())

                # 构建轻量级摘要
                summary = {
                    "total_files_analyzed": total_files,
                    "files_with_credentials": files_with_credentials,
                    "total_credentials_found": total_credentials,
                    "files_analyzed": list(credentials_result.keys())[:10]  # 只保留前10个文件名
                }

                # 将凭证存入 Storage
                for file_path, credentials in credentials_result.items():
                    for cred in credentials:
                        self.storage.add_credential_from_dict({
                            "cred_type": cred.get("cred_type", "UNKNOWN"),
                            "confidence": cred.get("confidence", 0.0),
                            "file_path": file_path,
                            "layer_id": cred.get("layer_id"),
                            "line_number": cred.get("line_number"),
                            "context": cred.get("context")
                        })

                # 更新上下文（只存储摘要，不存储完整凭证）
                new_context["last_tool"] = tool_name
                new_context["last_result"] = tool_result  # 存储完整结果（包含 summary）
                new_context["last_success"] = True
                new_context["last_error"] = None

                logger.info(
                    "凭证分析完成（已存入Storage）",
                    summary=summary
                )

            # ===== 通用更新：其他工具 =====
            else:
                new_context["last_tool"] = tool_name
                new_context["last_result"] = result["result"]
                new_context["last_success"] = True
                new_context["last_error"] = None  # 清除之前的错误

            # 更新状态（用最后执行的工具名）
            new_context["current_state"] = tool_name

            # 添加到工具历史（让 Agent 可以追溯）
            if "tool_history" not in new_context:
                new_context["tool_history"] = []

            # 对于 analyze_contents，只存储摘要
            history_result = new_context["last_result"]
            new_context["tool_history"].append({
                "tool": tool_name,
                "parameters": decision.get("parameters", {}),
                "result": history_result,
                "status": "success",
                "timestamp": datetime.utcnow().isoformat()
            })

            # 只保留最近 10 次历史（避免上下文过大）
            if len(new_context["tool_history"]) > 10:
                new_context["tool_history"] = new_context["tool_history"][-10:]

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
                "timestamp": datetime.utcnow().isoformat()
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
扫描 Docker 镜像，发现所有敏感凭证（API Keys、密码、Tokens、证书等）。

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
扫描 Docker 镜像，发现所有敏感凭证（API Keys、密码、Tokens、证书等）。

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
            event_type=EventType.ERROR,
            source="scan_agent",
            data={
                "task_id": self.task_id,
                "error": error_message
            }
        ))
