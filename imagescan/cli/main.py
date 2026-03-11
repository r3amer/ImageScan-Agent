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
from ..core.orchestrator import ScanOrchestrator

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
    images: List[str] = typer.Argument(..., help="Docker 镜像名称（支持多个镜像，如 nginx:latest python:3.11）"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出 JSON 文件路径（多镜像时忽略）"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出（显示凭证详情）"),
    debug: bool = typer.Option(False, "--debug", help="启用调试模式（显示详细日志）"),
    concurrent: int = typer.Option(3, "--concurrent", "-c", help="并发扫描数量（默认 3）"),
):
    """
    扫描 Docker 镜像中的敏感凭证

    示例：
        imagescan scan nginx:latest
        imagescan scan python:3.11 --output results.json
        imagescan scan nginx:latest python:3.11 redis:latest --concurrent 2
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

            # 加载配置
            config = get_config()

            # 获取事件总线
            from ..core.event_bus import get_event_bus
            event_bus = get_event_bus()

            # images 已经是 List[str] 类型
            image_list = images

            # 多镜像警告
            if len(image_list) > 1 and output:
                console.print("[yellow]⚠[/yellow] 多镜像扫描时，--output 参数将被忽略")
                console.print("[yellow]  每个镜像的结果将自动保存到 output/{task_id}/result.json[/yellow]\n")

            # 创建并发信号量
            semaphore = asyncio.Semaphore(concurrent)

            # 扫描单个镜像的封装函数
            async def scan_single_image(image: str) -> tuple[str, dict]:
                """扫描单个镜像，返回 (image, result) 元组"""
                async with semaphore:
                    # 创建独立的编排器实例（每个任务有独立的 task_id）
                    # 注意：每个实例会自动生成独立的 task_id（UUID）
                    orchestrator = ScanOrchestrator(
                        event_bus=event_bus,
                        config=config
                    )

                    # 记录 task_id 用于调试
                    task_id = orchestrator.task_id
                    logger.info(f"为镜像 {image} 创建独立的扫描任务", task_id=task_id, image=image)

                    # 不指定 output_file，让 scan_image 自动生成 output/{task_id}/result.json
                    scan_output = None if len(image_list) > 1 else output

                    try:
                        result = await orchestrator.scan_image(
                            image_name=image,
                            output_file=scan_output
                        )
                        # 确保 result 中包含 task_id
                        if "task_id" not in result:
                            result["task_id"] = task_id
                        return (image, result)
                    except Exception as e:
                        # 返回错误信息，不中断其他扫描
                        return (image, {
                            "error": str(e),
                            "status": "FAILED"
                        })

            # 显示初始化信息
            console.print(f"[cyan]初始化扫描器...[/cyan]")
            console.print(f"[cyan]待扫描镜像 ({len(image_list)} 个):[/cyan]")
            for img in image_list:
                console.print(f"  • {img}")
            console.print(f"[cyan]并发数: {concurrent}[/cyan]\n")

            # 并发执行所有扫描
            console.print("[cyan]开始并发扫描...[/cyan]\n")

            results = await asyncio.gather(
                *[scan_single_image(img) for img in image_list],
                return_exceptions=True
            )

            # 处理结果
            successful = []
            failed = []

            for item in results:
                if isinstance(item, Exception):
                    failed.append(("", {"error": str(item), "status": "FAILED"}))
                else:
                    image, result = item
                    if result.get("status") == "FAILED":
                        failed.append((image, result))
                    else:
                        successful.append((image, result))

            # 显示汇总结果
            console.print("\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]")
            console.print(f"[bold green]扫描完成！[/bold green]")
            console.print(f"  成功: [green]{len(successful)}[/green] 个")
            console.print(f"  失败: [red]{len(failed)}[/red] 个")
            console.print("[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n")

            # 显示成功的结果
            if successful:
                console.print("[bold green]成功扫描的镜像:[/bold green]\n")
                for image, result in successful:
                    console.print(f"[cyan]▸ {image}[/cyan]")
                    task_id = result.get('task_id', 'N/A')
                    console.print(f"  任务 ID: {task_id}")
                    console.print(f"  发现凭证: [yellow]{result.get('credential_count', 0)}[/yellow] 个")

                    # 显示输出文件路径
                    output_file = result.get('output_file', '')
                    if output_file:
                        console.print(f"  结果保存: [cyan]{output_file}[/cyan]")

                    # 风险等级颜色
                    risk_level = result.get("risk_level", "LOW")
                    if risk_level == "HIGH":
                        console.print(f"  风险等级: [red]HIGH[/red]")
                    elif risk_level == "MEDIUM":
                        console.print(f"  风险等级: [yellow]MEDIUM[/yellow]")
                    else:
                        console.print(f"  风险等级: [green]LOW[/green]")

                    # 显示凭证类型分布（verbose 模式）
                    if verbose:
                        credentials = result.get("credentials", [])
                        if credentials:
                            from collections import Counter
                            cred_types = Counter(cred.get("type", "UNKNOWN") for cred in credentials)

                            console.print("  [bold]凭证类型分布:[/bold]")
                            for cred_type, count in cred_types.most_common():
                                console.print(f"    {cred_type}: {count}")

                            console.print("  [bold]发现的凭证:[/bold]")
                            for cred in credentials[:5]:  # 多镜像时只显示前5个
                                cred_type = cred.get("type", "UNKNOWN")
                                conf = cred.get("confidence", 0.0)
                                file_path = cred.get("file_path", "")

                                if conf >= 0.8:
                                    conf_style = f"[red]{conf:.2f}[/red]"
                                elif conf >= 0.5:
                                    conf_style = f"[yellow]{conf:.2f}[/yellow]"
                                else:
                                    conf_style = f"{conf:.2f}"

                                console.print(f"    • {cred_type} ({conf_style})")
                                console.print(f"      文件: {file_path}")

                            if len(credentials) > 5:
                                console.print(f"    ... 还有 {len(credentials) - 5} 个凭证")

                    console.print()

            # 显示失败的结果
            if failed:
                console.print("[bold red]扫描失败的镜像:[/bold red]\n")
                for image, result in failed:
                    console.print(f"[red]▸ {image}[/red]")
                    console.print(f"  错误: {result.get('error', 'Unknown error')}")
                    console.print()

            # 保存结果提示
            if len(image_list) > 1:
                console.print("[cyan]所有结果已保存到 output/{task_id}/result.json[/cyan]")
            elif successful:
                result_path = successful[0][1].get("output_file", output)
                console.print(f"\n[cyan]✓[/cyan] 结果已保存到: [cyan]{result_path}[/cyan]")

        except Exception as e:
            console.print(f"\n[red]✗[/red] 扫描失败: {e}")
            if debug:
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
