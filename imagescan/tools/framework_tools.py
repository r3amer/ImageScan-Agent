"""
框架检测工具 - 根据目录结构检测镜像框架并优化扫描策略
"""

import os
import json
from typing import Dict, List, Any
from ..utils.logger import get_logger
from ..core.framework_detector import FrameworkDetector, FrameworkInfo
from ..utils.config import Config

logger = get_logger(__name__)


async def _list_all_files_from_tar(tar_path: str) -> List[str]:
    """从 tar 文件中列出所有文件路径"""
    import tarfile
    files = []
    try:
        with tarfile.open(tar_path, 'r') as tar:
            for member in tar.getmembers():
                if member.isfile():
                    files.append(member.name)
    except Exception as e:
        logger.error(f"读取 tar 文件失败: {e}")
    return files


async def detect_framework(
    tar_path: str,
    config: Config = None
) -> Dict[str, Any]:
    """
    检测镜像使用的框架

    Args:
        tar_path: 镜像 tar 文件路径
        config: 配置对象（可选）

    Returns:
        {
            "success": True,
            "data": {
                "framework_name": "react",
                "risk_level": "medium",
                "confidence": 0.9,
                "credential_types": ["build_env", "api_key"],
                "priority_paths": [".env", "config/"],
                "skip_paths": ["node_modules/", "src/components/"],
                "scan_strategy": {
                    "total_files": 5000,
                    "files_to_scan": 300,
                    "reduction_ratio": "94%"
                }
            },
            "summary": "检测到 React 框架（置信度 90%），风险等级：中。将扫描 300 个高优先级文件，跳过 4700 个低风险文件。"
        }
    """
    try:
        logger.info(f"开始检测框架，tar_path={tar_path}")

        # 1. 列出所有文件
        all_files = await _list_all_files_from_tar(tar_path)
        total_files = len(all_files)

        if total_files == 0:
            return {
                "success": False,
                "error": "tar 文件为空或读取失败",
                "summary": "❌ 无法从 tar 文件中读取文件列表"
            }

        # 2. 检测框架
        detector = FrameworkDetector()
        framework_info = await detector.detect(all_files)

        # 3. 计算扫描策略
        files_to_scan = []
        skipped_files = []

        for file_path in all_files:
            priority = detector.get_scan_priority(file_path, framework_info)

            # 优先级 0 和 1 的文件必须扫描
            if priority <= 1:
                files_to_scan.append(file_path)
            # 优先级 3 的文件跳过
            elif priority == 3:
                skipped_files.append(file_path)
            # 优先级 2 的文件，根据数量限制
            elif len(files_to_scan) < 1000:  # 最多扫描 1000 个中等优先级文件
                files_to_scan.append(file_path)
            else:
                skipped_files.append(file_path)

        reduction_ratio = (1 - len(files_to_scan) / total_files) * 100 if total_files > 0 else 0

        # 4. 构建返回结果
        result_data = {
            "framework_name": framework_info.name,
            "risk_level": framework_info.risk_level,
            "confidence": framework_info.confidence,
            "credential_types": framework_info.credential_types,
            "priority_paths": framework_info.priority_paths,
            "skip_paths": framework_info.skip_paths,
            "evidence": framework_info.evidence,
            "scan_strategy": {
                "total_files": total_files,
                "files_to_scan": len(files_to_scan),
                "files_to_skip": len(skipped_files),
                "reduction_ratio": f"{reduction_ratio:.1f}%",
                "sample_files_to_scan": files_to_scan[:10]  # 示例
            }
        }

        # 根据风险等级生成建议
        if framework_info.risk_level == "low":
            recommendation = "⚠️ 检测到低风险框架（如 Nginx/Apache），凭证可能较少，但仍需检查配置文件。"
        elif framework_info.risk_level == "medium":
            recommendation = f"✅ 检测到 {framework_info.name} 框架，将重点扫描构建配置和 API Key。"
        else:  # high
            recommendation = f"🔴 检测到高风险框架（{framework_info.name}），可能包含数据库密码、API Secret 等敏感信息。"

        summary = (
            f"{recommendation}\n"
            f"置信度: {framework_info.confidence:.0%} | "
            f"扫描 {len(files_to_scan)} 个文件，跳过 {len(skipped_files)} 个文件（减少 {reduction_ratio:.0f}%）"
        )

        logger.info(
            "框架检测完成",
            framework=framework_info.name,
            risk_level=framework_info.risk_level,
            scan_files=len(files_to_scan),
            skip_files=len(skipped_files)
        )

        return {
            "success": True,
            "data": result_data,
            "summary": summary
        }

    except Exception as e:
        logger.error(f"框架检测失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "summary": f"❌ 框架检测失败：{e}"
        }


async def filter_files_by_framework(
    tar_path: str,
    framework_info: Dict[str, Any],
    config: Config = None
) -> Dict[str, Any]:
    """
    根据框架信息过滤文件列表

    Args:
        tar_path: 镜像 tar 文件路径
        framework_info: 框架信息（来自 detect_framework 的返回值）
        config: 配置对象（可选）

    Returns:
        {
            "success": True,
            "data": {
                "filtered_files": [".env", "config/api.js", ...],
                "file_count": 300
            },
            "summary": "根据框架信息筛选出 300 个高优先级文件"
        }
    """
    try:
        logger.info("根据框架信息过滤文件")

        # 1. 列出所有文件
        all_files = await _list_all_files_from_tar(tar_path)

        # 2. 重建 FrameworkInfo 对象
        info = FrameworkInfo(
            name=framework_info.get("framework_name", "unknown"),
            risk_level=framework_info.get("risk_level", "medium"),
            confidence=framework_info.get("confidence", 0.0),
            credential_types=framework_info.get("credential_types", []),
            priority_paths=framework_info.get("priority_paths", []),
            skip_paths=framework_info.get("skip_paths", []),
            evidence=framework_info.get("evidence", [])
        )

        # 3. 过滤文件
        detector = FrameworkDetector()
        filtered_files = []

        for file_path in all_files:
            priority = detector.get_scan_priority(file_path, info)

            # 只保留优先级 0-2 的文件
            if priority <= 2:
                filtered_files.append(file_path)

        # 4. 限制文件数量
        max_files = 2000  # 最多保留 2000 个文件
        if len(filtered_files) > max_files:
            filtered_files = filtered_files[:max_files]

        logger.info(
            "文件过滤完成",
            total_files=len(all_files),
            filtered_files=len(filtered_files)
        )

        return {
            "success": True,
            "data": {
                "filtered_files": filtered_files,
                "file_count": len(filtered_files)
            },
            "summary": f"根据 {info.name} 框架筛选出 {len(filtered_files)} 个高优先级文件（跳过 {len(all_files) - len(filtered_files)} 个低风险文件）"
        }

    except Exception as e:
        logger.error(f"文件过滤失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "summary": f"❌ 文件过滤失败：{e}"
        }
