"""
内容扫描器模块

用途：
1. 扫描文件内容，检测敏感凭证
2. 批量处理多个文件
3. 聚合扫描结果
4. 管理扫描状态和进度
5. 三层筛选优化：结构预检 + 大文件摘要

参考：docs/APP_FLOW.md
"""

import asyncio
import json
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from .llm_client import get_llm_client, LLMClientError
from ..utils.logger import get_logger
from ..models.credential import Credential, CredentialType, ValidationStatus

logger = get_logger(__name__)


class FileStructureChecker:
    """
    文件结构检查器（三层筛选的第二层）

    作用：
    - 解析文件结构（JSON/YAML/Python/JS/Shell）
    - 提取配置项
    - 识别敏感模式
    - 降低 LLM token 消耗
    """

    # 敏感关键词（用于判断文件是否可能包含凭证）
    SENSITIVE_KEYWORDS = [
        # 密钥相关
        'password', 'passwd', 'pwd', 'secret', 'api_key', 'apikey', 'api-key',
        'token', 'access_token', 'refresh_token', 'auth_token', 'bearer',
        'credential', 'credentials', 'private_key', 'privatekey', 'private-key',
        # 数据库
        'database_url', 'db_url', 'connection_string', 'mongodb', 'mysql',
        'postgresql', 'redis', 'elasticsearch',
        # 云服务
        'aws_access_key', 'aws_secret_key', 'azure_key', 'google_credentials',
        'stripe_key', 'github_token', 'gitlab_token',
        # 其他
        'authorization', 'auth', 'license', 'license_key', 'ssh_key'
    ]

    # 每个文件类型最少需要的敏感关键词数量（低于此值则跳过）
    MIN_SENSITIVE_PATTERNS = 1

    @classmethod
    def _get_file_type(cls, file_path: str) -> str:
        """根据扩展名判断文件类型"""
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
            '.fish': 'shell',
            '.env': 'env',
            '.properties': 'properties',
            '.ini': 'ini',
            '.cfg': 'cfg',
            '.conf': 'conf',
            '.xml': 'xml',
            '.toml': 'toml',
        }
        return type_map.get(ext, 'unknown')

    @classmethod
    def _check_json_structure(cls, content: str) -> Dict[str, Any]:
        """检查 JSON 文件结构"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {'structure_score': 0, 'should_skip': True, 'skip_reason': 'Invalid JSON'}

        if not isinstance(data, dict):
            return {'structure_score': 0.1, 'should_skip': True, 'skip_reason': 'Not a JSON object'}

        # 提取所有 key
        keys = cls._extract_keys_from_dict(data)

        # 检查敏感关键词
        sensitive_keys = [k for k in keys if any(kw in k.lower() for kw in cls.SENSITIVE_KEYWORDS)]

        # 计算结构分数
        sensitive_ratio = len(sensitive_keys) / len(keys) if keys else 0
        structure_score = min(0.9, 0.3 + sensitive_ratio * 2)

        # 提取敏感部分
        key_sections = {}
        for key in sensitive_keys:
            key_sections[key] = cls._get_nested_value(data, key)

        return {
            'structure_score': structure_score,
            'has_patterns': len(sensitive_keys) >= cls.MIN_SENSITIVE_PATTERNS,
            'sensitive_keys': sensitive_keys,
            'key_sections': key_sections,
            'should_skip': structure_score < 0.3 or len(sensitive_keys) < cls.MIN_SENSITIVE_PATTERNS,
            'skip_reason': f'Low structure score ({structure_score:.2f}) or no sensitive patterns' if structure_score < 0.3 else None,
            'total_keys': len(keys),
            'sensitive_key_count': len(sensitive_keys)
        }

    @classmethod
    def _extract_keys_from_dict(cls, data: Dict, prefix: str = '') -> List[str]:
        """递归提取所有 key"""
        keys = []
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            keys.append(full_key)
            if isinstance(value, dict):
                keys.extend(cls._extract_keys_from_dict(value, full_key))
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        keys.extend(cls._extract_keys_from_dict(item, f"{full_key}[{i}]"))
        return keys

    @classmethod
    def _get_nested_value(cls, data: Dict, key_path: str) -> Any:
        """根据路径获取嵌套值"""
        parts = key_path.split('.')
        value = data
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    @classmethod
    def _check_python_structure(cls, content: str) -> Dict[str, Any]:
        """检查 Python 文件结构"""
        # 查找赋值语句
        assignment_pattern = r'^\s*(\w+)\s*=\s*[\'"]?([^\'"\n]+)[\'"]?\s*(?:#.*)?$'
        assignments = re.findall(assignment_pattern, content, re.MULTILINE)

        # 查找字符串常量
        string_pattern = r'[\'"]([A-Z_]{2,}|[a-z_]*_(?:key|token|password|secret|url))[\'"]'
        strings = re.findall(string_pattern, content, re.IGNORECASE)

        # 查找敏感模式
        sensitive_patterns = []
        for pattern in cls.SENSITIVE_KEYWORDS:
            if re.search(rf'\b{pattern}\b', content, re.IGNORECASE):
                sensitive_patterns.append(pattern)

        # 计算结构分数
        sensitive_count = len(sensitive_patterns) + len([s for s in strings if any(kw in s.lower() for kw in cls.SENSITIVE_KEYWORDS)])
        structure_score = min(0.9, 0.3 + sensitive_count * 0.1)

        # 提取敏感行
        key_sections = {}
        for match in re.finditer(r'.*(?:password|secret|key|token|api_key).*=.*', content, re.IGNORECASE):
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if re.search(r'(?:password|secret|key|token|api_key)', line, re.IGNORECASE):
                    key_sections[f'line_{i}'] = line.strip()

        return {
            'structure_score': structure_score,
            'has_patterns': sensitive_count >= cls.MIN_SENSITIVE_PATTERNS,
            'sensitive_patterns': list(set(sensitive_patterns)),
            'key_sections': key_sections,
            'should_skip': structure_score < 0.3 or sensitive_count < cls.MIN_SENSITIVE_PATTERNS,
            'skip_reason': f'Low structure score ({structure_score:.2f}) or no sensitive patterns' if structure_score < 0.3 else None,
            'assignment_count': len(assignments),
            'sensitive_count': sensitive_count
        }

    @classmethod
    def _check_shell_structure(cls, content: str) -> Dict[str, Any]:
        """检查 Shell 文件结构"""
        # 查找环境变量赋值
        export_pattern = r'export\s+(\w+)='
        exports = re.findall(export_pattern, content)

        # 查找变量赋值
        var_pattern = r'^(\w+)=(?:[\'"]?)([^\'"\n]+)(?:[\'"]?)'
        vars_found = re.findall(var_pattern, content, re.MULTILINE)

        # 查找敏感模式
        sensitive_vars = []
        for var_name, _ in vars_found + [(e, '') for e in exports]:
            if any(kw in var_name.lower() for kw in cls.SENSITIVE_KEYWORDS):
                sensitive_vars.append(var_name)

        # 计算结构分数
        sensitive_count = len(sensitive_vars)
        structure_score = min(0.9, 0.3 + sensitive_count * 0.15)

        # 提取敏感行
        key_sections = {}
        for match in re.finditer(r'^.*(?:password|secret|key|token|api_key)\s*=?\s*[^\n]*', content, re.IGNORECASE | re.MULTILINE):
            key_sections[f'sensitive_var_{len(key_sections)}'] = match.group(0).strip()

        return {
            'structure_score': structure_score,
            'has_patterns': sensitive_count >= cls.MIN_SENSITIVE_PATTERNS,
            'sensitive_vars': sensitive_vars,
            'key_sections': key_sections,
            'should_skip': structure_score < 0.3 or sensitive_count < cls.MIN_SENSITIVE_PATTERNS,
            'skip_reason': f'Low structure score ({structure_score:.2f}) or no sensitive patterns' if structure_score < 0.3 else None,
            'export_count': len(exports),
            'sensitive_count': sensitive_count
        }

    @classmethod
    def _check_javascript_structure(cls, content: str) -> Dict[str, Any]:
        """检查 JavaScript/TypeScript 文件结构"""
        # 查找对象属性
        property_pattern = r'["\']?(\w+)["\']?\s*:'
        properties = re.findall(property_pattern, content)

        # 查找常量定义
        const_pattern = r'(?:const|let|var)\s+(\w+)\s*='
        constants = re.findall(const_pattern, content)

        # 查找敏感模式
        sensitive_patterns = []
        all_names = properties + constants
        for name in all_names:
            if any(kw in name.lower() for kw in cls.SENSITIVE_KEYWORDS):
                sensitive_patterns.append(name)

        # 计算结构分数
        sensitive_count = len(sensitive_patterns)
        structure_score = min(0.9, 0.3 + sensitive_count * 0.12)

        # 提取敏感行
        key_sections = {}
        for match in re.finditer(r'.*(?:password|secret|key|token|api_key)\s*:\s*[^\n]+', content, re.IGNORECASE):
            key_sections[f'sensitive_prop_{len(key_sections)}'] = match.group(0).strip()

        return {
            'structure_score': structure_score,
            'has_patterns': sensitive_count >= cls.MIN_SENSITIVE_PATTERNS,
            'sensitive_patterns': sensitive_patterns,
            'key_sections': key_sections,
            'should_skip': structure_score < 0.3 or sensitive_count < cls.MIN_SENSITIVE_PATTERNS,
            'skip_reason': f'Low structure score ({structure_score:.2f}) or no sensitive patterns' if structure_score < 0.3 else None,
            'property_count': len(properties),
            'sensitive_count': sensitive_count
        }

    @classmethod
    def _check_yaml_structure(cls, content: str) -> Dict[str, Any]:
        """检查 YAML 文件结构（简单实现）"""
        # 查找 key: value 模式
        kv_pattern = r'^(\w+(?:\.\w+)*)\s*:\s*(.+?)\s*$'
        key_values = re.findall(kv_pattern, content, re.MULTILINE)

        # 查找敏感模式
        sensitive_keys = []
        for key, value in key_values:
            if any(kw in key.lower() for kw in cls.SENSITIVE_KEYWORDS):
                sensitive_keys.append(key)

        # 计算结构分数
        sensitive_count = len(sensitive_keys)
        structure_score = min(0.9, 0.3 + sensitive_count * 0.15)

        # 提取敏感行
        key_sections = {}
        for key, value in key_values:
            if any(kw in key.lower() for kw in cls.SENSITIVE_KEYWORDS):
                key_sections[key] = value

        return {
            'structure_score': structure_score,
            'has_patterns': sensitive_count >= cls.MIN_SENSITIVE_PATTERNS,
            'sensitive_keys': sensitive_keys,
            'key_sections': key_sections,
            'should_skip': structure_score < 0.3 or sensitive_count < cls.MIN_SENSITIVE_PATTERNS,
            'skip_reason': f'Low structure score ({structure_score:.2f}) or no sensitive patterns' if structure_score < 0.3 else None,
            'kv_count': len(key_values),
            'sensitive_count': sensitive_count
        }

    @classmethod
    def check_file_structure(cls, file_path: str, content: str) -> Dict[str, Any]:
        """
        检查文件结构，返回是否应该跳过

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            {
                'structure_score': 0-1 之间的分数,
                'has_patterns': 是否包含敏感模式,
                'key_sections': 提取的关键部分,
                'should_skip': 是否应该跳过,
                'skip_reason': 跳过原因,
                ...其他统计信息
            }
        """
        file_type = cls._get_file_type(file_path)

        if file_type == 'json':
            return cls._check_json_structure(content)
        elif file_type in ['yaml', 'yml']:
            return cls._check_yaml_structure(content)
        elif file_type == 'python':
            return cls._check_python_structure(content)
        elif file_type in ['javascript', 'typescript']:
            return cls._check_javascript_structure(content)
        elif file_type in ['shell', 'env', 'sh']:
            return cls._check_shell_structure(content)
        else:
            # 未知文件类型，不过滤
            return {
                'structure_score': 0.5,
                'has_patterns': True,  # 保守策略
                'key_sections': {},
                'should_skip': False,
                'skip_reason': None,
                'file_type': file_type
            }


class SummaryExtractor:
    """
    大文件摘要提取器（三层筛选的第三层）

    作用：
    - 对大文件（>1MB）提取摘要
    - 减少发送给 LLM 的内容
    - 保留关键信息
    """

    @classmethod
    def _extract_json_summary(cls, content: str) -> Dict[str, Any]:
        """提取 JSON 文件摘要"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {'summary': content[:10000], 'truncated': True}

        # 提取敏感 key 的值
        sensitive_items = {}
        for key, value in data.items():
            if any(kw in key.lower() for kw in FileStructureChecker.SENSITIVE_KEYWORDS):
                sensitive_items[key] = str(value)[:500]

        summary = json.dumps(sensitive_items, indent=2)
        return {
            'summary': summary,
            'truncated': len(sensitive_items) < len(data),
            'total_keys': len(data),
            'extracted_keys': len(sensitive_items)
        }

    @classmethod
    def _extract_code_summary(cls, content: str, file_type: str) -> Dict[str, Any]:
        """提取代码文件摘要"""
        lines = content.split('\n')

        # 提取包含敏感关键词的行
        sensitive_lines = []
        for i, line in enumerate(lines):
            if any(kw in line.lower() for kw in FileStructureChecker.SENSITIVE_KEYWORDS):
                # 包含上下文（前后各 2 行）
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                sensitive_lines.extend(lines[start:end])

        # 提取函数/类签名
        if file_type == 'python':
            signatures = re.findall(r'^\s*(?:def|class)\s+\w+', content, re.MULTILINE)
        else:
            signatures = re.findall(r'^\s*(?:function|class|const)\s+\w+', content, re.MULTILINE)

        summary_lines = []
        if signatures:
            summary_lines.append("=== Function/Class Signatures ===")
            summary_lines.extend(signatures[:20])  # 最多 20 个签名
            summary_lines.append("")

        if sensitive_lines:
            summary_lines.append("=== Sensitive Code Sections ===")
            summary_lines.extend(sensitive_lines[:50])  # 最多 50 行

        summary = '\n'.join(summary_lines) if summary_lines else content[:10000]

        return {
            'summary': summary,
            'truncated': len(sensitive_lines) > 50 or len(signatures) > 20,
            'signature_count': len(signatures),
            'sensitive_line_count': len(sensitive_lines)
        }

    @classmethod
    def extract_summary(cls, file_path: str, content: str) -> Dict[str, Any]:
        """
        提取文件摘要

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            {
                'summary': 提取的摘要内容,
                'truncated': 是否被截断,
                'key_sections': 关键部分,
                'statistics': 统计信息
            }
        """
        file_type = FileStructureChecker._get_file_type(file_path)

        if file_type == 'json':
            return cls._extract_json_summary(content)
        elif file_type in ['python', 'javascript', 'typescript', 'shell']:
            return cls._extract_code_summary(content, file_type)
        else:
            # 默认：截取前 10KB
            return {
                'summary': content[:10000],
                'truncated': len(content) > 10000,
                'original_size': len(content),
                'summary_size': min(10000, len(content))
            }


