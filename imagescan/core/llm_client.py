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

    # 系统提示词：容器安全专家
    SYSTEM_INSTRUCTION = """你是一个容器安全专家，专门负责分析 Docker 镜像中的敏感凭证。

你的核心能力：
1. 识别各种类型的敏感凭证（API密钥、密码、证书、私钥等）
2. 分析文件名和内容，判断是否包含敏感信息
3. 评估凭证的有效性和风险等级
4. 减少误报，提高准确率

重要规则：
- 始终以 JSON 格式返回结果
- 如果不确定，设置较低的置信度
- 只报告真正可能包含敏感凭证的内容
- 忽略明显的系统文件和配置模板
- 对于脱敏内容（如 ***、******），判断为非凭证

## 误报识别（非常重要，必须严格遵守）

以下情况【不是】泄露的凭证，请忽略或设置极低置信度（< 0.2）：

### 1. 环境变量引用（仅引用，无实际值）
❌ 误报案例：
- os.environ['PASSWORD']
- os.getenv('API_KEY')
- os.environ.get('SECRET_KEY')
- environ['DATABASE_URL']
- getenv('REDIS_PASSWORD')

✅ 判断依据：这些只是从环境变量读取配置，密码值不在这行代码中

### 2. 配置对象引用（仅引用，无实际值）
❌ 误报案例：
- config.DATABASE_URL
- settings.API_KEY
- app.config['SECRET_KEY']
- Config.DB_PASSWORD
- self.config.password

✅ 判断依据：这些只是从配置对象读取，实际值在其他地方

### 3. 模板/占位符（明显的占位符）
❌ 误报案例：
- "your_api_key_here"
- "CHANGE_ME"
- "TODO"
- "xxx", "xxxx", "xxxxx"
- "****", "******"
- "example", "test", "demo"
- "${PASSWORD}", "%API_KEY%", "$DB_URL"

✅ 判断依据：这些是模板或占位符，不是真实的凭证

### 4. 空值/默认值
❌ 误报案例：
- password = ""
- api_key = None
- secret = ""

✅ 判断依据：空值不是有效的凭证

### 5. 变量名/注释（仅提到关键词）
❌ 误报案例：
- # API_KEY=sk-1234
- # password: abc123
- TODO: set API_KEY here

✅ 判断依据：注释或文档中的示例，不是实际使用

## 真正的凭证泄露（应该报告）

只有包含【实际敏感信息值】的才是真正的凭证泄露：

✅ 真实凭证案例：
- password = "abc123"                    # 硬编码密码
- API_KEY = "sk-1234567890abcdef"        # 硬编码密钥
- DB_URL = "postgres://user:pass@host/db" # 完整连接字符串
- -----BEGIN PRIVATE KEY-----              # 实际私钥内容
- AIzaSyDFI4KvZASwUXqzaqwL9F07rChEb4UUX2c  # 实际 API Key

凭证类型分类：
- API_KEY: API 密钥（sk-、xoxb-、AKIA... 等）
- PASSWORD: 密码（password、passwd 等）
- TOKEN: 令牌（token、bearer、jwt 等）
- CERTIFICATE: 证书（.crt、.pem、.cer 等）
- PRIVATE_KEY: 私钥（.key、private_key 等）
- DATABASE_URL: 数据库连接字符串
- AWS_KEY: AWS 访问密钥
- SSH_KEY: SSH 密钥
- UNKNOWN: 其他未知类型

置信度评分：
- 0.9-1.0: 极高置信度（明确包含敏感凭证的实际值）
- 0.7-0.9: 高置信度（高度疑似包含实际值）
- 0.5-0.7: 中等置信度（疑似，需人工确认）
- 0.2-0.5: 低置信度（不确定，可能是引用）
- 0.0-0.2: 极低置信度（基本确定是引用或占位符，仅在有明确值时才报告）

记住：宁可漏报，不要误报。只报告你确定包含实际敏感信息的内容。"""

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
        retry=retry_if_exception_type((asyncio.TimeoutError, ConnectionError))
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
            logger.error("LLM 请求超时")
            raise LLMClientError("LLM 请求超时")

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

        return await self._call_llm(messages, temperature=temperature)

    async def analyze_filenames(
        self,
        filenames: List[str],
        layer_id: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """
        分析文件名，识别可能包含敏感凭证的文件

        Args:
            filenames: 文件名列表
            layer_id: 层 ID（可选）

        Returns:
            {
                "high_confidence": [...],  # 高置信度敏感文件
                "medium_confidence": [...],  # 中等置信度
                "low_confidence": [...]  # 低置信度
            }
        """
        if not filenames:
            return {"high_confidence": [], "medium_confidence": [], "low_confidence": []}

        # 限制文件数量（避免 token 超限）
        max_files = 5000
        if len(filenames) > max_files:
            logger.warning(
                "文件数量过多，进行截断",
                total_files=len(filenames),
                truncated=max_files
            )
            filenames = filenames[:max_files]

        prompt = f"""分析以下 {len(filenames)} 个文件名，识别可能包含敏感凭证的文件。

文件名列表：
{json.dumps(filenames, ensure_ascii=False, indent=2)}

请将文件分为三类：
1. high_confidence: 极高可能是敏感文件（如 .env、config.json、secret.pem 等）
2. medium_confidence: 可能是敏感文件（如 config、settings 等）
3. low_confidence: 疑似敏感文件（需要进一步检查）

返回 JSON 格式：
{{
    "high_confidence": ["文件路径1", "文件路径2"],
    "medium_confidence": ["文件路径3"],
    "low_confidence": ["文件路径4"]
}}

规则：
- 忽略系统目录（/usr、/bin、/lib、/etc/passwd 等）
- 忽略明显的库文件（node_modules、vendor 等）
- 重点关注配置文件、环境文件、密钥文件
- 对于测试文件、示例文件，降低置信度"""

        result = await self.think(prompt, temperature=0.0)

        # 验证返回格式
        for key in ["high_confidence", "medium_confidence", "low_confidence"]:
            if key not in result:
                result[key] = []

        logger.info(
            "文件名分析完成",
            layer_id=layer_id,
            high_count=len(result.get("high_confidence", [])),
            medium_count=len(result.get("medium_confidence", [])),
            low_count=len(result.get("low_confidence", []))
        )

        return result

    async def analyze_file_contents(
        self,
        file_path: str,
        content: str,
        layer_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        分析文件内容，检测敏感凭证

        Args:
            file_path: 文件路径
            content: 文件内容
            layer_id: 层 ID（可选）

        Returns:
            检测到的凭证列表：
            [
                {
                    "cred_type": "API_KEY",
                    "confidence": 0.95,
                    "context": "原始内容片段（脱敏）",
                    "line_number": 10,
                    "metadata": {...}
                }
            ]
        """
        # 限制内容长度（避免 token 超限）
        max_length = 10000
        if len(content) > max_length:
            content = content[:max_length] + "\n... (内容已截断)"
            logger.warning(
                "文件内容过长，进行截断",
                file_path=file_path,
                original_length=len(content),
                truncated=max_length
            )

        prompt = f"""分析以下文件内容，检测其中的敏感凭证。

文件路径：{file_path}

文件内容：
```
{content}
```

请返回 JSON 格式：
{{
    "credentials": [
        {{
            "cred_type": "凭证类型（API_KEY/PASSWORD/TOKEN/CERTIFICATE/PRIVATE_KEY/DATABASE_URL/AWS_KEY/SSH_KEY/UNKNOWN）",
            "confidence": 置信度（0.0-1.0的浮点数）,
            "context": "包含凭证的上下文（截取关键部分，不超过200字符）",
            "line_number": 行号（如果可以推断）,
            "raw_value": "原始凭证值（如果可能提取，否则为null）",
            "metadata": {{
                "additional_info": "其他补充信息"
            }}
        }}
    ]
}}

规则：
- 只报告真正可能包含敏感凭证的内容
- 如果没有发现敏感凭证，返回空数组 []
- 对于已脱敏的内容（如 ***、******），不要报告
- 对于明显的示例文本（如 your_api_key_here），不要报告
- 置信度应该基于格式匹配和上下文判断
- 如果能提取原始凭证值，填写 raw_value（否则为 null）"""

        result = await self.think(prompt, temperature=0.0)

        # 验证返回格式
        if "credentials" not in result:
            result["credentials"] = []

        credentials = result["credentials"]

        # 添加文件路径信息
        for cred in credentials:
            cred["file_path"] = file_path
            if "layer_id" not in cred:
                cred["layer_id"] = layer_id

        logger.info(
            "文件内容分析完成",
            file_path=file_path,
            layer_id=layer_id,
            credentials_found=len(credentials)
        )

        return credentials

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
