"""
验证 Agent

职责：
1. 验证凭证的有效性
2. 静态分析凭证格式
3. 判断是否为误报
4. 更新验证状态

参考：docs/APP_FLOW.md
"""

import asyncio
from typing import Dict, Any, List, Optional
import re
from datetime import datetime

from ..core.agent import BaseAgent
from ..core.events import EventType
from ..core.llm_client import get_llm_client
from ..utils.logger import get_logger
from ..utils.database import Database, get_database
from ..models.credential import Credential, ValidationStatus, CredentialType

logger = get_logger(__name__)


class ValidationAgent(BaseAgent):
    """
    验证 Agent

    负责凭证验证：
    1. 静态格式验证
    2. LLM 智能验证
    3. 误报判断
    4. 状态更新
    """

    def __init__(self, event_bus=None, database: Optional[Database] = None):
        super().__init__("ValidationAgent", event_bus)

        self.database = database or get_database()
        self.llm_client = get_llm_client()

        # 验证规则
        self._init_validation_rules()

    def _init_validation_rules(self):
        """初始化验证规则"""
        # AWS Key 格式
        self.aws_access_key_pattern = re.compile(r'^AKIA[0-9A-Z]{16}$')
        self.aws_secret_key_pattern = re.compile(r'^[0-9a-zA-Z/+]{40}$')

        # API Key 格式（常见模式）
        self.api_key_patterns = {
            'sk-': re.compile(r'^sk-[a-zA-Z0-9]{48}$'),  # OpenAI
            'xoxb-': re.compile(r'^xoxb-[0-9]{13}-[0-9]{24}$'),  # Slack Bot
            'AKIA': re.compile(r'^AKIA[0-9A-Z]{16}$'),  # AWS
        }

        # JWT 格式
        self.jwt_pattern = re.compile(r'^eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$')

        # 测试/示例关键词
        self.test_keywords = [
            'test', 'demo', 'example', 'sample', 'placeholder',
            'xxx', '***', 'your_api_key', 'your_key', 'replace_with'
        ]

    async def process(
        self,
        task_id: str,
        credential_ids: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        验证凭证

        Args:
            task_id: 任务 ID
            credential_ids: 凭证 ID 列表（None 表示验证任务的所有凭证）
            **kwargs: 其他参数

        Returns:
            验证结果
        """
        logger.info(
            "开始验证凭证",
            task_id=task_id,
            count=len(credential_ids) if credential_ids else "all"
        )

        # 获取凭证列表
        if credential_ids:
            credentials = []
            for cred_id in credential_ids:
                # TODO: 实现 get_credential_by_id
                pass
        else:
            credentials = await self.database.get_credentials_by_task(task_id)

        if not credentials:
            logger.info("无凭证需要验证", task_id=task_id)
            return {
                "task_id": task_id,
                "status": "success",
                "verified": 0,
                "valid": 0,
                "invalid": 0,
                "skipped": 0
            }

        # 验证每个凭证
        verified = 0
        valid = 0
        invalid = 0
        skipped = 0

        for cred_dict in credentials:
            try:
                # 构建凭证对象
                credential = Credential(**cred_dict)

                # 执行验证
                validation_result = await self._validate_credential(credential)

                # 更新验证状态
                # TODO: 实现 update_credential_validation_status

                verified += 1
                if validation_result["is_valid"]:
                    valid += 1
                else:
                    invalid += 1

            except Exception as e:
                logger.warning(
                    "凭证验证失败",
                    credential_id=cred_dict.get("credential_id"),
                    error=str(e)
                )
                skipped += 1

        logger.info(
            "凭证验证完成",
            task_id=task_id,
            verified=verified,
            valid=valid,
            invalid=invalid,
            skipped=skipped
        )

        return {
            "task_id": task_id,
            "status": "success",
            "verified": verified,
            "valid": valid,
            "invalid": invalid,
            "skipped": skipped
        }

    async def _validate_credential(self, credential: Credential) -> Dict[str, Any]:
        """
        验证单个凭证

        Args:
            credential: 凭证对象

        Returns:
            验证结果
        """
        # 1. 静态格式验证
        format_valid = self._validate_format(credential)

        if not format_valid:
            return {
                "is_valid": False,
                "confidence": 0.0,
                "reason": "格式验证失败",
                "suggestions": []
            }

        # 2. 检查是否为测试/示例凭证
        if self._is_test_credential(credential):
            return {
                "is_valid": False,
                "confidence": 0.0,
                "reason": "检测为测试/示例凭证",
                "suggestions": []
            }

        # 3. 高置信度凭证（>0.8）跳过 LLM 验证
        if credential.confidence >= 0.8:
            return {
                "is_valid": True,
                "confidence": credential.confidence,
                "reason": "高置信度凭证，格式验证通过",
                "suggestions": []
            }

        # 4. 中低置信度凭证使用 LLM 验证
        try:
            llm_result = await self.llm_client.validate_credential(
                credential.model_dump()
            )
            return llm_result
        except Exception as e:
            logger.warning("LLM 验证失败", error=str(e))
            # LLM 失败时，保守估计
            return {
                "is_valid": None,  # 未知
                "confidence": credential.confidence * 0.5,
                "reason": "LLM 验证失败，降低置信度",
                "suggestions": ["建议人工确认"]
            }

    def _validate_format(self, credential: Credential) -> bool:
        """
        验证凭证格式

        Args:
            credential: 凭证对象

        Returns:
            是否格式有效
        """
        cred_type = credential.cred_type
        raw_value = credential.raw_value

        if not raw_value:
            # 没有 raw_value 时，基于 context 判断
            return self._validate_context(credential)

        # 根据类型验证
        if cred_type == CredentialType.AWS_KEY:
            return bool(self.aws_access_key_pattern.match(raw_value))

        elif cred_type == CredentialType.API_KEY:
            # 尝试匹配已知模式
            for prefix, pattern in self.api_key_patterns.items():
                if raw_value.startswith(prefix):
                    return bool(pattern.match(raw_value))
            # 未知 API Key 格式，保守返回 True
            return True

        elif cred_type == CredentialType.TOKEN:
            # JWT 验证
            if self.jwt_pattern.match(raw_value):
                return True
            # 其他 Token，保守返回 True
            return True

        elif cred_type == CredentialType.PASSWORD:
            # 密码应该有一定长度
            return len(raw_value) >= 8

        else:
            # 其他类型，保守返回 True
            return True

    def _validate_context(self, credential: Credential) -> bool:
        """
        基于 context 验证

        Args:
            credential: 凭证对象

        Returns:
            是否有效
        """
        context = credential.context or ""

        # 检查是否包含测试关键词
        lower_context = context.lower()
        for keyword in self.test_keywords:
            if keyword in lower_context:
                return False

        # 检查是否被注释
        if '#' in context or '//' in context:
            return False

        return True

    def _is_test_credential(self, credential: Credential) -> bool:
        """
        判断是否为测试凭证

        Args:
            credential: 凭证对象

        Returns:
            是否为测试凭证
        """
        # 检查文件路径
        file_path = credential.file_path.lower()
        test_paths = [
            'test', 'tests', 'example', 'demo', 'sample',
            'spec', 'mock', 'fixture'
        ]
        for test_path in test_paths:
            if test_path in file_path:
                return True

        # 检查 context
        context = (credential.context or "").lower()
        for keyword in self.test_keywords:
            if keyword in context:
                return True

        # 检查 raw_value
        if credential.raw_value:
            raw_value = credential.raw_value.lower()
            for keyword in self.test_keywords:
                if keyword in raw_value:
                    return True

        return False