class FileScanResult:
    """单个文件扫描结果"""

    def __init__(
        self,
        file_path: str,
        layer_id: str,
        credentials: List[Dict[str, Any]],
        scan_error: Optional[str] = None,
        structure_check: Optional[Dict[str, Any]] = None,
        summary_used: bool = False
    ):
        self.file_path = file_path
        self.layer_id = layer_id
        self.credentials = credentials
        self.scan_error = scan_error
        self.structure_check = structure_check or {}
        self.summary_used = summary_used
        self.scanned_at = datetime.utcnow()

    @property
    def has_credentials(self) -> bool:
        """是否发现凭证"""
        return len(self.credentials) > 0

    @property
    def success(self) -> bool:
        """扫描是否成功"""
        return self.scan_error is None

    @property
    def was_skipped(self) -> bool:
        """是否被结构预检跳过"""
        return self.structure_check.get('should_skip', False)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "file_path": self.file_path,
            "layer_id": self.layer_id,
            "credentials": self.credentials,
            "has_credentials": self.has_credentials,
            "credential_count": len(self.credentials),
            "scan_error": self.scan_error,
            "was_skipped": self.was_skipped,
            "structure_check": self.structure_check,
            "summary_used": self.summary_used,
            "scanned_at": self.scanned_at.isoformat()
        }


