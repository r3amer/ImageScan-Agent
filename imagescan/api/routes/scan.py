"""
扫描路由 - 扫描任务管理

职责：
1. 获取扫描任务详情
2. 获取扫描历史
3. 取消扫描任务

参考：progress_frontend.txt 第一阶段
"""

import logging
from fastapi import APIRouter, HTTPException, Path
from typing import List
from ..models.scan import ScanResult
from ...utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# TODO: 实现任务存储（当前只是示例）
_tasks_storage = {}


@router.get("/{task_id}", response_model=ScanResult)
async def get_scan_result(task_id: str = Path(..., description="任务 ID")):
    """
    获取扫描任务详情

    Args:
        task_id: 任务 ID

    Returns:
        ScanResult: 扫描结果
    """
    if task_id not in _tasks_storage:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    return _tasks_storage[task_id]


@router.get("/history", response_model=List[ScanResult])
async def get_scan_history(limit: int = 10):
    """
    获取扫描历史

    Args:
        limit: 返回数量限制

    Returns:
        List[ScanResult]: 扫描历史列表
    """
    # TODO: 实现历史记录查询
    return []


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
