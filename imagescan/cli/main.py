"""
CLI 主入口模块

用途：
1. 定义所有 CLI 子命令
2. 实现命令行交互
3. 美化输出（使用 Rich）
4. 进度条显示

参考：docs/APP_FLOW.md, docs/PRD.md
"""

import typer
from typing import Optional, List
from pathlib import Path
import asyncio
import sys

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from ..utils.logger import get_logger
from ..utils.config import get_config
from ..agents.master_agent import MasterAgent
from ..agents.executor_agent import ExecutorAgent
from ..agents.validation_agent import ValidationAgent
from ..agents.knowledge_agent import KnowledgeAgent
from ..agents.reflection_agent import ReflectionAgent
from ..utils.database import get_database

logger = get_logger(__name__)
console = Console()

# 创建 Typer 应用（使用 terminal_width 参数避免 rich 格式化问题）
app = typer.Typer(
    name="imagescan",
    help="ImageScan Agent - Docker 镜像敏感凭证扫描工具",
    add_completion=True,
    context_settings={"max_content_width": 120}
)


# ========== 辅助函数 ==========

def init_agents():
    """初始化所有 Agent"""
    event_bus = None  # 使用全局实例
    database = get_database()

    master = MasterAgent(event_bus=event_bus, database=database)
    executor = ExecutorAgent(event_bus=event_bus, database=database)
    validator = ValidationAgent(event_bus=event_bus, database=database)
    knowledge = KnowledgeAgent(event_bus=event_bus)
    reflection = ReflectionAgent(event_bus=event_bus, database=database)

    # 设置从 Agent
    master.set_agents(executor, validator, knowledge, reflection)

    return master, executor, validator, knowledge, reflection


# ========== version 命令 ==========

@app.command()
def version():
    """
    显示版本信息

    示例：
        imagescan version
    """
    from .. import __version__
    console.print(f"ImageScan Agent version [cyan]{__version__}[/cyan]")


# ========== scan 子命令 ==========