class ContentScanner:
    """
    内容扫描器

    职责：
    1. 读取文件内容
    2. 调用 LLM 扫描敏感凭证
    3. 聚合扫描结果
    4. 追踪扫描进度
    5. 三层筛选：结构预检 + 大文件摘要
    """

    def __init__(self):
        """初始化扫描器"""
        from ..utils.config import get_config
        self.llm_client = get_llm_client()
        self._scanned_files: Dict[str, FileScanResult] = {}

        # 检查是否启用三层筛选
        self.config = get_config()
        self.three_layer_enabled = (
            hasattr(self.config, 'three_layer_filtering') and
            getattr(self.config.three_layer_filtering, 'enabled', False)
        )
        self.structure_check_enabled = self.three_layer_enabled and getattr(
            self.config.three_layer_filtering, 'structure_check_enabled', True
        )
        self.summary_threshold_mb = getattr(
            self.config.three_layer_filtering, 'summary_threshold_mb', 1.0
        )

    async def _read_file_content(self, file_path: str) -> str:
        """
        读取文件内容

        Args:
            file_path: 文件路径

        Returns:
            文件内容

        Raises:
            FileNotFoundError: 文件不存在
            IOError: 读取失败
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 限制文件大小（1MB）
        max_size = 1024 * 1024
        file_size = path.stat().st_size

        if file_size > max_size:
            logger.warning(
                "文件过大，只读取部分内容",
                file_path=file_path,
                file_size=file_size,
                max_size=max_size
            )

        # 读取文件内容
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                # 读取前 max_size 字节
                content = f.read(max_size)
                return content
        except Exception as e:
            logger.error("文件读取失败", file_path=file_path, error=str(e))
            raise IOError(f"无法读取文件 {file_path}: {e}")

    async def scan_file(
        self,
        file_path: str,
        layer_id: str,
        use_cache: bool = True
    ) -> FileScanResult:
        """
        扫描单个文件

        Args:
            file_path: 文件路径
            layer_id: 层 ID
            use_cache: 是否使用缓存

        Returns:
            扫描结果
        """
        # 检查缓存
        cache_key = f"{layer_id}:{file_path}"
        if use_cache and cache_key in self._scanned_files:
            logger.debug("使用缓存的扫描结果", file_path=file_path)
            return self._scanned_files[cache_key]

        logger.debug("开始扫描文件", file_path=file_path, layer_id=layer_id)

        # 初始化统计信息
        structure_check: Dict[str, Any] = {}
        summary_used = False

        try:
            # 读取文件内容
            content = await self._read_file_content(file_path)

            if not content or not content.strip():
                logger.debug("文件为空，跳过扫描", file_path=file_path)
                result = FileScanResult(
                    file_path=file_path,
                    layer_id=layer_id,
                    credentials=[],
                    structure_check=structure_check,
                    summary_used=summary_used
                )
                self._scanned_files[cache_key] = result
                return result

            # 第二层：结构预检（如果启用）
            if self.structure_check_enabled:
                structure_check = FileStructureChecker.check_file_structure(file_path, content)

                if structure_check.get('should_skip'):
                    logger.debug(
                        "结构预检跳过文件",
                        file_path=file_path,
                        reason=structure_check.get('skip_reason'),
                        structure_score=structure_check.get('structure_score')
                    )
                    result = FileScanResult(
                        file_path=file_path,
                        layer_id=layer_id,
                        credentials=[],
                        structure_check=structure_check,
                        summary_used=summary_used
                    )
                    self._scanned_files[cache_key] = result
                    return result

                logger.debug(
                    "结构预检通过",
                    file_path=file_path,
                    structure_score=structure_check.get('structure_score'),
                    has_patterns=structure_check.get('has_patterns')
                )

            # 第三层：大文件摘要提取
            # 检查文件大小
            file_size_mb = Path(file_path).stat().st_size / (1024 * 1024)

            if file_size_mb > self.summary_threshold_mb:
                # 提取摘要
                summary_result = SummaryExtractor.extract_summary(file_path, content)
                content = summary_result['summary']
                summary_used = True

                logger.info(
                    "大文件已提取摘要",
                    file_path=file_path,
                    size_mb=f"{file_size_mb:.2f}",
                    summary_size=len(content)
                )

            # 调用 LLM 扫描
            credentials = await self.llm_client.analyze_file_contents(
                file_path=file_path,
                content=content,
                layer_id=layer_id
            )

            result = FileScanResult(
                file_path=file_path,
                layer_id=layer_id,
                credentials=credentials,
                structure_check=structure_check,
                summary_used=summary_used
            )

            # 缓存结果
            self._scanned_files[cache_key] = result

            if result.has_credentials:
                logger.info(
                    "文件中发现凭证",
                    file_path=file_path,
                    layer_id=layer_id,
                    credential_count=len(credentials)
                )

            return result

        except (FileNotFoundError, IOError) as e:
            logger.warning(
                "文件扫描失败（IO错误）",
                file_path=file_path,
                error=str(e)
            )
            result = FileScanResult(
                file_path=file_path,
                layer_id=layer_id,
                credentials=[],
                scan_error=str(e),
                structure_check=structure_check,
                summary_used=summary_used
            )
            return result

        except LLMClientError as e:
            logger.error(
                "文件扫描失败（LLM错误）",
                file_path=file_path,
                error=str(e)
            )
            result = FileScanResult(
                file_path=file_path,
                layer_id=layer_id,
                credentials=[],
                scan_error=str(e),
                structure_check=structure_check,
                summary_used=summary_used
            )
            return result

    async def scan_multiple_files(
        self,
        files: List[Dict[str, str]],
        max_concurrent: int = 10,
        progress_callback: Optional[callable] = None
    ) -> List[FileScanResult]:
        """
        批量扫描多个文件

        Args:
            files: 文件列表，格式：[{"file_path": "...", "layer_id": "..."}]
            max_concurrent: 最大并发数
            progress_callback: 进度回调函数

        Returns:
            扫描结果列表
        """
        logger.info(
            "开始批量扫描文件",
            file_count=len(files),
            max_concurrent=max_concurrent
        )

        # 创建信号量限制并发
        semaphore = asyncio.Semaphore(max_concurrent)

        total_files = len(files)
        completed_count = 0

        async def scan_single(file_info: Dict[str, str]):
            nonlocal completed_count

            async with semaphore:
                result = await self.scan_file(
                    file_info["file_path"],
                    file_info["layer_id"]
                )

                completed_count += 1

                # 调用进度回调
                if progress_callback:
                    await progress_callback(completed_count, total_files, result)

                return result

        # 并发执行
        tasks = [scan_single(f) for f in files]
        results = await asyncio.gather(*tasks)

        # 统计
        successful_scans = sum(1 for r in results if r.success)
        files_with_credentials = sum(1 for r in results if r.has_credentials)
        total_credentials = sum(len(r.credentials) for r in results)

        logger.info(
            "批量扫描完成",
            total_files=total_files,
            successful=successful_scans,
            with_credentials=files_with_credentials,
            total_credentials=total_credentials
        )

        return results

    def aggregate_results(
        self,
        scan_results: List[FileScanResult]
    ) -> Dict[str, Any]:
        """
        聚合扫描结果

        Args:
            scan_results: 扫描结果列表

        Returns:
            聚合统计
        """
        all_credentials: List[Dict[str, Any]] = []

        for result in scan_results:
            if result.has_credentials:
                all_credentials.extend(result.credentials)

        # 按置信度分组
        high_conf = [c for c in all_credentials if c.get("confidence", 0) >= 0.8]
        medium_conf = [c for c in all_credentials if 0.5 <= c.get("confidence", 0) < 0.8]
        low_conf = [c for c in all_credentials if c.get("confidence", 0) < 0.5]

        # 按类型分组
        by_type: Dict[str, int] = {}
        for cred in all_credentials:
            cred_type = cred.get("cred_type", "UNKNOWN")
            by_type[cred_type] = by_type.get(cred_type, 0) + 1

        # 按层分组
        by_layer: Dict[str, int] = {}
        for cred in all_credentials:
            layer_id = cred.get("layer_id", "unknown")
            by_layer[layer_id] = by_layer.get(layer_id, 0) + 1

        aggregation = {
            "total_credentials": len(all_credentials),
            "by_confidence": {
                "high": len(high_conf),
                "medium": len(medium_conf),
                "low": len(low_conf)
            },
            "by_type": by_type,
            "by_layer": by_layer,
            "files_scanned": len(scan_results),
            "files_with_credentials": sum(1 for r in scan_results if r.has_credentials)
        }

        logger.info(
            "结果聚合完成",
            total_credentials=aggregation["total_credentials"],
            files_with_credentials=aggregation["files_with_credentials"]
        )

        return aggregation

    def convert_to_credential_models(
        self,
        scan_results: List[FileScanResult],
        task_id: str
    ) -> List[Credential]:
        """
        将扫描结果转换为凭证模型

        Args:
            scan_results: 扫描结果列表
            task_id: 任务 ID

        Returns:
            凭证模型列表
        """
        credentials: List[Credential] = []

        for result in scan_results:
            if not result.has_credentials:
                continue

            for cred_data in result.credentials:
                try:
                    # 映射凭证类型
                    cred_type_str = cred_data.get("cred_type", "UNKNOWN")
                    try:
                        cred_type = CredentialType[cred_type_str]
                    except KeyError:
                        cred_type = CredentialType.UNKNOWN

                    # 创建凭证模型
                    credential = Credential(
                        task_id=task_id,
                        cred_type=cred_type,
                        confidence=cred_data.get("confidence", 0.0),
                        file_path=cred_data.get("file_path", result.file_path),
                        line_number=cred_data.get("line_number"),
                        layer_id=cred_data.get("layer_id", result.layer_id),
                        context=cred_data.get("context", ""),
                        raw_value=cred_data.get("raw_value"),
                        validation_status=ValidationStatus.PENDING,
                        metadata=cred_data.get("metadata", {})
                    )

                    credentials.append(credential)

                except Exception as e:
                    logger.warning(
                        "凭证模型转换失败",
                        file_path=result.file_path,
                        error=str(e)
                    )

        logger.info(
            "凭证模型转换完成",
            input_count=sum(len(r.credentials) for r in scan_results),
            output_count=len(credentials)
        )

        return credentials

    def get_scan_stats(self) -> Dict[str, Any]:
        """获取扫描统计"""
        cached_results = list(self._scanned_files.values())

        return {
            "cached_files": len(cached_results),
            "files_with_credentials": sum(1 for r in cached_results if r.has_credentials),
            "total_credentials_found": sum(len(r.credentials) for r in cached_results)
        }

    def clear_cache(self):
        """清除缓存"""
        self._scanned_files.clear()
        logger.debug("清除扫描缓存")


# 全局内容扫描器实例（延迟加载）
_global_scanner: Optional[ContentScanner] = None


def get_content_scanner() -> ContentScanner:
    """
    获取全局内容扫描器实例（单例模式）

    Returns:
        内容扫描器实例
    """
    global _global_scanner
    if _global_scanner is None:
        _global_scanner = ContentScanner()
    return _global_scanner
