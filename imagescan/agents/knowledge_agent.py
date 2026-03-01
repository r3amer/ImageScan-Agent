"""
知识 Agent

职责：
1. 查询 RAG 知识库（历史案例、误报模式）
2. 匹配已知凭证模式
3. 提供上下文信息
4. 辅助研判

参考：docs/APP_FLOW.md

注意：MVP 阶段 RAG 功能禁用，此 Agent 主要提供接口预留
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..core.agent import BaseAgent
from ..core.events import EventType
from ..utils.logger import get_logger
from ..utils.config import get_config

logger = get_logger(__name__)


class KnowledgeAgent(BaseAgent):
    """
    知识 Agent

    MVP 阶段：提供基本接口，RAG 功能禁用
    优化阶段：集成 ChromaDB 向量数据库
    """

    def __init__(self, event_bus=None):
        super().__init__("KnowledgeAgent", event_bus)

        self.config = get_config()

        # 检查 RAG 是否启用
        self.rag_enabled = self.config.rag.enabled if hasattr(self.config, 'rag') else False

        if not self.rag_enabled:
            logger.info("RAG 功能禁用（MVP 阶段）", name=self.name)

        # TODO: 优化阶段初始化 ChromaDB
        # self.chromadb_client = ...

    async def process(
        self,
        task_id: str,
        query: str,
        query_type: str = "general",
        **kwargs
    ) -> Dict[str, Any]:
        """
        查询知识库

        Args:
            task_id: 任务 ID
            query: 查询内容
            query_type: 查询类型（general, pattern, history）
            **kwargs: 其他参数

        Returns:
            查询结果
        """
        logger.debug(
            "知识库查询",
            task_id=task_id,
            query_type=query_type,
            rag_enabled=self.rag_enabled
        )

        if not self.rag_enabled:
            # MVP 阶段返回空结果
            return {
                "task_id": task_id,
                "query": query,
                "query_type": query_type,
                "results": [],
                "rag_enabled": False,
                "message": "RAG 功能在 MVP 阶段禁用"
            }

        # TODO: 优化阶段实现 ChromaDB 查询
        # results = await self._query_chromadb(query, query_type)

        return {
            "task_id": task_id,
            "query": query,
            "query_type": query_type,
            "results": [],
            "rag_enabled": self.rag_enabled
        }

    async def get_similar_cases(
        self,
        credential: Dict[str, Any],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        获取相似历史案例

        Args:
            credential: 凭证信息
            top_k: 返回数量

        Returns:
            相似案例列表
        """
        if not self.rag_enabled:
            return []

        # TODO: 优化阶段实现
        # 1. 构建查询向量
        # 2. 查询 ChromaDB
        # 3. 返回相似案例

        return []

    async def get_known_patterns(
        self,
        cred_type: str
    ) -> List[Dict[str, Any]]:
        """
        获取已知凭证模式

        Args:
            cred_type: 凭证类型

        Returns:
            模式列表
        """
        if not self.rag_enabled:
            return []

        # TODO: 优化阶段实现
        # 查询凭证模式库

        return []

    async def check_false_positive(
        self,
        credential: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        检查是否为已知误报

        Args:
            credential: 凭证信息

        Returns:
            误报检查结果
        """
        if not self.rag_enabled:
            return {
                "is_false_positive": False,
                "confidence": 0.0,
                "reason": "RAG 功能未启用"
            }

        # TODO: 优化阶段实现
        # 1. 查询误报模式库
        # 2. 匹配相似误报
        # 3. 返回判断结果

        return {
            "is_false_positive": False,
            "confidence": 0.0,
            "reason": "暂无数据"
        }

    async def add_to_knowledge_base(
        self,
        item_type: str,
        item_data: Dict[str, Any]
    ):
        """
        添加条目到知识库

        Args:
            item_type: 条目类型（case, pattern, false_positive）
            item_data: 条目数据
        """
        if not self.rag_enabled:
            logger.debug("RAG 功能未启用，跳过添加", item_type=item_type)
            return

        # TODO: 优化阶段实现
        # 添加到 ChromaDB

        logger.info("添加到知识库", item_type=item_type)

    # ========== 优化阶段实现 ==========

    async def _init_chromadb(self):
        """初始化 ChromaDB（优化阶段）"""
        # import chromadb
        # self.chromadb_client = chromadb.PersistentClient(
        #     path=self.config.storage.chromadb_path
        # )
        pass

    async def _query_chromadb(
        self,
        query: str,
        collection_name: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        查询 ChromaDB（优化阶段）

        Args:
            query: 查询文本
            collection_name: 集合名称
            top_k: 返回数量

        Returns:
            查询结果
        """
        # collection = self.chromadb_client.get_collection(collection_name)
        # results = collection.query(
        #     query_texts=[query],
        #     n_results=top_k
        # )
        # return results
        return []

    async def _add_to_chromadb(
        self,
        collection_name: str,
        documents: List[str],
        metadatas: List[Dict[str, Any]]
    ):
        """
        添加到 ChromaDB（优化阶段）

        Args:
            collection_name: 集合名称
            documents: 文档列表
            metadatas: 元数据列表
        """
        # collection = self.chromadb_client.get_or_create_collection(collection_name)
        # collection.add(
        #     documents=documents,
        #     metadatas=metadatas
        # )
        pass
