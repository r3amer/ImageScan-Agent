"""
LLM 函数调用字符串解析器

职责：
1. 解析 LLM 输出的函数调用字符串（如 docker_save("nginx", "./out")）
2. 使用 AST 安全解析
3. 返回结构化的函数名和参数

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

import ast
from typing import Any, Dict, List, Optional


class ParseError(Exception):
    """解析错误"""
    pass


class LLMFunctionCallParser:
    """
    LLM 函数调用字符串解析器

    使用 AST 安全解析 LLM 输出的函数调用字符串
    """

    def __init__(self):
        """初始化解析器"""
        pass

    def parse(self, llm_output: str) -> Dict[str, Any]:
        """
        解析 LLM 输出的函数调用字符串

        Args:
            llm_output: LLM 输出文本

        Returns:
            {
                "function_name": str,  # 函数名
                "args": Dict           # {"args": [], "kwargs": {}}
            }

        Raises:
            ParseError: 解析失败
        """
        # 提取函数调用字符串
        call_str = self._extract_call_string(llm_output)
        if not call_str:
            raise ParseError("No function call found in LLM output")

        # 使用 AST 解析
        try:
            tree = ast.parse(call_str, mode='eval')
            call = tree.body

            if not isinstance(call, ast.Call):
                raise ParseError("Not a function call")

            func_name = self._get_function_name(call)
            args = self._parse_arguments(call)

            return {
                "function_name": func_name,
                "args": args
            }

        except (SyntaxError, ValueError) as e:
            raise ParseError(f"Failed to parse function call: {e}")

    def _extract_call_string(self, llm_output: str) -> Optional[str]:
        """
        从 LLM 输出中提取函数调用字符串

        Args:
            llm_output: LLM 输出文本

        Returns:
            函数调用字符串，未找到返回 None
        """
        # 按行分割，查找包含函数调用的行
        lines = llm_output.strip().split('\n')

        for line in lines:
            line = line.strip()
            # 跳过空行和注释
            if not line or line.startswith('#'):
                continue
            # 检查是否包含函数调用模式
            if '(' in line and ')' in line and not line.startswith('http'):
                return line

        return None

    def _get_function_name(self, call: ast.Call) -> str:
        """
        获取函数名

        Args:
            call: AST Call 节点

        Returns:
            函数名

        Raises:
            ParseError: 不支持的函数调用类型
        """
        if isinstance(call.func, ast.Name):
            # 简单函数名：docker_save
            return call.func.id
        elif isinstance(call.func, ast.Attribute):
            # 属性访问：docker.save
            return call.func.attr
        else:
            raise ParseError(f"Unsupported function call type: {type(call.func)}")

    def _parse_arguments(self, call: ast.Call) -> Dict[str, Any]:
        """
        解析函数参数

        Args:
            call: AST Call 节点

        Returns:
            {"args": [], "kwargs": {}}
        """
        # 解析位置参数
        args = []
        for arg in call.args:
            args.append(self._parse_value(arg))

        # 解析关键字参数
        kwargs = {}
        for keyword in call.keywords:
            if keyword.arg:
                kwargs[keyword.arg] = self._parse_value(keyword.value)

        return {
            "args": args,
            "kwargs": kwargs
        }

    def _parse_value(self, node: ast.AST) -> Any:
        """
        解析 AST 节点为 Python 值

        Args:
            node: AST 节点

        Returns:
            Python 值

        Raises:
            ParseError: 不支持的值类型
        """
        if isinstance(node, ast.Constant):
            # 常量：字符串、数字、布尔值
            return node.value
        elif isinstance(node, ast.Str):
            # 字符串（Python 3.7 及以下）
            return node.s
        elif isinstance(node, ast.Num):
            # 数字（Python 3.7 及以下）
            return node.n
        elif isinstance(node, ast.List):
            # 列表
            return [self._parse_value(e) for e in node.elts]
        elif isinstance(node, ast.Dict):
            # 字典
            keys = [self._parse_value(k) for k in node.keys]
            values = [self._parse_value(v) for v in node.values]
            return dict(zip(keys, values))
        elif isinstance(node, ast.NameConstant):
            # None/True/False（Python 3.7 及以下）
            return node.value
        else:
            raise ParseError(f"Unsupported value type: {type(node).__name__}")

    def parse_multiple(self, llm_output: str) -> List[Dict[str, Any]]:
        """
        解析多个函数调用

        Args:
            llm_output: LLM 输出文本（可能包含多个函数调用）

        Returns:
            [{"function_name": str, "args": Dict}, ...]
        """
        results = []
        lines = llm_output.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # 检查是否是函数调用
            if '(' in line and ')' in line and not line.startswith('http'):
                try:
                    result = self.parse(line)
                    results.append(result)
                except ParseError:
                    # 跳过无法解析的行
                    continue

        return results
