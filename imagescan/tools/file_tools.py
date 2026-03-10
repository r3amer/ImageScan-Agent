"""
文件操作工具模块

用途：
1. 列出层中的所有文件
2. 从层中提取文件
3. 读取文件内容
4. 过滤文件路径

参考：docs/APP_FLOW.md（工具调用详解）
"""

import asyncio
import os
import tarfile
from pathlib import Path
from typing import List, Dict, Optional, Any

import aiofiles

from .registry import registry
from ..utils.logger import get_logger

logger = get_logger(__name__)


# 自定义异常类
class LayerFileNotFound(Exception):
    """层文件不存在异常"""
    pass


class FileReadError(Exception):
    """读取文件失败异常"""
    pass

@registry.register(
    "file.extract_from_layer",
    description="从层 tar 包中提取文件到本地文件系统。参数：layer_tar_path(层 tar 文件路径), file_path(文件在层中的路径), output_path(输出目录路径)。返回：提取后的本地文件路径字符串"
)
async def file_extract_from_layer(
    layer_tar_path: str,
    file_path: str,
    output_path: str
) -> str:
    """
    从层中提取单个文件

    Args:
        layer_tar_path: 层 tar 文件路径
        file_path: 文件在层中的路径
        output_path: 输出目录路径

    Returns:
        extracted_path: 提取后的文件路径

    示例:
        >>> extracted = await file_extract_from_layer(
        ...     "./tmp/sha256_abc.tar",
        ...     "app/config.json",
        ...     "./files"
        ... )
        >>> print(extracted)  # "./files/app/config.json"
    """
    logger.debug("从层提取文件", layer=layer_tar_path, file=file_path)

    try:
        with tarfile.open(layer_tar_path) as tar:
            # 检查文件是否存在
            try:
                member = tar.getmember(file_path)
            except KeyError:
                logger.error("文件不存在于层中", file=file_path)
                raise LayerFileNotFound(
                    f"File not found in layer: {file_path}"
                )

            # 确保输出目录存在
            output_file = Path(output_path) / file_path
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # 提取文件（IO 密集型，使用线程池）
            await asyncio.to_thread(
                lambda: tar.extract(member, output_path)
            )

            extracted_path = str(output_file)
            logger.debug("文件提取成功", path=extracted_path)
            return extracted_path

    except LayerFileNotFound:
        raise
    except Exception as e:
        logger.error("提取文件失败", error=str(e))
        raise FileReadError(f"Failed to extract file: {e}")


@registry.register(
    "file.exists",
    description="检查文件是否存在。参数：file_path(文件路径)。返回：布尔值，true 表示存在"
)
def file_exists(file_path: str) -> bool:
    """
    检查文件是否存在

    Args:
        file_path: 文件路径

    Returns:
        是否存在
    """
    return Path(file_path).exists()


@registry.register(
    "file.get_size",
    description="获取文件大小。参数：file_path(文件路径)。返回：文件大小（字节数）"
)
def file_get_size(file_path: str) -> int:
    """
    获取文件大小

    Args:
        file_path: 文件路径

    Returns:
        文件大小（字节）
    """
    try:
        return Path(file_path).stat().st_size
    except FileNotFoundError:
        return 0


# ========== 内部函数（不注册为工具）==========

async def _read_file_content(file_path: str) -> Optional[str]:
    """
    内部函数：读取文件内容（不注册为工具）

    Args:
        file_path: 文件路径

    Returns:
        文件内容，读取失败返回 None
    """
    try:
        async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='ignore') as f:
            return await f.read()
    except Exception as e:
        logger.warning("读取文件失败", file=file_path, error=str(e))
        return None


async def _read_binary_file(file_path: str) -> Optional[bytes]:
    """
    内部函数：读取二进制文件（不注册为工具）

    Args:
        file_path: 文件路径

    Returns:
        文件内容（字节），读取失败返回 None
    """
    try:
        async with aiofiles.open(file_path, mode='rb') as f:
            return await f.read()
    except Exception as e:
        logger.warning("读取二进制文件失败", file=file_path, error=str(e))
        return None


# ========== 工具：分析文件内容 ==========

