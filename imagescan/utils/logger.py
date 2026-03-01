"""
日志系统模块

用途：
1. 结构化 JSON 日志
2. 日志级别管理
3. 日志轮转
4. 上下文绑定

参考：docs/BACKEND_STRUCTURE.md
"""

import logging
import sys
from pathlib import Path
from typing import Any
import structlog
from loguru import logger as loguru_logger


def setup_logging(
    level: str = "INFO",
    log_format: str = "json",
    log_path: str = "./logs",
    rotation_days: int = 7
) -> None:
    """
    配置结构化日志系统

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        log_format: 日志格式 (json 或 text)
        log_path: 日志文件目录
        rotation_days: 日志轮转周期（天）
    """
    # 确保日志目录存在
    Path(log_path).mkdir(parents=True, exist_ok=True)

    # 配置标准库 logging（structlog 依赖）
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper()),
        stream=sys.stdout
    )

    # 配置 structlog
    if log_format == "json":
        # JSON 格式（生产环境）
        structlog.configure(
            processors=[
                # 过滤低于指定级别的日志
                structlog.stdlib.filter_by_level,

                # 添加日志级别
                structlog.stdlib.add_log_level,

                # 添加 logger 名称
                structlog.stdlib.add_logger_name,

                # 添加时间戳
                structlog.processors.TimeStamper("iso"),

                # 添加调用堆栈（仅在 DEBUG 级别）
                structlog.processors.StackInfoRenderer(),

                # 添加异常信息
                structlog.processors.format_exc_info,

                # Unicode 解码
                structlog.processors.UnicodeDecoder(),

                # JSON 渲染
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
            wrapper_class=structlog.stdlib.BoundLogger,
        )
    else:
        # 文本格式（开发环境）
        # 自定义简洁格式
        class SimpleRenderer:
            def __call__(self, logger, log_method, event_dict):
                # 简洁格式: [级别] 消息
                level = log_method.upper()
                # 添加颜色
                level_colors = {
                    "DEBUG": "\033[36m",  # 青色
                    "INFO": "\033[32m",   # 绿色
                    "WARNING": "\033[33m", # 黄色
                    "ERROR": "\033[31m",   # 红色
                    "CRITICAL": "\033[35m" # 紫色
                }
                reset = "\033[0m"
                color = level_colors.get(level, "")

                # 基础消息
                output = f"{color}[{level}]{reset} {event_dict.get('event', '')}"

                # 如果有额外的上下文信息，添加到后面
                context = {k: v for k, v in event_dict.items() if k not in ('event', 'timestamp', 'level', 'logger', 'log_level')}
                if context:
                    context_str = ", ".join(f"{k}={v}" for k, v in context.items())
                    output += f" ({context_str})"

                return output

        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper("iso"),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                SimpleRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
            wrapper_class=structlog.stdlib.BoundLogger,
        )

    # 配置 loguru（用于文件日志和轮转）
    log_file = Path(log_path) / "imagescan.log"

    # 移除默认 handler
    loguru_logger.remove()

    # 添加控制台 handler（文本格式）
    loguru_logger.add(
        sys.stdout,
        level=level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True
    )

    # 添加文件 handler（JSON 格式）
    loguru_logger.add(
        log_file,
        level=level.upper(),
        format="{message}",  # JSON 格式由 serializer 处理
        rotation=f"{rotation_days} days",
        retention="30 days",  # 保留 30 天
        compression="zip",  # 压缩旧日志
        serialize=True,  # JSON 格式
        enqueue=True,  # 异步写入
        backtrace=True,  # 完整堆栈
        diagnose=True  # 变量值
    )


def get_logger(name: str) -> Any:
    """
    获取 logger 实例

    Args:
        name: logger 名称（通常使用 __name__）

    Returns:
        logger 实例

    示例:
        >>> from imagescan.utils.logger import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("Scanner started", task_id="abc-123")
    """
    return structlog.get_logger(name)


def set_log_level(level: str = "INFO") -> None:
    """
    动态设置日志级别

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)

    示例:
        >>> set_log_level("DEBUG")  # 启用debug输出
        >>> set_log_level("INFO")   # 只显示info和warning
    """
    level_upper = level.upper()

    # 1. 设置标准库 logging 的级别（structlog 依赖这个）
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level_upper))

    # 2. 更新 loguru 的控制台 handler
    # 移除控制台handler（通过检查handler的sink）
    handlers_to_remove = []
    for idx, handler in enumerate(list(loguru_logger._core.handlers.values())):
        try:
            # 获取handler的sink信息
            handler_repr = repr(handler)
            # 如果是控制台输出（stdout/stderr），标记移除
            if 'stdout' in handler_repr or 'stderr' in handler_repr:
                handlers_to_remove.append(idx)
        except:
            pass

    # 从后往前删除，避免索引问题
    # 注意：需要使用实际的 handler ID 而不是索引
    handler_ids = list(loguru_logger._core.handlers.keys())
    for idx in sorted(handlers_to_remove, reverse=True):
        if idx < len(handler_ids):
            loguru_logger.remove(handler_ids[idx])

    # 重新添加控制台handler，使用新的级别
    loguru_logger.add(
        sys.stdout,
        level=level_upper,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True
    )


def get_current_level() -> str:
    """
    获取当前日志级别

    Returns:
        当前日志级别
    """
    if loguru_logger.core.handlers:
        for handler in loguru_logger.core.handlers:
            if handler.__class__.__name__ != "FileHandler":
                return handler.levelname
    return "INFO"


# 为了向后兼容，也导出一个全局 logger
def bind_context(**kwargs) -> None:
    """
    绑定全局上下文（所有日志都会包含这些字段）

    Args:
        **kwargs: 上下文字段

    示例:
        >>> bind_context(task_id="abc-123", user="alice")
        >>> logger.info("Processing file")  # 自动包含 task_id 和 user
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """清除全局上下文"""
    structlog.contextvars.clear_contextvars()


# 兼容 loguru 的简单接口
class Logger:
    """
    简化的 Logger 接口

    提供 loguru 风格的 API，但底层使用 structlog
    """

    def __init__(self, name: str):
        self._logger = get_logger(name)
        self._name = name

    def debug(self, message: str, **kwargs):
        """记录 DEBUG 级别日志"""
        self._logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs):
        """记录 INFO 级别日志"""
        self._logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs):
        """记录 WARNING 级别日志"""
        self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs):
        """记录 ERROR 级别日志"""
        self._logger.error(message, **kwargs)

    def exception(self, message: str, **kwargs):
        """记录异常（自动包含堆栈信息）"""
        self._logger.exception(message, **kwargs)

    def bind(self, **kwargs) -> "Logger":
        """
        绑定上下文（返回新的 logger 实例）

        Args:
            **kwargs: 上下文字段

        Returns:
            新的 logger 实例
        """
        # structlog 的 bind 会返回新的 context
        new_logger = Logger(self._name)
        new_logger._logger = self._logger.bind(**kwargs)
        return new_logger
