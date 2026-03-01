"""
工具注册表

用途：
1. 注册所有可用的工具函数
2. 生成工具的 JSON Schema
3. 提供工具调用接口

参考：docs/APP_FLOW.md（工具调用详解）
"""

import inspect
from typing import Callable, Dict, Any, Optional


class ToolRegistry:
    """
    工具注册表

    管理所有可用的工具，提供注册、查询、调用功能。
    """

    def __init__(self):
        """初始化空的工具注册表"""
        self._tools: Dict[str, Callable] = {}

    def register(self, name: Optional[str] = None):
        """
        装饰器：注册工具函数

        Args:
            name: 工具名称（默认使用函数名）

        Returns:
            装饰器函数

        示例:
            >>> registry = ToolRegistry()
            >>> @registry.register("docker.save")
            >>> def docker_save(image_name: str, output_path: str) -> str:
            ...     return f"Saved {image_name}"
        """
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            self._tools[tool_name] = func
            return func
        return decorator

    def get(self, name: str) -> Callable:
        """
        获取工具函数

        Args:
            name: 工具名称

        Returns:
            工具函数

        Raises:
            ValueError: 工具不存在
        """
        if name not in self._tools:
            raise ValueError(f"Tool not found: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        """
        检查工具是否存在

        Args:
            name: 工具名称

        Returns:
            是否存在
        """
        return name in self._tools

    def list_tools(self) -> Dict[str, str]:
        """
        列出所有工具及其描述

        Returns:
            工具名称到描述的映射
        """
        return {
            name: func.__doc__ or "No description"
            for name, func in self._tools.items()
        }

    def get_schema(self, name: str) -> Dict[str, Any]:
        """
        获取工具的 JSON Schema

        Args:
            name: 工具名称

        Returns:
            JSON Schema 格式的工具描述

        Raises:
            ValueError: 工具不存在
        """
        func = self.get(name)
        sig = inspect.signature(func)

        # 解析函数签名
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            # 获取类型信息
            param_type = param.annotation
            if param_type == inspect.Parameter.empty:
                param_type = "any"
            else:
                param_type = str(param_type)

            # 构建属性定义
            prop_def = {
                "type": param_type,
                "description": f"Parameter: {param_name}"
            }

            # 检查是否有默认值
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

            properties[param_name] = prop_def

        # 构建完整的 schema
        schema = {
            "name": name,
            "description": func.__doc__ or f"Tool: {name}",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

        return schema

    def get_all_schemas(self) -> list[Dict[str, Any]]:
        """
        获取所有工具的 JSON Schema

        Returns:
            JSON Schema 列表
        """
        return [self.get_schema(name) for name in self._tools]

    async def call(self, name: str, **kwargs) -> Any:
        """
        调用工具（异步支持）

        Args:
            name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具不存在
            Exception: 工具执行失败
        """
        func = self.get(name)

        # 检查是否是协程函数
        if inspect.iscoroutinefunction(func):
            return await func(**kwargs)
        else:
            return func(**kwargs)

    def call_sync(self, name: str, **kwargs) -> Any:
        """
        调用工具（同步）

        Args:
            name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具不存在
            Exception: 工具执行失败
        """
        func = self.get(name)
        return func(**kwargs)


# 全局工具注册表实例
registry = ToolRegistry()
