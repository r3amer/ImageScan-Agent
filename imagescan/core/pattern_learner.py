"""
模式学习器 - 从扫描结果中学习低风险文件模式

职责：
1. 从文件列表中提取低风险模式（前缀和扩展名）
2. 将学习的模式持久化到 learned_filters.json
3. 加载并应用学习的规则

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

import json
import os
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import Counter

from ..utils.logger import get_logger

logger = get_logger(__name__)


class PatternLearner:
    """
    模式学习器 - 从文件中学习低风险过滤规则
    """

    # 默认学习文件路径
    DEFAULT_LEARNED_FILTERS_PATH = "./agent_memory/learned_filters.json"

    def __init__(self, filters_path: Optional[str] = None):
        """
        初始化模式学习器

        Args:
            filters_path: 学习规则保存路径（默认 ./agent_memory/learned_filters.json）
        """
        self.filters_path = filters_path or self.DEFAULT_LEARNED_FILTERS_PATH

        # 学习的数据结构
        self._learned_data = {
            "version": "1.0",
            "last_updated": None,
            "stats": {
                "total_prefixes": 0,
                "total_extensions": 0,
                "total_scans": 0
            },
            "patterns": {
                "path_prefixes": [],  # 路径前缀：["etc/DIR_COLORS", "usr/share/terminfo"]
                "extensions": []       # 扩展名：[".colors", ".terminfo"]
            }
        }

        # 加载已学习的规则
        self._load_filters()

    def _load_filters(self):
        """从文件加载学习的规则"""
        if not os.path.exists(self.filters_path):
            logger.info("学习规则文件不存在，将创建新文件", path=self.filters_path)
            return

        try:
            with open(self.filters_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 版本检查
            if data.get("version") != "1.0":
                logger.warning("学习规则版本不匹配", version=data.get("version"))

            self._learned_data = data
            logger.info(
                "学习规则加载成功",
                prefixes=self._learned_data["stats"]["total_prefixes"],
                extensions=self._learned_data["stats"]["total_extensions"]
            )

        except Exception as e:
            logger.error("加载学习规则失败", error=str(e))

    def _save_filters(self):
        """保存学习的规则到文件"""
        try:
            # 确保目录存在
            dir_path = os.path.dirname(self.filters_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            # 更新统计
            self._learned_data["last_updated"] = datetime.utcnow().isoformat()
            self._learned_data["stats"]["total_prefixes"] = len(
                self._learned_data["patterns"]["path_prefixes"]
            )
            self._learned_data["stats"]["total_extensions"] = len(
                self._learned_data["patterns"]["extensions"]
            )

            # 保存到文件
            with open(self.filters_path, 'w', encoding='utf-8') as f:
                json.dump(self._learned_data, f, ensure_ascii=False, indent=2)

            logger.info(
                "学习规则保存成功",
                prefixes=self._learned_data["stats"]["total_prefixes"],
                extensions=self._learned_data["stats"]["total_extensions"]
            )

        except Exception as e:
            logger.error("保存学习规则失败", error=str(e))

    async def learn_from_files(
        self,
        files: List[str]
    ) -> Dict[str, Any]:
        """
        从文件列表中学习低风险模式（超时时调用）

        流程：
        1. 统计方法快速提取候选模式
        2. LLM 分析候选模式，筛选出真正的低风险模式

        Args:
            files: 文件列表

        Returns:
            {
                "prefixes_learned": int,
                "extensions_learned": int,
                "summary": [...]
            }
        """
        if not files:
            logger.info("没有文件需要分析")
            return {
                "prefixes_learned": 0,
                "extensions_learned": 0,
                "summary": ["✅ 没有文件需要分析"]
            }

        logger.info("开始分析低风险文件模式", count=len(files))

        # 步骤1: 统计方法提取候选模式
        logger.info("步骤1: 统计方法提取候选模式")
        candidate_patterns = self._extract_patterns_statistical(files)

        logger.info(
            "候选模式提取完成",
            prefixes_count=len(candidate_patterns["path_prefixes"]),
            extensions_count=len(candidate_patterns["extensions"])
        )

        # 步骤2: LLM 分析候选模式，筛选低风险模式
        logger.info("步骤2: LLM 分析候选模式")
        final_patterns = await self._extract_patterns_with_llm(
            candidate_patterns["path_prefixes"],
            candidate_patterns["extensions"]
        )

        logger.info(
            "LLM 筛选完成",
            final_prefixes=len(final_patterns["path_prefixes"]),
            final_extensions=len(final_patterns["extensions"])
        )

        # 保存模式
        learned_count = self._save_patterns(final_patterns)

        # 保存到文件
        self._save_filters()

        # 更新扫描次数
        self._learned_data["stats"]["total_scans"] += 1

        return {
            "prefixes_learned": len(final_patterns["path_prefixes"]),
            "extensions_learned": len(final_patterns["extensions"]),
            "summary": [
                f"✅ 模式学习完成",
                f"  分析文件: {len(files)}",
                f"  候选前缀: {len(candidate_patterns['path_prefixes'])}",
                f"  候选扩展名: {len(candidate_patterns['extensions'])}",
                f"  学习前缀: {len(final_patterns['path_prefixes'])}",
                f"  学习扩展名: {len(final_patterns['extensions'])}",
                f"  新增模式: {learned_count}"
            ]
        }

    def _extract_patterns_statistical(
        self,
        files: List[str]
    ) -> Dict[str, List[str]]:
        """
        使用统计方法从文件列表中提取候选模式

        Args:
            files: 文件列表

        Returns:
            {
                "path_prefixes": ["etc/DIR_COLORS", "usr/share/terminfo"],
                "extensions": [".colors", ".terminfo"]
            }
        """
        # 统计路径前缀（取前2级）
        prefix_counter = Counter()
        for f in files:
            parts = f.split('/')
            if len(parts) >= 2:
                # 取前2级作为前缀，如 "etc/DIR_COLORS"
                prefix = '/'.join(parts[:2])
                prefix_counter[prefix] += 1

        # 统计扩展名
        ext_counter = Counter()
        for f in files:
            _, ext = os.path.splitext(f)
            if ext:
                ext_counter[ext.lower()] += 1

        # 过滤低频模式（出现>=3次）
        min_occurrences = 1
        path_prefixes = [p for p, c in prefix_counter.items() if c >= min_occurrences]
        extensions = [e for e, c in ext_counter.items() if c >= min_occurrences]

        logger.debug(
            "统计模式提取完成",
            total_prefixes=len(prefix_counter),
            filtered_prefixes=len(path_prefixes),
            total_extensions=len(ext_counter),
            filtered_extensions=len(extensions)
        )

        return {
            "path_prefixes": path_prefixes,
            "extensions": extensions
        }

    async def _extract_patterns_with_llm(
        self,
        candidate_prefixes: List[str],
        candidate_extensions: List[str]
    ) -> Dict[str, List[str]]:
        """
        使用LLM从候选模式中筛选真正的低风险模式

        Args:
            candidate_prefixes: 候选路径前缀列表
            candidate_extensions: 候选扩展名列表

        Returns:
            {
                "path_prefixes": ["etc/DIR_COLORS", "usr/share/terminfo"],
                "extensions": [".colors", ".terminfo"]
            }
        """
        from ..core.llm_client import get_llm_client

        llm_client = get_llm_client()

        prompt = f"""从以下候选模式中筛选出真正的低风险模式（最不可能包含敏感凭证）。