@app.command()
def scan(
    image: str = typer.Argument(..., help="Docker 镜像名称（如 nginx:latest）"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出 JSON 文件路径"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出（显示凭证详情）"),
    debug: bool = typer.Option(False, "--debug", help="启用调试模式（显示详细日志）"),
):
    """
    扫描 Docker 镜像中的敏感凭证

    示例：
        imagescan scan nginx:latest
        imagescan scan python:3.11 --output results.json
        imagescan scan 20.205.173.138:5000/myimage:tag1 --verbose
        imagescan scan python:3.11 --debug

    日志级别：
        默认只显示 INFO 和 WARNING 级别日志
        使用 --debug 参数查看详细的 DEBUG 日志
    """
    async def do_scan():
        try:
            # 初始化日志系统（使用文本格式，便于用户查看）
            from ..utils.logger import setup_logging, set_log_level
            setup_logging(level="DEBUG", log_format="text")  # 文本格式更美观

            # 设置日志级别
            if debug:
                set_log_level("DEBUG")
            else:
                set_log_level("INFO")

            # 初始化 Agent
            console.print("[cyan]初始化 Agent...[/cyan]")
            master, executor, validator, knowledge, reflection = init_agents()

            # 初始化所有 Agent
            await master.initialize()
            await executor.initialize()
            await validator.initialize()
            await knowledge.initialize()
            await reflection.initialize()

            console.print("[green]✓[/green] Agent 初始化完成\n")

            # 创建进度条
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:

                # 添加任务
                task = progress.add_task(
                    f"[cyan]扫描镜像 {image}[/cyan]",
                    total=100
                )

                # 订阅进度事件
                from ..core.event_bus import get_event_bus
                from ..core.events import EventType

                event_bus = get_event_bus()

                # 进度更新回调
                async def update_progress():
                    while True:
                        await asyncio.sleep(0.1)
                        stats = master.get_scan_progress()
                        if stats["task_id"]:
                            total_layers = stats["stats"].get("total_layers", 1)
                            current_layer = stats["stats"].get("processed_layers", 0)
                            percent = int((current_layer / total_layers) * 100) if total_layers > 0 else 0
                            progress.update(task, completed=percent)
                            if percent >= 100:
                                break

                # 启动进度更新任务
                progress_task = asyncio.create_task(update_progress())

                # 执行实际扫描
                try:
                    result = await master.process(
                        image_name=image,
                        image_id=image  # 使用镜像名称作为 ID
                    )
                finally:
                    progress_task.cancel()

            # 显示结果
            console.print("\n[green]✓[/green] 扫描完成！")
            console.print(f"  镜像: {image}")

            # 获取扫描结果
            task_id = result.get("task_id")
            if task_id:
                db_task = await master.database.get_task(task_id)

                if db_task:
                    credentials_found = db_task.get("credentials_found", 0)
                    console.print(f"  任务 ID: {task_id}")
                    console.print(f"  发现凭证: [yellow]{credentials_found}[/yellow] 个")

                    # 获取凭证列表
                    credentials = await master.database.get_credentials_by_task(task_id)

                    if credentials:
                        # 显示统计信息
                        from collections import Counter
                        cred_types = Counter(cred.get("cred_type", "UNKNOWN") for cred in credentials)
                        high_conf = sum(1 for cred in credentials if cred.get("confidence", 0) >= 0.8)

                        console.print(f"  高置信度: [red]{high_conf}[/red] 个")

                        # 显示凭证类型分布
                        if verbose:
                            console.print("\n  [bold]凭证类型分布:[/bold]")
                            for cred_type, count in cred_types.most_common():
                                console.print(f"    {cred_type}: {count}")

                        # 风险等级评估
                        if high_conf >= 10:
                            risk_level = "[red]HIGH[/red]"
                        elif high_conf >= 3:
                            risk_level = "[yellow]MEDIUM[/yellow]"
                        else:
                            risk_level = "[green]LOW[/green]"
                        console.print(f"  风险等级: {risk_level}")

                        # 详细输出
                        if verbose and credentials:
                            console.print("\n[bold]发现的凭证:[/bold]")
                            for cred in credentials[:10]:  # 最多显示10个
                                cred_type = cred.get("cred_type", "UNKNOWN")
                                conf = cred.get("confidence", 0.0)
                                file_path = cred.get("file_path", "")

                                # 置信度样式
                                if conf >= 0.8:
                                    conf_style = f"[red]{conf:.2f}[/red]"
                                elif conf >= 0.5:
                                    conf_style = f"[yellow]{conf:.2f}[/yellow]"
                                else:
                                    conf_style = f"{conf:.2f}"

                                console.print(f"  • {cred_type} ({conf_style})")
                                console.print(f"    文件: {file_path}")

                            if len(credentials) > 10:
                                console.print(f"\n  ... 还有 {len(credentials) - 10} 个凭证")

                    # 保存结果到 JSON
                    if output:
                        import json
                        from pathlib import Path

                        result_data = {
                            "task_id": task_id,
                            "image": image,
                            "image_id": db_task.get("image_id", ""),
                            "status": db_task.get("status", ""),
                            "credentials_found": credentials_found,
                            "risk_level": "HIGH" if high_conf >= 10 else "MEDIUM" if high_conf >= 3 else "LOW",
                            "statistics": {
                                "total_layers": db_task.get("total_layers", 0),
                                "processed_layers": db_task.get("processed_layers", 0),
                                "total_files": db_task.get("total_files", 0),
                                "high_confidence": high_conf
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

                        output_path = Path(output)
                        output_path.parent.mkdir(parents=True, exist_ok=True)

                        with open(output_path, 'w', encoding='utf-8') as f:
                            json.dump(result_data, f, indent=2, ensure_ascii=False)

                        console.print(f"\n[cyan]✓[/cyan] 结果已保存到: [cyan]{output_path}[/cyan]")

            # 清理
            await master.stop()
            await executor.stop()
            await validator.stop()
            await knowledge.stop()
            await reflection.stop()

        except Exception as e:
            console.print(f"\n[red]✗[/red] 扫描失败: {e}")
            if verbose:
                import traceback
                console.print(traceback.format_exc())
            raise typer.Exit(1)

    # 运行异步任务
    asyncio.run(do_scan())


# ========== history 子命令 ==========

@app.command()
def history(
    limit: int = typer.Option(10, "--limit", "-n", help="显示最近 N 条记录"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
):
    """
    查看历史扫描记录

    示例：
        imagescan history
        imagescan history --limit 20
    """
    try:
        database = get_database()
        asyncio.run(database.init())

        # 获取历史记录
        tasks = asyncio.run(database.get_all_tasks(limit=limit))

        if not tasks:
            console.print("[yellow]暂无扫描记录[/yellow]")
            return  # 正常返回，不退出

        # 创建表格
        table = Table(title=f"扫描历史 (最近 {len(tasks)} 条)")
        table.add_column("任务 ID", style="cyan", no_wrap=False)
        table.add_column("镜像", style="green")
        table.add_column("状态", style="yellow")
        table.add_column("凭证数", style="red", justify="right")
        table.add_column("创建时间", style="blue")
        table.add_column("耗时", justify="right")

        for task in tasks:
            # 计算耗时
            duration = "N/A"
            if task.get("started_at") and task.get("completed_at"):
                start = task["started_at"]
                end = task["completed_at"]
                if isinstance(start, str) and isinstance(end, str):
                    from datetime import datetime
                    try:
                        start_dt = datetime.fromisoformat(start)
                        end_dt = datetime.fromisoformat(end)
                        duration = f"{(end_dt - start_dt).total_seconds():.1f}s"
                    except:
                        pass

            # 状态样式
            status = task.get("status", "UNKNOWN")
            if status == "COMPLETED":
                status_style = "[green]COMPLETED[/green]"
            elif status == "FAILED":
                status_style = "[red]FAILED[/red]"
            elif status == "RUNNING":
                status_style = "[yellow]RUNNING[/yellow]"
            else:
                status_style = status

            table.add_row(
                task.get("task_id", "")[:12],
                task.get("image_name", ""),
                status_style,
                str(task.get("credentials_found", 0)),
                task.get("created_at", "")[:19] if len(task.get("created_at", "")) > 19 else task.get("created_at", ""),
                duration
            )

        console.print(table)

        # 详细输出
        if verbose and tasks:
            console.print("\n[bold]详细信息:[/bold]\n")
            for task in tasks[:3]:  # 只显示前3条
                console.print(Panel(
                    f"任务 ID: {task.get('task_id')}\n"
                    f"镜像 ID: {task.get('image_id', '')[:20]}\n"
                    f"总层数: {task.get('total_layers', 0)}\n"
                    f"已处理层: {task.get('processed_layers', 0)}\n"
                    f"总文件数: {task.get('total_files', 0)}\n"
                    f"错误信息: {task.get('error_message', '无')}",
                    title=f"[cyan]{task.get('image_name')}[/cyan]",
                    border_style="blue"
                ))

    except Exception as e:
        console.print(f"[red]✗[/red] 查询失败: {e}")
        raise typer.Exit(1)


# ========== config 子命令 ==========

@app.command()
def config(
    show: bool = typer.Option(False, "--show", "-s", help="显示当前配置"),
    edit: bool = typer.Option(False, "--edit", "-e", help="编辑配置文件"),
):
    """
    查看或修改配置

    示例：
        imagescan config --show
        imagescan config --edit
    """
    try:
        config = get_config()

        if show:
            # 显示配置
            console.print(Panel(
                f"[bold]API 配置[/bold]\n"
                f"  模型: {config.api.model if hasattr(config, 'api') else 'N/A'}\n"
                f"  Base URL: {config.api.base_url if hasattr(config, 'api') else 'N/A'}\n\n"
                f"[bold]扫描参数[/bold]\n"
                f"  置信度阈值: {config.scan_parameters.confidence_threshold if hasattr(config, 'scan_parameters') else 'N/A'}\n"
                f"  最大文件大小: {config.scan_parameters.max_file_size_mb if hasattr(config, 'scan_parameters') else 'N/A'} MB\n"
                f"  启用验证: {config.scan_parameters.enable_verification if hasattr(config, 'scan_parameters') else 'N/A'}\n\n"
                f"[bold]存储配置[/bold]\n"
                f"  输出路径: {config.storage.output_path if hasattr(config, 'storage') else 'N/A'}\n"
                f"  数据库路径: {config.storage.database_path if hasattr(config, 'storage') else 'N/A'}\n",
                title="[cyan]当前配置[/cyan]",
                border_style="green"
            ))

        elif edit:
            # 编辑配置文件
            config_file = Path("config.toml")
            if not config_file.exists():
                config_file = Path("/home/alice/image_scan/ImageScan-Agent/config.toml")

            if config_file.exists():
                console.print(f"[cyan]配置文件路径:[/cyan] {config_file}")
                console.print("[yellow]请使用文本编辑器打开上述文件进行编辑[/yellow]")
            else:
                console.print("[red]✗[/red] 未找到配置文件")

        else:
            console.print("请使用 --show 或 --edit 选项")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]✗[/red] 配置操作失败: {e}")
        raise typer.Exit(1)


# ========== verify 子命令 ==========

@app.command()
def verify(
    task_id: str = typer.Argument(..., help="任务 ID"),
    revalidate: bool = typer.Option(False, "--revalidate", "-r", help="重新验证"),
):
    """
    验证扫描结果中的凭证

    示例：
        imagescan verify task_abc123
        imagescan verify task_abc123 --revalidate
    """
    async def do_verify():
        try:
            database = get_database()
            await database.init()

            # 获取任务信息
            task = await database.get_task(task_id)

            if not task:
                console.print(f"[red]✗[/red] 未找到任务: {task_id}")
                raise typer.Exit(1)

            console.print(f"[cyan]任务信息:[/cyan]")
            console.print(f"  镜像: {task.get('image_name')}")
            console.print(f"  状态: {task.get('status')}")
            console.print(f"  创建时间: {task.get('created_at')}")

            # 获取凭证列表
            credentials = await database.get_credentials_by_task(task_id)

            if not credentials:
                console.print("\n[yellow]未发现凭证[/yellow]")
                raise typer.Exit()

            console.print(f"\n[cyan]发现 {len(credentials)} 个凭证:[/cyan]\n")

            # 创建凭证表格
            table = Table()
            table.add_column("类型", style="cyan")
            table.add_column("置信度", justify="right")
            table.add_column("文件路径", style="green")
            table.add_column("验证状态", style="yellow")

            for cred in credentials:
                # 置信度样式
                conf = cred.get("confidence", 0.0)
                if conf >= 0.8:
                    conf_style = f"[red]{conf:.2f}[/red]"
                elif conf >= 0.5:
                    conf_style = f"[yellow]{conf:.2f}[/yellow]"
                else:
                    conf_style = f"{conf:.2f}"

                # 验证状态
                status = cred.get("validation_status", "PENDING")
                if status == "VALID":
                    status_style = "[green]VALID[/green]"
                elif status == "INVALID":
                    status_style = "[red]INVALID[/red]"
                else:
                    status_style = f"[yellow]{status}[/yellow]"

                table.add_row(
                    cred.get("cred_type", "UNKNOWN"),
                    conf_style,
                    cred.get("file_path", ""),
                    status_style
                )

            console.print(table)

            # 重新验证
            if revalidate:
                console.print("\n[cyan]开始重新验证...[/cyan]")
                # TODO: 调用 ValidationAgent
                console.print("[yellow]重新验证功能开发中[/yellow]")

        except Exception as e:
            console.print(f"[red]✗[/red] 验证失败: {e}")
            raise typer.Exit(1)

    asyncio.run(do_verify())


# ========== main 入口点 ==========

if __name__ == "__main__":
    app()
