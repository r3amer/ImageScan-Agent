"""
LLM 客户端模块

用途：
1. 封装 Google Gemini 2.5 Flash API 调用
2. 提供 JSON 模式响应
3. 支持结构化输出（系统提示 + 用户输入）
4. 错误处理和重试机制

参考：docs/TECH_STACK.md, docs/APP_FLOW.md
"""

import asyncio
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..utils.logger import get_logger
from ..utils.config import get_config

logger = get_logger(__name__)


class LLMClientError(Exception):
    """LLM 客户端异常"""
    pass


class LLMClient:
    """
    LLM 客户端

    使用 OpenAI SDK 调用 Gemini API
    强制 JSON 响应模式
    """

    # 系统提示词：容器安全专家（精简版 - 优化性能）
    SYSTEM_INSTRUCTION = """你是容器安全专家，负责分析 Docker 镜像中的敏感凭证和危险配置。

## 核心任务
识别文件中的真实敏感凭证（硬编码的密钥、密码、令牌等）和危险配置，忽略配置引用和占位符。

## 误报识别规则（严格遵守）

以下不是凭证，必须忽略（置信度<0.2）：

1. **环境变量引用**：os.environ['X'], os.getenv('X'), getenv('X')
2. **配置引用**：config.XXX, settings.XXX, app.config['XXX']
3. **占位符**："your_api_key_here", "CHANGE_ME", "TODO", "xxx", "****", "example", "test"
4. **空值**：password="", api_key=None
5. **注释**：# password=xxx

## 真实凭证（必须报告）

只有包含实际值的才是凭证：
- password="abc123"
- API_KEY="sk-1234567890"
- DB_URL="postgres://user:pass@host/db"
- -----BEGIN PRIVATE KEY-----

## 凭证类型
API_KEY, PASSWORD, TOKEN, CERTIFICATE, PRIVATE_KEY, DATABASE_URL, AWS_KEY, SSH_KEY, UNKNOWN

## 置信度标准
- 0.9-1.0: 明确包含实际值
- 0.7-0.9: 高度疑似实际值
- 0.5-0.7: 需确认
- 0.2-0.5: 可能是引用
- 0.0-0.2: 确定是引用

规则：宁可漏报，不要误报。只报告确定包含实际值的内容。"""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        初始化 LLM 客户端

        Args:
            api_key: Gemini API Key（默认从配置读取）
            base_url: API Base URL（默认使用 Gemini OpenAI 兼容端点）
        """
        config = get_config()

        # 从配置或参数获取 API Key
        self.api_key = api_key or config.api.gemini_api_key
        if not self.api_key:
            raise LLMClientError("GEMINI_API_KEY 未配置")

        # 使用 Gemini OpenAI 兼容端点
        self.base_url = base_url or "https://generativelanguage.googleapis.com/v1beta/openai/"

        # 初始化 OpenAI 客户端
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

        # 模型配置（使用 Gemini 2.5 Flash）
        self.model = "gemini-2.5-flash"

        # Token 统计
        self.total_tokens_used = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.call_count = 0

        logger.info(
            "LLM 客户端初始化",
            model=self.model,
            base_url=self.base_url
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError,))  # 移除 asyncio.TimeoutError
    )
    async def _call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        调用 LLM

        Args:
            messages: 消息列表
            temperature: 温度参数（0.0 = 确定性输出）
            max_tokens: 最大 token 数

        Returns:
            响应内容（JSON）

        Raises:
            LLMClientError: 调用失败
            asyncio.TimeoutError: 超时（传播到上层处理）
        """
        try:
            logger.debug(
                "LLM 请求",
                model=self.model,
                messages_count=len(messages),
                temperature=temperature
            )

            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"}
                ),
                timeout=60.0
            )

            # 提取响应内容
            content = response.choices[0].message.content

            # 解析 JSON
            result = json.loads(content)

            # 统计 token 使用
            if hasattr(response, 'usage') and response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens

                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                self.total_tokens_used += total_tokens
                self.call_count += 1

                logger.debug(
                    "LLM 响应成功",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    call_count=self.call_count
                )
            else:
                logger.debug("LLM 响应成功", tokens_used="N/A")

            return result

        except asyncio.TimeoutError:
            # 超时异常传播到上层，不在这里处理
            logger.error("LLM 请求超时", message_length=len(json.dumps(messages)))
            raise  # 重新抛出超时异常，让上层处理分段逻辑

        except json.JSONDecodeError as e:
            logger.error("LLM 响应 JSON 解析失败", error=str(e))
            raise LLMClientError(f"LLM 响应不是有效的 JSON: {e}")

        except Exception as e:
            logger.error("LLM 调用失败", error=str(e), error_type=type(e).__name__)
            raise LLMClientError(f"LLM 调用失败: {e}")

    async def think(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        temperature: float = 0.0
    ) -> Dict[str, Any]:
        """
        通用思考接口

        Args:
            prompt: 用户提示
            context: 上下文信息（可选）
            temperature: 温度参数

        Returns:
            LLM 响应（JSON）
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt}
        ]

        # 添加上下文（如果有）
        if context:
            context_str = json.dumps(context, ensure_ascii=False, indent=2)
            messages[1]["content"] = f"{prompt}\n\n上下文信息：\n{context_str}"
        
        print('%'*40)
        print(f"提示词\n\n{messages[1]['content']}")
        print('%'*30)

        return await self._call_llm(messages, temperature=temperature)

    async def validate_credential(
        self,
        credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证凭证的有效性（静态分析）

        Args:
            credential: 凭证信息

        Returns:
            {
                "is_valid": bool,
                "confidence": float,
                "reason": "原因说明",
                "suggestions": ["改进建议"]
            }
        """
        prompt = f"""验证以下凭证的有效性（基于静态分析）。

凭证信息：
{json.dumps(credential, ensure_ascii=False, indent=2)}

请分析：
1. 这个凭证看起来是有效的吗？
2. 它是否是测试/示例凭证？
3. 它是否已过期或被撤销？（基于上下文判断）
4. 置信度评估

返回 JSON 格式：
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "reason": "详细原因说明",
    "suggestions": ["改进建议1", "改进建议2"]
}}

规则：
- 对于明显的测试凭证（如 test_key、example.com），判定为无效
- 对于已脱敏的凭证（如 ******），判定为无效
- 对于格式不完整的凭证，降低置信度"""

        result = await self.think(prompt, temperature=0.0)

        logger.info(
            "凭证验证完成",
            cred_type=credential.get("cred_type"),
            is_valid=result.get("is_valid", False)
        )

        return result

    async def generate_scan_report(
        self,
        scan_metadata: Dict[str, Any],
        credentials: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        生成扫描报告摘要

        Args:
            scan_metadata: 扫描元数据
            credentials: 发现的凭证列表

        Returns:
            报告摘要
        """
        prompt = f"""生成扫描报告摘要。

扫描元数据：
{json.dumps(scan_metadata, ensure_ascii=False, indent=2)}

发现凭证数：{len(credentials)}

请返回 JSON 格式：
{{
    "summary": "简要总结（1-2句话）",
    "risk_level": "HIGH/MEDIUM/LOW",
    "key_findings": ["关键发现1", "关键发现2"],
    "recommendations": ["建议1", "建议2"],
    "statistics": {{
        "total_credentials": {len(credentials)},
        "by_type": {{"API_KEY": 5, "PASSWORD": 2}},
        "by_confidence": {{"high": 3, "medium": 2, "low": 2}}
    }}
}}

重点关注：
- 高风险凭证（置信度 > 0.8）
- 高置信度凭证数量
- 凭证类型分布"""

        result = await self.think(prompt, temperature=0.0)

        logger.info(
            "扫描报告生成完成",
            risk_level=result.get("risk_level", "UNKNOWN")
        )

        return result

    def get_token_usage(self) -> Dict[str, int]:
        """
        获取 token 使用统计

        Returns:
            {
                "total_tokens": int,
                "prompt_tokens": int,
                "completion_tokens": int,
                "call_count": int
            }
        """
        return {
            "total_tokens": self.total_tokens_used,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "call_count": self.call_count
        }

    async def close(self):
        """关闭客户端连接"""
        await self.client.close()
        logger.info("LLM 客户端已关闭")


# 全局 LLM 客户端实例（延迟加载）
_global_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """
    获取全局 LLM 客户端实例（单例模式）

    Returns:
        LLM 客户端实例
    """
    global _global_llm_client
    if _global_llm_client is None:
        _global_llm_client = LLMClient()
    return _global_llm_client