候选路径前缀（{len(candidate_prefixes)}个）：
{json.dumps(candidate_prefixes, ensure_ascii=False)}

候选扩展名（{len(candidate_extensions)}个）：
{json.dumps(candidate_extensions, ensure_ascii=False)}

请返回低风险模式（只保留明确不包含凭证的）：

返回 JSON 格式：
{{
    "path_prefixes": ["etc/DIR_COLORS", "usr/share/terminfo"],
    "extensions": [".colors", ".terminfo"]
}}

筛选规则：
- **保留**: 系统文件、颜色定义、终端信息、帮助文件等明显不包含凭证的
- **排除**: 可能包含凭证的文件（.env, .json, .yaml, .py, .sh, .conf, .config 等）
- **排除**: 包含敏感关键词的（secret, credential, password, key, token 等）
- 宁可漏报，不要误报"""

        try:
            result = await llm_client.think(prompt, temperature=0.0)
            logger.info(
                "LLM 模式筛选成功",
                input_prefixes=len(candidate_prefixes),
                output_prefixes=len(result.get("path_prefixes", [])),
                input_extensions=len(candidate_extensions),
                output_extensions=len(result.get("extensions", []))
            )
            return result

        except Exception as e:
            logger.error("LLM 模式筛选失败", error=str(e))
            # 失败时返回保守结果（排除所有）
            return {"path_prefixes": [], "extensions": []}

    def _save_patterns(self, patterns: Dict[str, List[str]]) -> int:
        """
        保存学习的模式

        Args:
            patterns: 提取的模式

        Returns:
            新增的模式数量
        """
        learned_count = 0
        now = datetime.utcnow().isoformat()

        # 添加路径前缀
        for prefix in patterns.get("path_prefixes", []):
            if not self._pattern_exists("path_prefixes", prefix):
                self._learned_data["patterns"]["path_prefixes"].append({
                    "value": prefix,
                    "confidence": 0.8,
                    "learned_at": now
                })
                learned_count += 1

        # 添加扩展名
        for ext in patterns.get("extensions", []):
            if not self._pattern_exists("extensions", ext):
                self._learned_data["patterns"]["extensions"].append({
                    "value": ext,
                    "confidence": 0.8,
                    "learned_at": now
                })
                learned_count += 1

        logger.info("保存学习模式完成", new_patterns=learned_count)
        return learned_count

    def _pattern_exists(self, pattern_type: str, value: str) -> bool:
        """检查模式是否已存在"""
        return any(
            item["value"] == value
            for item in self._learned_data["patterns"][pattern_type]
        )

    def should_filter_file(self, file_path: str) -> bool:
        """
        判断单个文件是否应该被过滤

        Args:
            file_path: 文件路径

        Returns:
            True: 应该过滤（低风险）
            False: 不过滤
        """
        # 1. 检查路径前缀
        for item in self._learned_data["patterns"]["path_prefixes"]:
            if file_path.startswith(item["value"]):
                return True

        # 2. 检查扩展名（大小写不敏感）
        _, ext = os.path.splitext(file_path)
        if ext:
            ext_lower = ext.lower()
            for item in self._learned_data["patterns"]["extensions"]:
                if ext_lower == item["value"].lower():
                    return True

        return False

    def get_stats(self) -> Dict[str, Any]:
        """获取学习统计信息"""
        return {
            "version": self._learned_data["version"],
            "last_updated": self._learned_data["last_updated"],
            "total_prefixes": self._learned_data["stats"]["total_prefixes"],
            "total_extensions": self._learned_data["stats"]["total_extensions"],
            "total_scans": self._learned_data["stats"]["total_scans"]
        }

    def reset(self):
        """重置所有学习的规则（谨慎使用）"""
        self._learned_data = {
            "version": "1.0",
            "last_updated": None,
            "stats": {
                "total_prefixes": 0,
                "total_extensions": 0,
                "total_scans": 0
            },
            "patterns": {
                "path_prefixes": [],
                "extensions": []
            }
        }
        self._save_filters()
        logger.warning("学习规则已重置")


# 全局实例
_pattern_learner_instance: Optional[PatternLearner] = None


def get_pattern_learner() -> PatternLearner:
    """获取全局模式学习器实例"""
    global _pattern_learner_instance
    if _pattern_learner_instance is None:
        _pattern_learner_instance = PatternLearner()
    return _pattern_learner_instance


# ==================== 测试代码 ====================
if __name__ == "__main__":
    async def run_test():
        """完整测试 PatternLearner 功能"""
        print("=" * 60)
        print("PatternLearner 端到端测试")
        print("=" * 60)

        # 测试数据
        test_files = []
        print(f"\n📋 测试文件数量: {len(test_files)}")
        print(f"文件列表: {test_files[:5]}...")

        # 创建学习器（使用测试路径）
        test_filters_path = "./test_learned_filters.json"
        learner = PatternLearner(filters_path=test_filters_path)

        # 先重置（确保干净状态）
        print("\n🔄 重置学习规则...")
        learner.reset()

        # 步骤1: 学习模式
        print("\n" + "=" * 60)
        print("步骤 1: 学习低风险模式")
        print("=" * 60)

        result = await learner.learn_from_files(test_files)

        print("\n学习结果:")
        for line in result["summary"]:
            print(f"  {line}")

        # 步骤2: 查看学习的模式
        print("\n" + "=" * 60)
        print("步骤 2: 查看学习的模式")
        print("=" * 60)

        print(f"\n学习的路径前缀 ({len(learner._learned_data['patterns']['path_prefixes'])} 个):")
        for item in learner._learned_data["patterns"]["path_prefixes"]:
            print(f"  - {item['value']} (置信度: {item['confidence']})")

        print(f"\n学习的扩展名 ({len(learner._learned_data['patterns']['extensions'])} 个):")
        for item in learner._learned_data["patterns"]["extensions"]:
            print(f"  - {item['value']} (置信度: {item['confidence']})")

        # 步骤3: 测试过滤功能
        print("\n" + "=" * 60)
        print("步骤 3: 测试过滤功能")
        print("=" * 60)

        test_cases = [
            ("etc/DIR_COLORS", True, "完整匹配前缀"),
            ("etc/DIR_COLORS.256color", True, "前缀匹配"),
            ("usr/share/terminfo/a", True, "前缀匹配"),
            ("etc/passwd", False, "不匹配任何模式"),
            ("app/config.json", False, "不匹配任何模式"),
            ("app/test.colors", True, "扩展名匹配"),
        ]

        print("\n过滤测试:")
        for file_path, expected, description in test_cases:
            result = learner.should_filter_file(file_path)
            status = "✅" if result == expected else "❌"
            print(f"  {status} {file_path:30} → {result:5} ({description})")

        # 步骤4: 查看统计信息
        print("\n" + "=" * 60)
        print("步骤 4: 统计信息")
        print("=" * 60)

        stats = learner.get_stats()
        print(f"\n版本: {stats['version']}")
        print(f"最后更新: {stats['last_updated']}")
        print(f"学习前缀数: {stats['total_prefixes']}")
        print(f"学习扩展名数: {stats['total_extensions']}")
        print(f"总扫描次数: {stats['total_scans']}")

        # 步骤5: 验证文件保存
        print("\n" + "=" * 60)
        print("步骤 5: 验证文件保存")
        print("=" * 60)

        if os.path.exists(test_filters_path):
            with open(test_filters_path, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            print(f"\n✅ 文件已保存: {test_filters_path}")
            print(f"   文件大小: {os.path.getsize(test_filters_path)} 字节")
            print(f"   保存的模式数: {len(saved_data['patterns']['path_prefixes']) + len(saved_data['patterns']['extensions'])}")
        else:
            print(f"\n❌ 文件未保存: {test_filters_path}")

        print("\n" + "=" * 60)
        print("✅ 测试完成！")
        print("=" * 60)

        # 清理测试文件
        print(f"\n🗑️  清理测试文件: {test_filters_path}")
        if os.path.exists(test_filters_path):
            os.remove(test_filters_path)
            print("   已删除")

    # 运行测试
    asyncio.run(run_test())
