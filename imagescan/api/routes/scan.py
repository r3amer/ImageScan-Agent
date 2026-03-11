"""
扫描路由 - 扫描任务管理

职责：
1. 获取扫描任务详情
2. 获取扫描历史
3. 取消扫描任务

参考：progress_frontend.txt 第一阶段
"""

import logging
from pathlib import Path as PathLib
from fastapi import APIRouter, HTTPException, Path
from typing import List, Optional
from ..models.scan import ScanResult, Credential, ScanStatistics
from ...utils.logger import get_logger
from ...utils.config import Config

logger = get_logger(__name__)

router = APIRouter()
config = Config()


def _load_result_from_storage(task_id: str) -> Optional[dict]:
    """
    从存储加载扫描结果

    Args:
        task_id: 任务 ID

    Returns:
        扫描结果字典，如果不存在返回 None
    """
    # 尝试从 output 目录加载
    output_path = PathLib(config.storage.output_path)

    # 搜索所有子目录
    for results_dir in output_path.glob("*/result.json"):
        try:
            import json
            with open(results_dir, 'r') as f:
                data = json.load(f)
                # 检查 task_id 是否匹配（在 metadata 中）
                metadata = data.get("metadata", {})
                if metadata.get("task_id") == task_id:
                    return data
        except Exception as e:
            logger.warning("读取结果文件失败", file=str(results_dir), error=str(e))
            continue

    return None


def _convert_to_scan_result(data: dict) -> ScanResult:
    """
    将存储的数据转换为 ScanResult 模型

    处理 SimpleStorageManager 保存的数据结构：
    {
        "metadata": {...},
        "summary": {...},
        "credentials": [...]
    }

    Args:
        data: 原始数据字典

    Returns:
        ScanResult
    """
    # 获取 metadata
    metadata = data.get("metadata", {})
    summary = data.get("summary", {})

    # 转换凭证列表
    credentials = []
    for cred_data in data.get("credentials", []):
        credentials.append(Credential(
            type=cred_data.get("type", cred_data.get("cred_type", "unknown")),
            confidence=cred_data.get("confidence", 0.0),
            file_path=cred_data.get("file_path", ""),
            layer_id=cred_data.get("layer_id"),
            line_number=cred_data.get("line_number"),
            validation_status=cred_data.get("validation_status"),
            context=cred_data.get("context")
        ))

    # 转换统计信息
    statistics = None
    stats_data = summary.get("statistics", {})
    if stats_data:
        statistics = ScanStatistics(
            total_layers=stats_data.get("total_layers", 0),
            processed_layers=stats_data.get("processed_layers", 0),
            total_files=stats_data.get("total_files", 0),
            scanned_files=stats_data.get("scanned_files", 0)
        )

    # 确定状态 - 根据 completed_at 判断
    status = "completed"
    if metadata.get("completed_at") is None:
        status = "running"

    # 计算持续时间（秒）
    duration = None
    started_at = metadata.get("started_at")
    completed_at = metadata.get("completed_at")
    if started_at and completed_at:
        try:
            from datetime import datetime
            start = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            end = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
            duration = (end - start).total_seconds()
        except Exception:
            pass

    return ScanResult(
        task_id=metadata.get("task_id", ""),
        image_name=metadata.get("image_name", "unknown"),
        status=status,
        credentials=credentials,
        statistics=statistics,
        token_usage=summary.get("token_usage"),
        duration=duration,
        started_at=started_at,
        completed_at=completed_at
    )


@router.get("/history", response_model=List[ScanResult])
async def get_scan_history(limit: int = 10):
    """
    获取扫描历史

    Args:
        limit: 返回数量限制

    Returns:
        List[ScanResult]: 扫描历史列表
    """
    results = []
    output_path = PathLib(config.storage.output_path)

    # 收集所有结果文件
    result_files = []
    for results_file in output_path.glob("*/result.json"):
        result_files.append(results_file)

    # 按修改时间排序（最新的在前）
    result_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    # 加载前 N 个
    for results_file in result_files[:limit]:
        try:
            import json
            with open(results_file, 'r') as f:
                data = json.load(f)
                results.append(_convert_to_scan_result(data))
        except Exception as e:
            logger.warning("读取历史记录失败", file=str(results_file), error=str(e))
            continue

    return results


@router.get("/{task_id}", response_model=ScanResult)
async def get_scan_result(task_id: str = Path(..., description="任务 ID")):
    """
    获取扫描任务详情

    Args:
        task_id: 任务 ID

    Returns:
        ScanResult: 扫描结果
    """
    result_data = _load_result_from_storage(task_id)

    if not result_data:
        raise HTTPException(
            status_code=404,
            detail=f"任务 {task_id} 不存在或结果尚未生成"
        )

    return _convert_to_scan_result(result_data)


@router.delete("/{task_id}")
async def cancel_scan(task_id: str = Path(..., description="任务 ID")):
    """
    取消扫描任务

    Args:
        task_id: 任务 ID

    Returns:
        dict: 取消结果
    """
    # TODO: 实现任务取消
    return {"status": "not_implemented", "message": "任务取消功能待实现"}
