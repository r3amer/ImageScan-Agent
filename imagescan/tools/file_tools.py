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
import tarfile
from pathlib import Path
from typing import List

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


@registry.register("file.list_layer_files")
async def file_list_layer_files(layer_tar_path: str) -> List[str]:
    """
    列出层中的所有文件

    Args:
        layer_tar_path: 层 tar 文件路径

    Returns:
        files: 文件路径列表

    示例:
        >>> files = await file_list_layer_files("./tmp/layer.tar")
        >>> print(f"Total files: {len(files)}")
    """
    logger.debug("列出层文件", layer=layer_tar_path)

    try:
        # 使用线程池读取文件列表（IO 密集型）
        def _list_files():
            with tarfile.open(layer_tar_path) as tar:
                return tar.getnames()

        files = await asyncio.to_thread(_list_files)

        logger.debug("文件列表获取成功",
                    layer=layer_tar_path,
                    count=len(files))
        return files

    except Exception as e:
        logger.error("列出文件失败", error=str(e))
        raise FileReadError(f"Failed to list files: {e}")


@registry.register("file.extract_from_layer")
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


@registry.register("file.read_content")
async def file_read_content(file_path: str) -> str:
    """
    读取文件内容

    Args:
        file_path: 文件路径

    Returns:
        content: 文件内容

    Raises:
        FileReadError: 读取失败

    示例:
        >>> content = await file_read_content("./files/config.json")
        >>> print(content[:100])  # 前 100 个字符
    """
    logger.debug("读取文件内容", file=file_path)

    try:
        async with aiofiles.open(file_path, mode='r') as f:
            content = await f.read()

        logger.debug("文件读取成功",
                    file=file_path,
                    size=len(content))
        return content

    except Exception as e:
        logger.error("读取文件失败", file=file_path, error=str(e))
        raise FileReadError(f"Failed to read file: {e}")


@registry.register("file.read_binary")
async def file_read_binary(file_path: str) -> bytes:
    """
    读取二进制文件内容

    Args:
        file_path: 文件路径

    Returns:
        content: 文件内容（字节）

    示例:
        >>> content = await file_read_binary("./files/certificate.pem")
    """
    logger.debug("读取二进制文件", file=file_path)

    try:
        async with aiofiles.open(file_path, mode='rb') as f:
            content = await f.read()

        logger.debug("二进制文件读取成功",
                    file=file_path,
                    size=len(content))
        return content

    except Exception as e:
        logger.error("读取二进制文件失败",
                    file=file_path,
                    error=str(e))
        raise FileReadError(f"Failed to read binary file: {e}")


@registry.register("file.exists")
def file_exists(file_path: str) -> bool:
    """
    检查文件是否存在

    Args:
        file_path: 文件路径

    Returns:
        是否存在
    """
    return Path(file_path).exists()


@registry.register("file.get_size")
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


@registry.register("file.filter_paths")
def file_filter_paths(
    file_paths: List[str],
    prefix_exclude: List[str],
    keywords_exclude: List[str]
) -> List[str]:
    """
    过滤文件路径

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


# 便捷函数：获取文件扩展名
def get_file_extension(file_path: str) -> str:
    """
    获取文件扩展名

    Args:
        file_path: 文件路径

    Returns:
        扩展名（如 ".json", ".txt"）
    """
    return Path(file_path).suffix


# 便捷函数：判断是否为文本文件
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


# 便捷函数：格式化文件大小
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
