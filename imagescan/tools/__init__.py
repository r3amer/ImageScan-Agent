"""
工具包初始化

导入所有工具模块，触发工具注册
"""

# 导入工具模块（触发装饰器注册）
from . import docker_tools
from . import tar_tools
from . import file_tools

# 导出注册表实例
from .registry import registry

__all__ = ["registry"]
