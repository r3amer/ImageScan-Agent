"""
ImageScan 扫描模块

提供扫描功能的可导入接口
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from .core.orchestrator import ScanOrchestrator
from .utils.config import get_config
from .utils.logger import get_logger, setup_logging, set_log_level
from .core.event_bus import get_event_bus

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


def _display_credentials(credentials, limit=20):
    """显示凭证详情"""
    from collections import Counter

    if not credentials:
        print_warning("未发现凭证")
        return

    # 统计信息
    cred_types = Counter(cred.get("type", "UNKNOWN") for cred in credentials)
    high_conf = sum(1 for cred in credentials if cred.get("confidence", 0) >= 0.8)
    medium_conf = sum(1 for cred in credentials if 0.5 <= cred.get("confidence", 0) < 0.8)

    print(f"\n发现凭证: {len(credentials)} 个")
    print(f"  - 高置信度 (≥0.8): {high_conf} 个")
    print(f"  - 中置信度 (0.5-0.8): {medium_conf} 个")
    print(f"  - 低置信度 (<0.5): {len(credentials) - high_conf - medium_conf} 个")

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


def _display_credential_details(credentials, limit=20):
    """显示凭证详情"""
    print(f"\n{'='*70}")
    print("详细凭证列表")
    print(f"{'='*70}\n")

    for i, cred in enumerate(credentials[:limit], 1):
        cred_type = cred.get("type", "UNKNOWN")
        conf = cred.get("confidence", 0.0)
        file_path = cred.get("file_path", "")
        layer_id = cred.get("layer_id")
        line_number = cred.get("line_number")

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
        print()

    if len(credentials) > limit:
        print(f"... 还有 {len(credentials) - limit} 个凭证未显示\n")


async def scan_image(
    image_name: str,
    output_file: str = None,
    verbose: bool = False,
    debug: bool = False
):
    """扫描 Docker 镜像"""

    print_header("ImageScan Agent - Docker 镜像敏感凭证扫描")

    # 初始化日志系统（使用文本格式，便于用户查看）
    setup_logging(level="DEBUG", log_format="text")

    # 设置日志级别
    if debug:
        set_log_level("DEBUG")
        print_info("已启用调试模式")
    else:
        set_log_level("INFO")

    try:
        # 加载配置
        config = get_config()

        # 获取事件总线
        event_bus = get_event_bus()

        # 创建扫描编排器
        print_info("初始化扫描器...")
        orchestrator = ScanOrchestrator(
            event_bus=event_bus,
            config=config
        )

        print_success("扫描器初始化完成")

        # 执行扫描
        print_info(f"开始扫描镜像: {image_name}")
        print()

        start_time = datetime.now(timezone.utc)

        result = await orchestrator.scan_image(
            image_name=image_name,
            output_file=output_file
        )

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        # 显示结果
        print_header("扫描结果")

        # 基本信息
        print(f"镜像: {image_name}")
        print(f"任务 ID: {result.get('task_id', 'N/A')}")
        print(f"状态: {result.get('status', 'UNKNOWN')}")
        print(f"扫描耗时: {duration:.2f} 秒")

        # 显示凭证信息
        credentials = result.get("credentials", [])
        _display_credentials(credentials)

        # 显示统计信息
        stats = result.get("statistics", {})
        if stats:
            print(f"\n扫描统计:")
            print(f"  - 总层数: {stats.get('total_layers', 0)}")
            print(f"  - 已处理层: {stats.get('processed_layers', 0)}")
            print(f"  - 总文件数: {stats.get('total_files', 0)}")
            print(f"  - 已扫描文件: {stats.get('scanned_files', 0)}")

        # Token 使用统计
        token_usage = result.get("token_usage", {})
        if token_usage.get("call_count", 0) > 0:
            print(f"\nAPI 使用统计:")
            print(f"  - 调用次数: {token_usage.get('call_count', 0)}")
            print(f"  - 总 Token: {token_usage.get('total_tokens', 0)}")
            print(f"  - 输入 Token: {token_usage.get('prompt_tokens', 0)}")
            print(f"  - 输出 Token: {token_usage.get('completion_tokens', 0)}")

        # 详细输出
        if verbose and credentials:
            _display_credential_details(credentials)

        # 保存结果（如果没有在 orchestrator 中保存）
        if output_file:
            print_success(f"结果已保存到: {output_file}")

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

    print_warning("历史记录功能需要数据库支持，当前使用 SimpleStorageManager")
    print_info("如需查看历史记录，请使用 JSON 输出文件")
    print()

    # 列出可能的输出文件
    output_dir = Path("./data")
    if output_dir.exists():
        json_files = list(output_dir.glob("*.json"))
        if json_files:
            print(f"找到 {len(json_files)} 个结果文件:")
            for f in sorted(json_files, key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
                print(f"  - {f.name}")
        else:
            print_warning("未找到结果文件")
    else:
        print_warning("数据目录不存在: ./data")
