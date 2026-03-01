"""
研判 Agent

职责：
1. 汇总所有凭证
2. 置信度评估
3. 疑似凭证二次审核
4. 生成统计信息

参考：docs/APP_FLOW.md
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import Counter, defaultdict

from ..core.agent import BaseAgent
from ..core.events import EventType
from ..core.llm_client import get_llm_client
from ..utils.logger import get_logger
from ..utils.database import Database, get_database
from ..models.credential import Credential, CredentialType, ValidationStatus, get_risk_level, RiskLevel

logger = get_logger(__name__)


class ReflectionAgent(BaseAgent):
    """
    研判 Agent

    负责：
    1. 汇总扫描结果
    2. 置信度二次评估
    3. 生成统计报告
    4. 风险等级评估
    """

    def __init__(self, event_bus=None, database: Optional[Database] = None):
        super().__init__("ReflectionAgent", event_bus)

        self.database = database or get_database()
        self.llm_client = get_llm_client()

    async def process(
        self,
        task_id: str,
        scan_result: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """
        研判扫描结果

        Args:
            task_id: 任务 ID
            scan_result: 扫描结果
            **kwargs: 其他参数

        Returns:
            研判结果
        """
        logger.info(
            "开始研判扫描结果",
            task_id=task_id
        )

        # 1. 获取所有凭证
        credentials = await self.database.get_credentials_by_task(task_id)

        if not credentials:
            logger.info("无凭证需要研判", task_id=task_id)
            return {
                "task_id": task_id,
                "total_credentials": 0,
                "statistics": self._empty_statistics(),
                "risk_assessment": {
                    "overall_risk": "LOW",
                    "high_risk_count": 0,
                    "medium_risk_count": 0,
                    "low_risk_count": 0
                }
            }

        # 2. 置信度二次评估（针对中低置信度凭证）
        credentials = await self._reflect_on_credentials(credentials)

        # 3. 生成统计信息
        statistics = await self._generate_statistics(credentials, scan_result)

        # 4. 风险评估
        risk_assessment = self._assess_risk(credentials)

        logger.info(
            "研判完成",
            task_id=task_id,
            total_credentials=len(credentials),
            high_risk=risk_assessment["high_risk_count"],
            medium_risk=risk_assessment["medium_risk_count"],
            low_risk=risk_assessment["low_risk_count"]
        )

        return {
            "task_id": task_id,
            "total_credentials": len(credentials),
            "credentials": [self._serialize_cred(cred) for cred in credentials],
            "statistics": statistics,
            "risk_assessment": risk_assessment
        }

    async def _reflect_on_credentials(
        self,
        credentials: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        对凭证进行二次研判

        重点处理中低置信度凭证

        Args:
            credentials: 凭证列表

        Returns:
            研判后的凭证列表
        """
        reflected = []

        for cred_dict in credentials:
            # 确保metadata是字典而不是字符串
            if "metadata" in cred_dict and isinstance(cred_dict["metadata"], str):
                import json
                try:
                    cred_dict["metadata"] = json.loads(cred_dict["metadata"])
                except:
                    cred_dict["metadata"] = {}

            credential = Credential(**cred_dict)

            # 高置信度凭证直接保留
            if credential.confidence >= 0.8:
                reflected.append(cred_dict)
                continue

            # 中低置信度凭证需要二次研判
            # MVP 阶段：简单规则判断
            # 优化阶段：可加入 Tree of Thought

            adjusted_confidence = await self._adjust_confidence(credential)

            if adjusted_confidence != credential.confidence:
                logger.info(
                    "置信度调整",
                    credential_id=cred_dict.get("credential_id"),
                    old_confidence=credential.confidence,
                    new_confidence=adjusted_confidence
                )

                # 更新置信度
                cred_dict["confidence"] = adjusted_confidence

            reflected.append(cred_dict)

        return reflected

    async def _adjust_confidence(self, credential: Credential) -> float:
        """
        调整置信度

        Args:
            credential: 凭证对象

        Returns:
            调整后的置信度
        """
        original_confidence = credential.confidence
        adjusted_confidence = original_confidence

        # 1. 检查文件路径
        file_path = credential.file_path.lower()

        # 提升：敏感路径
        sensitive_paths = [
            '.env', 'config', 'secret', 'credential',
            'password', 'key', 'token', 'auth'
        ]
        for path in sensitive_paths:
            if path in file_path:
                adjusted_confidence = min(1.0, adjusted_confidence + 0.1)
                break

        # 降低：测试/示例路径
        test_paths = [
            'test', 'tests', 'example', 'demo', 'sample',
            'spec', 'mock', 'fixture', 'doc'
        ]
        for path in test_paths:
            if path in file_path:
                adjusted_confidence = max(0.0, adjusted_confidence - 0.3)
                break

        # 2. 检查上下文
        context = (credential.context or "").lower()

        # 提升：包含关键词
        sensitive_keywords = [
            'password', 'passwd', 'api_key', 'apikey',
            'secret', 'token', 'credential'
        ]
        for keyword in sensitive_keywords:
            if keyword in context:
                adjusted_confidence = min(1.0, adjusted_confidence + 0.05)
                break

        # 降低：测试关键词
        test_keywords = [
            'test', 'demo', 'example', 'sample',
            'placeholder', 'xxx', '***'
        ]
        for keyword in test_keywords:
            if keyword in context:
                adjusted_confidence = max(0.0, adjusted_confidence - 0.2)
                break

        # 3. 检查凭证类型
        # 某些类型天然可信度高
        high_confidence_types = [
            CredentialType.AWS_KEY,
            CredentialType.API_KEY,
            CredentialType.PRIVATE_KEY
        ]
        if credential.cred_type in high_confidence_types and adjusted_confidence < 0.5:
            adjusted_confidence = min(0.7, adjusted_confidence + 0.2)

        # 4. 检查 raw_value
        if credential.raw_value:
            raw_value = credential.raw_value

            # 脱敏值降低置信度
            if '*' in raw_value or 'xxx' in raw_value.lower():
                adjusted_confidence = max(0.0, adjusted_confidence - 0.5)

            # 过短降低置信度
            elif len(raw_value) < 10:
                adjusted_confidence = max(0.0, adjusted_confidence - 0.3)

        return adjusted_confidence

    async def _generate_statistics(
        self,
        credentials: List[Dict[str, Any]],
        scan_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成统计信息

        Args:
            credentials: 凭证列表
            scan_result: 扫描结果

        Returns:
            统计信息
        """
        # 置信度分布
        confidence_dist = {"high": 0, "medium": 0, "low": 0}
        for cred in credentials:
            conf = cred.get("confidence", 0.0)
            if conf >= 0.8:
                confidence_dist["high"] += 1
            elif conf >= 0.5:
                confidence_dist["medium"] += 1
            else:
                confidence_dist["low"] += 1

        # 凭证类型分布
        type_dist = Counter(cred.get("cred_type", "UNKNOWN") for cred in credentials)

        # 层分布
        layer_dist = Counter(cred.get("layer_id", "")[:12] for cred in credentials)

        # 风险等级
        high_risk = sum(1 for cred in credentials if cred.get("confidence", 0.0) >= 0.8)
        medium_risk = sum(1 for cred in credentials if 0.5 <= cred.get("confidence", 0.0) < 0.8)
        low_risk = len(credentials) - high_risk - medium_risk

        return {
            "total_credentials": len(credentials),
            "confidence_distribution": confidence_dist,
            "credential_type_distribution": dict(type_dist),
            "layer_distribution": dict(layer_dist),
            "high_risk_count": high_risk,
            "medium_risk_count": medium_risk,
            "low_risk_count": low_risk,
            "scan_summary": {
                "total_layers": scan_result.get("total_layers", 0),
                "total_size": scan_result.get("total_size", 0)
            }
        }

    def _assess_risk(self, credentials: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        评估整体风险

        Args:
            credentials: 凭证列表

        Returns:
            风险评估
        """
        high_risk = sum(1 for cred in credentials if cred.get("confidence", 0.0) >= 0.8)
        medium_risk = sum(1 for cred in credentials if 0.5 <= cred.get("confidence", 0.0) < 0.8)
        low_risk = len(credentials) - high_risk - medium_risk

        # 整体风险等级
        if high_risk >= 3:
            overall_risk = "CRITICAL"
        elif high_risk >= 1:
            overall_risk = "HIGH"
        elif medium_risk >= 5:
            overall_risk = "MEDIUM"
        elif medium_risk >= 1:
            overall_risk = "LOW"
        else:
            overall_risk = "MINIMAL"

        return {
            "overall_risk": overall_risk,
            "high_risk_count": high_risk,
            "medium_risk_count": medium_risk,
            "low_risk_count": low_risk,
            "total_credentials": len(credentials)
        }

    def _serialize_cred(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        """序列化凭证信息（脱敏）"""
        return {
            "cred_type": cred.get("cred_type"),
            "confidence": cred.get("confidence"),
            "file_path": cred.get("file_path"),
            "line_number": cred.get("line_number"),
            "layer_id": cred.get("layer_id", "")[:12],
            "validation_status": cred.get("validation_status"),
            "context": (cred.get("context") or "")[:100]  # 截断
        }

    def _empty_statistics(self) -> Dict[str, Any]:
        """空统计信息"""
        return {
            "total_credentials": 0,
            "confidence_distribution": {"high": 0, "medium": 0, "low": 0},
            "credential_type_distribution": {},
            "layer_distribution": {},
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "low_risk_count": 0,
            "scan_summary": {
                "total_layers": 0,
                "total_size": 0
            }
        }
