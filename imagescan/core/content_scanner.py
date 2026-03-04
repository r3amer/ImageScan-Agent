"""
内容扫描器 - 文件读取与摘要

职责：
1. 读取文件内容（文本/二进制）
2. 大文件自动摘要（50KB 触发）
3. 正则匹配敏感行

参考：docs/IMPLEMENTATION_PLAN.md v2.0
"""

import os
import json
import re
from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class FileContent:
    """
    文件内容结果

    Attributes:
        content: 实际内容（可能被摘要）
        is_summary: 是否被摘要
        original_size: 原始文件大小（字节）
        summary_size: 摘要后大小（字节）
        metadata: 元数据
    """
    content: str
    is_summary: bool
    original_size: int
    summary_size: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "content": self.content,
            "is_summary": self.is_summary,
            "original_size": self.original_size,
            "summary_size": self.summary_size,
            "metadata": self.metadata
        }


class ContentScanner:
    """
    内容扫描器

    职责：
    1. 读取文件内容
    2. 自动摘要大文件
    3. 提供内容给 ScanAgent 分析
    """

    # 敏感关键词正则模式（简化，只匹配关键词和赋值符号）
    SENSITIVE_PATTERNS = [
        r'\bpassword\s*[:=]',
        r'\bpasswd\s*[:=]',
        r'\bpwd\s*[:=]',
        r'\bsecret\s*[:=]',
        r'\bapi_?key\s*[:=]',
        r'\bapikey\s*[:=]',
        r'\baccess_?token\s*[:=]',
        r'\brefresh_?token\s*[:=]',
        r'\bauth_?token\s*[:=]',
        r'\bbearer\s+[A-Za-z0-9\-._~+/]+=*',
        r'\bcredential\s*[:=]',
        r'\bprivate_?key\s*[:=]',
        r'\bdatabase_url\s*[:=]',
        r'\bdb_url\s*[:=]',
        r'\bconnection_?string\s*[:=]',
        r'\baws_?access_?key\s*[:=]',
        r'\baws_?secret_?key\s*[:=]',
        r'\bazure_?key\s*[:=]',
        r'\bssh_?key\s*[:=]',
        r'\blicense_?key\s*[:=]',
    ]

    # 编译正则（忽略大小写）
    COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in SENSITIVE_PATTERNS]

    def __init__(
        self,
        max_size: int = 1024 * 1024,  # 最大读取 1MB
        summary_threshold: int = 50 * 1024  # 50KB 触发摘要
    ):
        """
        初始化扫描器

        Args:
            max_size: 最大文件大小（字节）
            summary_threshold: 摘要阈值（字节）
        """
        self.max_size = max_size
        self.summary_threshold = summary_threshold

    def read_file(self, file_path: str) -> Optional[FileContent]:
        """
        读取文件，自动摘要

        Args:
            file_path: 文件路径

        Returns:
            FileContent 对象，读取失败返回 None
        """
        if not os.path.exists(file_path):
            return None

        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > self.max_size:
            return None

        # 读取内容
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            return None

        # 判断是否需要摘要
        if file_size > self.summary_threshold:
            summary_result = self._summarize_content(file_path, content)
            return FileContent(
                content=summary_result['content'],
                is_summary=True,
                original_size=file_size,
                summary_size=len(summary_result['content']),
                metadata=summary_result['metadata']
            )
        else:
            return FileContent(
                content=content,
                is_summary=False,
                original_size=file_size,
                summary_size=file_size,
                metadata={"file_type": self._get_file_type(file_path)}
            )

    def read_binary_file(self, file_path: str) -> Optional[bytes]:
        """
        读取二进制文件

        Args:
            file_path: 文件路径

        Returns:
            文件内容，读取失败返回 None
        """
        if not os.path.exists(file_path):
            return None

        if os.path.getsize(file_path) > self.max_size:
            return None

        try:
            with open(file_path, 'rb') as f:
                return f.read()
        except Exception:
            return None

    def _get_file_type(self, file_path: str) -> str:
        """获取文件类型"""
        ext = Path(file_path).suffix.lower()
        type_map = {
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
            '.sh': 'shell',
            '.bash': 'shell',
            '.zsh': 'shell',
            '.env': 'env',
            '.properties': 'properties',
            '.ini': 'ini',
            '.cfg': 'cfg',
            '.conf': 'conf',
            '.xml': 'xml',
            '.toml': 'toml',
        }
        return type_map.get(ext, 'unknown')

    def _summarize_content(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        摘要文件内容

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            {
                "content": 摘要后的内容,
                "metadata": 元数据
            }
        """
        file_type = self._get_file_type(file_path)

        if file_type == 'json':
            return self._extract_json_summary(file_path, content)
        elif file_type in ['yaml', 'yml', 'python', 'javascript', 'typescript',
                          'shell', 'env', 'properties', 'ini', 'cfg', 'conf']:
            return self._extract_code_summary(file_path, content)
        else:
            return self._extract_generic_summary(content)

    def _extract_json_summary(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        提取 JSON 文件摘要

        提取包含敏感关键词的 key-value 对
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # JSON 解析失败，回退到通用摘要
            return self._extract_generic_summary(content)

        # 递归提取敏感 key
        sensitive_items = self._extract_sensitive_keys_recursive(data)

        if not sensitive_items:
            # 没有找到敏感 key，使用通用摘要
            return self._extract_generic_summary(content)

        summary_content = json.dumps(sensitive_items, indent=2, ensure_ascii=False)

        return {
            "content": summary_content,
            "metadata": {
                "file_type": "json",
                "extraction_method": "sensitive_keys",
                "extracted_keys": len(sensitive_items),
                "original_size": len(content),
                "summary_size": len(summary_content)
            }
        }

    def _extract_sensitive_keys_recursive(self, data, path="") -> dict:
        """
        递归提取包含敏感关键词的 key-value 对

        Args:
            data: JSON 数据
            path: 当前路径（用于嵌套对象）

        Returns:
            敏感项字典
        """
        sensitive_keywords = [
            'password', 'secret', 'key', 'token', 'api',
            'credential', 'private', 'auth', 'license'
        ]

        result = {}

        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                current_path = f"{path}.{key}" if path else key

                # 检查是否包含敏感关键词
                if any(kw in key_lower for kw in sensitive_keywords):
                    # 限制值的大小
                    if isinstance(value, (str, int, float, bool, type(None))):
                        result[key] = str(value)[:500]
                    elif isinstance(value, dict):
                        result[key] = value
                    elif isinstance(value, list):
                        result[key] = value[:10]  # 最多保留 10 个元素
                    else:
                        result[key] = str(value)[:500]

                # 递归处理嵌套对象
                if isinstance(value, dict):
                    nested = self._extract_sensitive_keys_recursive(value, current_path)
                    if nested:
                        result[key] = nested

        return result

    def _extract_code_summary(self, file_path: str, content: str) -> Dict[str, Any]:
        """
        提取代码/配置文件摘要

        使用正则匹配包含敏感关键词的行
        """
        lines = content.split('\n')

        # 查找匹配的行
        sensitive_lines = []
        for i, line in enumerate(lines, 1):
            # 检查是否匹配任何敏感模式
            for pattern in self.COMPILED_PATTERNS:
                if pattern.search(line):
                    # 添加上下文（前后各 2 行）
                    start = max(0, i - 3)
                    end = min(len(lines), i + 2)
                    sensitive_lines.extend([
                        {"line_num": j + 1, "content": lines[j]}
                        for j in range(start, end)
                        if j not in [sl.get("line_num", 0) - 1 for sl in sensitive_lines]
                    ])
                    break

        # 构建摘要
        summary_lines = []
        for item in sensitive_lines:
            summary_lines.append(f"Line {item['line_num']}: {item['content']}")

        summary_content = '\n'.join(summary_lines)

        return {
            "content": summary_content,
            "metadata": {
                "file_type": self._get_file_type(file_path),
                "extraction_method": "regex_match",
                "total_lines": len(lines),
                "extracted_lines": len(sensitive_lines),
                "original_size": len(content),
                "summary_size": len(summary_content)
            }
        }

    def _extract_generic_summary(self, content: str) -> Dict[str, Any]:
        """
        通用摘要（头 + 尾）

        用于无法解析的文件类型
        """
        head_size = 5 * 1024  # 5KB
        tail_size = 5 * 1024  # 5KB

        head = content[:head_size]
        tail = content[-tail_size:] if len(content) > head_size + tail_size else ""

        omitted = len(content) - len(head) - len(tail)
        summary_content = head

        if omitted > 0:
            summary_content += f"\n\n...(省略 {omitted:,} 字节)...\n\n"
            summary_content += tail

        return {
            "content": summary_content,
            "metadata": {
                "file_type": "unknown",
                "extraction_method": "head_tail",
                "original_size": len(content),
                "summary_size": len(summary_content)
            }
        }