@registry.register(
    "file.analyze_contents",
    description="分析文件内容中的敏感凭证。参数：file_paths(本地文件路径列表), layer_id(可选的层ID)。返回：包含 success, data, summary 的字典，其中 data 是 {文件路径: [{凭证信息}], ...}，每个凭证包含 cred_type, confidence, context, line_number, raw_value"
)
async def file_analyze_contents(
    file_paths: List[str],
    layer_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    分析文件内容中的敏感凭证（隔离上下文）

    这是隔离上下文的关键工具：每个文件独立调用 LLM 分析，
    结果直接返回凭证信息，不污染主对话上下文。

    所有业务逻辑在此函数中完成。

    Args:
        file_paths: 文件路径列表
        layer_id: 层 ID（可选）

    Returns:
        {
            "success": True,
            "data": {
                "file_path1": [
                    {
                        "cred_type": "API_KEY",
                        "confidence": 0.95,
                        "context": "API_KEY=sk-1234567890",
                        "line_number": 10,
                        "raw_value": "sk-1234567890",
                        "metadata": {}
                    }
                ],
                "file_path2": []
            },
            "summary": ["✅ 文件内容分析完成", "  扫描文件数: 2", ...]
        }

    示例:
        >>> result = await file_analyze_contents(["./files/.env", "./files/config.json"], "sha256:abc")
        >>> print(result["summary"])  # "✅ 文件内容分析完成..."
    """
    from ..core.llm_client import get_llm_client

    logger.info("开始分析文件内容", file_count=len(file_paths), layer_id=layer_id)

    llm_client = get_llm_client()
    results = {}
    stats = {
        "total_files": len(file_paths),
        "successful": 0,
        "failed": 0,
        "total_credentials": 0
    }

    for file_path in file_paths:
        # 读取文件内容（内部调用，不注册为工具）
        content = await _read_file_content(file_path)

        if content is None:
            stats["failed"] += 1
            results[file_path] = []
            continue

        try:
            # 业务逻辑：限制内容长度（避免 token 超限）
            max_length = 100000# 12000
            if len(content) > max_length:
                content = content[:max_length] + "\n... (内容已截断)"
                logger.warning(
                    "文件内容过长，进行截断",
                    file_path=file_path,
                    original_length=len(content),
                    truncated=max_length
                )

            # 业务逻辑：构建 prompt
            prompt = f"""分析以下文件内容，检测其中的敏感凭证和危险配置。

文件路径：{file_path}

文件内容：
```
{content}
```

请返回 JSON 格式：
{{
    "credentials": [
        {{
            "cred_type": "凭证类型（API_KEY/PASSWORD/TOKEN/CERTIFICATE/PRIVATE_KEY/DATABASE_URL/AWS_KEY/SSH_KEY/UNKNOWN）",
            "confidence": 置信度（0.0-1.0的浮点数）,
            "context": "包含凭证的上下文（截取关键部分，不超过200字符）",
            "line_number": 行号（如果可以推断）,
            "raw_value": "原始凭证值（如果可能提取，否则为null）",
            "metadata": {{
                "additional_info": "其他补充信息"
            }}
        }}
    ]
}}

规则：
- 只报告真正可能包含敏感凭证的内容
- 如果没有发现敏感凭证，返回空数组 []
- 对于已脱敏的内容（如 ***、******），不要报告
- 对于明显的示例文本（如 your_api_key_here），不要报告
- 置信度应该基于格式匹配和上下文判断
- 如果能提取原始凭证值，填写 raw_value（否则为 null）"""

            # 调用 LLM（使用通用方法）
            llm_result = await llm_client.think(prompt, temperature=0.0)

            # 业务逻辑：验证返回格式并添加文件路径信息
            raw_credentials = llm_result.get("credentials", [])

            # 验证凭证：只保留有效的凭证（必须有 context 或 raw_value）
            credentials = []
            for cred in raw_credentials:
                # 跳过无效凭证：context 和 raw_value 都为空
                if not cred.get("context") and not cred.get("raw_value"):
                    logger.debug(
                        "跳过无效凭证（无上下文）",
                        file=file_path,
                        cred_type=cred.get("cred_type", "UNKNOWN")
                    )
                    continue

                # 跳过低置信度凭证（confidence <= 0）
                if cred.get("confidence", 0) <= 0:
                    logger.debug(
                        "跳过低置信度凭证",
                        file=file_path,
                        confidence=cred.get("confidence", 0)
                    )
                    continue

                # 添加文件路径信息
                cred["file_path"] = file_path
                if "layer_id" not in cred:
                    cred["layer_id"] = layer_id

                credentials.append(cred)

            results[file_path] = credentials
            stats["successful"] += 1
            stats["total_credentials"] += len(credentials)

            if credentials:
                logger.info(
                    "发现凭证",
                    file=file_path,
                    count=len(credentials),
                    types=[c.get("cred_type") for c in credentials]
                )

        except Exception as e:
            logger.error("分析文件失败", file=file_path, error=str(e))
            stats["failed"] += 1
            results[file_path] = []

    logger.info(
        "文件内容分析完成",
        stats=stats
    )

    return {
        "success": True,
        "data": results,
        "summary": [
            f"✅ 文件内容分析完成",
            f"  扫描文件数: {stats['total_files']}",
            f"  成功分析: {stats['successful']}",
            f"  分析失败: {stats['failed']}",
            f"  发现凭证数: {stats['total_credentials']}"
        ]
    }


# ========== 工具：过滤路径 ==========

# @registry.register(
#     "file.filter_paths",
#     description="过滤文件路径列表。参数：file_paths(文件路径列表), prefix_exclude(排除的路径前缀列表), keywords_exclude(排除的关键词列表)。返回：过滤后的文件路径列表"
# )
def file_filter_paths(
    file_paths: List[str],
    prefix_exclude: List[str],
    keywords_exclude: List[str]
) -> List[str]:
    """
    过滤文件路径列表

    Args:
        file_paths: 文件路径列表
        prefix_exclude: 排除的路径前缀
        keywords_exclude: 排除的关键词

    Returns:
        过滤后的文件路径列表

    示例:
        >>> files = ["/usr/bin/nginx", "/app/config.json"]
        >>> filtered = file_filter_paths(
        ...     files,
        ...     prefix_exclude=["/usr", "/lib"],
        ...     keywords_exclude=[".git"]
        ... )
        >>> print(filtered)  # ["/app/config.json"]
    """
    result = []

    for file_path in file_paths:
        # 检查前缀排除
        excluded = False
        for prefix in prefix_exclude:
            if file_path.startswith(prefix):
                excluded = True
                break

        if excluded:
            continue

        # 检查关键词排除
        for keyword in keywords_exclude:
            if keyword in file_path:
                excluded = True
                break

        if excluded:
            continue

        # 通过所有过滤条件
        result.append(file_path)

    logger.debug("文件过滤完成",
                total=len(file_paths),
                filtered_out=len(file_paths) - len(result),
                remaining=len(result))

    return result


# ========== 工具：清理临时文件 ==========

# @registry.register(
#     "file.cleanup_temp_files",
#     description="清理临时文件，但保留凭证文件。参数：temp_dir(临时文件目录), preserve_paths(要保留的文件路径列表)。返回：删除的文件数量，保留的文件数量"
# )
def file_cleanup_temp_files(
    temp_dir: str,
    preserve_paths: List[str]
) -> Dict[str, int]:
    """
    清理临时文件，保留凭证文件

    Args:
        temp_dir: 临时文件目录路径
        preserve_paths: 要保留的文件路径列表（凭证文件）

    Returns:
        清理统计：{"deleted": 删除数量, "preserved": 保留数量}

    示例:
        >>> stats = file_cleanup_temp_files(
        ...     "./output/temp_files",
        ...     ["./output/temp_files/etc/config.json", "./output/temp_files/.env"]
        ... )
        >>> print(stats)  # {"deleted": 98, "preserved": 2}
    """
    logger.info("开始清理临时文件", temp_dir=temp_dir, preserve_count=len(preserve_paths))

    temp_path = Path(temp_dir)

    if not temp_path.exists():
        logger.warning("临时目录不存在", temp_dir=temp_dir)
        return {"deleted": 0, "preserved": 0}

    # 标准化保留路径
    preserve_set = set()
    for p in preserve_paths:
        try:
            preserve_set.add(Path(p).resolve())
        except Exception:
            logger.warning("无法解析保留路径", path=p)
            continue

    deleted_count = 0
    preserved_count = 0
    errors = []

    # 遍历临时目录下的所有文件
    for root, dirs, files in os.walk(temp_path):
        for filename in files:
            file_path = Path(root) / filename

            try:
                # 检查是否在保留列表中
                if file_path.resolve() in preserve_set:
                    preserved_count += 1
                    logger.debug("保留文件", file=str(file_path))
                else:
                    # 删除文件
                    file_path.unlink()
                    deleted_count += 1
                    logger.debug("删除临时文件", file=str(file_path))

            except Exception as e:
                logger.error("删除文件失败", file=str(file_path), error=str(e))
                errors.append(str(file_path))

    # 尝试删除空目录
    try:
        for root, dirs, files in os.walk(temp_path, topdown=False):
            for dirname in dirs:
                dir_path = Path(root) / dirname
                try:
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        logger.debug("删除空目录", dir=str(dir_path))
                except Exception:
                    pass  # 目录非空或其他错误，忽略
    except Exception as e:
        logger.warning("清理空目录时出错", error=str(e))

    logger.info(
        "清理完成",
        deleted=deleted_count,
        preserved=preserved_count,
        errors=len(errors)
    )

    if errors:
        logger.warning("部分文件删除失败", count=len(errors))

    return {
        "deleted": deleted_count,
        "preserved": preserved_count,
        "errors": len(errors)
    }


# ========== 便捷函数 ==========

def get_file_extension(file_path: str) -> str:
    """
    获取文件扩展名

    Args:
        file_path: 文件路径

    Returns:
        扩展名（如 ".json", ".txt"）
    """
    return Path(file_path).suffix


def is_text_file(file_path: str) -> bool:
    """
    判断是否为文本文件

    Args:
        file_path: 文件路径

    Returns:
        是否为文本文件
    """
    text_extensions = {
        '.txt', '.json', '.xml', '.yaml', '.yml',
        '.py', '.js', '.sh', '.conf', '.config',
        '.env', '.ini', '.cfg', '.md'
    }
    return Path(file_path).suffix in text_extensions


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小

    Args:
        size_bytes: 字节数

    Returns:
        格式化的字符串
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"
