"""
ImageScan 扫描模块

提供扫描功能的可导入接口
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

from .agents.master_agent import MasterAgent
from .agents.executor_agent import ExecutorAgent
from .agents.validation_agent import ValidationAgent
from .agents.knowledge_agent import KnowledgeAgent
from .agents.reflection_agent import ReflectionAgent
from .utils.database import get_database
from .utils.logger import get_logger, setup_logging, set_log_level
from collections import Counter

logger = get_logger(__name__)


def print_header(text):
    """打印标题"""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def print_success(text):
    """打印成功消息"""
    print(f"✅ {text}")


def print_info(text):
    """打印信息"""
    print(f"ℹ️  {text}")


def print_warning(text):
    """打印警告"""
    print(f"⚠️  {text}")


def print_error(text):
    """打印错误"""
    print(f"❌ {text}")


async def scan_image(
    image_name: str,
    output_file: str = None,
    verbose: bool = False,
    debug: bool = False
):
    """扫描 Docker 镜像"""

    print_header("ImageScan Agent - Docker 镜像敏感凭证扫描")

    # 初始化日志系统（使用文本格式，便于用户查看）
    setup_logging(level="DEBUG", log_format="text")  # 文本格式更美观

    # 设置日志级别
    if debug:
        set_log_level("DEBUG")
        print_info("已启用调试模式")
    else:
        set_log_level("INFO")

    try:
        # 1. 初始化 Agent
        print_info("初始化 Agent...")

        database = get_database()
        await database.init()

        event_bus = None  # 使用全局实例

        master = MasterAgent(event_bus=event_bus, database=database)
        executor = ExecutorAgent(event_bus=event_bus, database=database)
        validator = ValidationAgent(event_bus=event_bus, database=database)
        knowledge = KnowledgeAgent(event_bus=event_bus)
        reflection = ReflectionAgent(event_bus=event_bus, database=database)

        # 设置从 Agent
        master.set_agents(executor, validator, knowledge, reflection)

        # 初始化所有 Agent
        await master.initialize()
        await executor.initialize()
        await validator.initialize()
        await knowledge.initialize()
        await reflection.initialize()

        print_success("Agent 初始化完成")

        # 2. 执行扫描
        print_info(f"开始扫描镜像: {image_name}")
        print()

        start_time = datetime.utcnow()

        result = await master.process(
            image_name=image_name,
            image_id=image_name
        )

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        # 3. 显示结果
        print_header("扫描结果")

        task_id = result.get("task_id")
        extract_path = Path("output/extracted") / task_id

        if not task_id:
            print_error("未获取到任务 ID")
            return False

        # 获取任务信息
        db_task = await database.get_task(task_id)
        if not db_task:
            print_error("未获取到任务信息")
            return False

        # 基本信息
        print(f"镜像: {image_name}")
        print(f"任务 ID: {task_id}")
        print(f"状态: {db_task.get('status', 'UNKNOWN')}")
        print(f"扫描耗时: {duration:.2f} 秒")

        # 获取凭证列表
        credentials = await database.get_credentials_by_task(task_id)
        credentials_found = len(credentials)

        print(f"\n发现凭证: {credentials_found} 个")

        if credentials:
            # 统计信息
            cred_types = Counter(cred.get("cred_type", "UNKNOWN") for cred in credentials)
            high_conf = sum(1 for cred in credentials if cred.get("confidence", 0) >= 0.8)
            medium_conf = sum(1 for cred in credentials if 0.5 <= cred.get("confidence", 0) < 0.8)

            print(f"  - 高置信度 (≥0.8): {high_conf} 个")
            print(f"  - 中置信度 (0.5-0.8): {medium_conf} 个")
            print(f"  - 低置信度 (<0.5): {credentials_found - high_conf - medium_conf} 个")

            # 凭证类型分布
            if cred_types:
                print(f"\n凭证类型分布:")
                for cred_type, count in cred_types.most_common():
                    print(f"  - {cred_type}: {count} 个")

            # 风险等级
            if high_conf >= 10:
                risk_level = "HIGH"
                risk_emoji = "🔴"
            elif high_conf >= 3:
                risk_level = "MEDIUM"
                risk_emoji = "🟡"
            else:
                risk_level = "LOW"
                risk_emoji = "🟢"

            print(f"\n风险等级: {risk_emoji} {risk_level}")

            # 显示解压目录路径（便于用户查看文件）
            print(f"\n📂 解压文件位置: {extract_path}/")
            print(f"   (可以查看凭证在镜像中的具体位置)")

            # 详细凭证列表
            if verbose:
                print(f"\n{'='*70}")
                print("详细凭证列表")
                print(f"{'='*70}\n")

                for i, cred in enumerate(credentials[:20], 1):  # 最多显示20个
                    cred_type = cred.get("cred_type", "UNKNOWN")
                    conf = cred.get("confidence", 0.0)
                    file_path = cred.get("file_path", "")
                    layer_id = cred.get("layer_id", "")
                    line_number = cred.get("line_number")
                    validation_status = cred.get("validation_status", "PENDING")

                    # 置信度样式
                    if conf >= 0.8:
                        conf_style = f"🔴 {conf:.2f}"
                    elif conf >= 0.5:
                        conf_style = f"🟡 {conf:.2f}"
                    else:
                        conf_style = f"🟢 {conf:.2f}"

                    print(f"{i}. [{cred_type}] {conf_style}")
                    print(f"   文件: {file_path}")
                    if line_number:
                        print(f"   行号: {line_number}")
                    if layer_id:
                        print(f"   层: {layer_id[:12]}...")
                    if validation_status != "PENDING":
                        print(f"   验证: {validation_status}")
                    print()

                if len(credentials) > 20:
                    print(f"... 还有 {len(credentials) - 20} 个凭证未显示\n")

            # 保存结果到 JSON
            if output_file:
                import json

                # 收集 token 使用统计
                token_usage = {
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0
                }

                # 从任意一个 llm_client 获取统计（都是全局单例）
                if hasattr(executor, 'filename_analyzer') and hasattr(executor.filename_analyzer, 'llm_client'):
                    token_usage = executor.filename_analyzer.llm_client.get_token_usage()
                elif hasattr(executor, 'content_scanner') and hasattr(executor.content_scanner, 'llm_client'):
                    token_usage = executor.content_scanner.llm_client.get_token_usage()

                result_data = {
                    "task_id": task_id,
                    "image": image_name,
                    "image_id": db_task.get("image_id", ""),
                    "status": db_task.get("status", ""),
                    "credentials_found": credentials_found,
                    "risk_level": "HIGH" if high_conf >= 10 else "MEDIUM" if high_conf >= 3 else "LOW",
                    "token_usage": token_usage,
                    "statistics": {
                        "total_layers": db_task.get("total_layers", 0),
                        "processed_layers": db_task.get("processed_layers", 0),
                        "total_files": db_task.get("total_files", 0),
                        "high_confidence": high_conf,
                        "medium_confidence": medium_conf,
                    },
                    "credentials": [
                        {
                            "type": cred.get("cred_type"),
                            "confidence": cred.get("confidence"),
                            "file_path": cred.get("file_path"),
                            "layer_id": cred.get("layer_id"),
                            "line_number": cred.get("line_number"),
                            "validation_status": cred.get("validation_status")
                        }
                        for cred in credentials
                    ],
                    "created_at": db_task.get("created_at", ""),
                    "started_at": db_task.get("started_at", ""),
                    "completed_at": db_task.get("completed_at", "")
                }

                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result_data, f, indent=2, ensure_ascii=False)

                print_success(f"结果已保存到: {output_path}")

        # 清理
        await master.stop()
        await executor.stop()
        await validator.stop()
        await knowledge.stop()
        await reflection.stop()

        print_success("扫描完成！")
        return True

    except Exception as e:
        print_error(f"扫描失败: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return False


async def show_history(limit: int = 10):
    """显示历史扫描记录"""

    print_header("扫描历史记录")

    try:
        database = get_database()
        await database.init()

        # 获取历史记录
        tasks = await database.get_all_tasks(limit=limit)

        if not tasks:
            print_warning("暂无扫描记录")
            return

        # 显示记录
        print(f"最近 {len(tasks)} 条扫描记录:\n")

        for i, task in enumerate(tasks, 1):
            task_id = task.get("task_id", "")[:12]
            image_name = task.get("image_name", "")
            status = task.get("status", "UNKNOWN")
            credentials_found = task.get("credentials_found", 0)
            created_at = task.get("created_at", "")[:19] if len(task.get("created_at", "")) > 19 else task.get("created_at", "")

            # 计算耗时
            duration = "N/A"
            if task.get("started_at") and task.get("completed_at"):
                start = task["started_at"]
                end = task["completed_at"]
                if isinstance(start, str) and isinstance(end, str):
                    try:
                        start_dt = datetime.fromisoformat(start)
                        end_dt = datetime.fromisoformat(end)
                        duration = f"{(end_dt - start_dt).total_seconds():.1f}s"
                    except:
                        pass

            # 状态样式
            if status == "COMPLETED":
                status_emoji = "✅"
            elif status == "FAILED":
                status_emoji = "❌"
            elif status == "RUNNING":
                status_emoji = "⏳"
            else:
                status_emoji = "❓"

            print(f"{i}. {task_id} - {image_name}")
            print(f"   状态: {status_emoji} {status}")
            print(f"   凭证: {credentials_found} 个")
            print(f"   时间: {created_at}")
            print(f"   耗时: {duration}")
            print()

    except Exception as e:
        print_error(f"查询失败: {e}")
        if logger:
            logger.error("显示历史失败", error=str(e))
