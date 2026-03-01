"""
Tar 工具模块

用途：
1. 解压 tar 文件
2. 读取 manifest.json
3. 获取层信息

参考：docs/APP_FLOW.md（工具调用详解）
"""

import asyncio
import json
import tarfile
from pathlib import Path
from typing import Dict, Any, List

from .registry import registry
from ..utils.logger import get_logger

logger = get_logger(__name__)


# 自定义异常类
class TarFileNotFound(Exception):
    """tar 文件不存在异常"""
    pass


class TarUnpackError(Exception):
    """解压 tar 失败异常"""
    pass


class ManifestNotFoundError(Exception):
    """manifest.json 不存在异常"""
    pass


@registry.register("tar.unpack")
async def tar_unpack(
    tar_path: str,
    extract_path: str
) -> Dict[str, Any]:
    """
    解压 tar 文件

    Args:
        tar_path: tar 文件路径
        extract_path: 解压目标路径

    Returns:
        manifest: manifest.json 内容

    Raises:
        TarFileNotFound: tar 文件不存在
        TarUnpackError: 解压失败
        ManifestNotFoundError: manifest.json 不存在

    示例:
        >>> manifest = await tar_unpack(
        ...     "./image_tar/nginx_latest.tar",
        ...     "./tmp/nginx_latest"
        ... )
        >>> print(f"Layers: {len(manifest['Layers'])}")
    """
    logger.info("解压 tar 文件", tar=tar_path, output=extract_path)

    # 检查 tar 文件是否存在
    tar_file = Path(tar_path)
    if not tar_file.exists():
        logger.error("tar 文件不存在", path=tar_path)
        raise TarFileNotFound(f"tar file not found: {tar_path}")

    # 确保目标目录存在
    Path(extract_path).mkdir(parents=True, exist_ok=True)

    try:
        # 解压 tar 文件（IO 密集型，使用线程池）
        await asyncio.to_thread(
            lambda: tarfile.open(tar_path).extractall(extract_path)
        )

        logger.info("tar 解压成功", path=extract_path)

    except Exception as e:
        logger.error("解压 tar 失败", error=str(e))
        raise TarUnpackError(f"Failed to unpack tar: {e}")

    # 读取 manifest.json
    manifest_path = Path(extract_path) / "manifest.json"
    if not manifest_path.exists():
        logger.error("manifest.json 不存在", path=manifest_path)
        raise ManifestNotFoundError(
            f"manifest.json not found in {extract_path}"
        )

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)

        # 处理两种格式：
        # 1. 列表格式（某些 Docker 版本）
        # 2. 字典格式（OCI 标准）
        if isinstance(manifest, list):
            # 列表格式：manifest[0]["Layers"] 或 manifest[0]["layers"]
            first_manifest = manifest[0] if manifest else {}
            layers_data = first_manifest.get("Layers", first_manifest.get("layers", []))
            logger.info("manifest.json 加载成功", layers=len(layers_data))
        else:
            # 字典格式：manifest["Layers"]
            logger.info("manifest.json 加载成功", layers=len(manifest.get("Layers", [])))

        return manifest

    except json.JSONDecodeError as e:
        logger.error("manifest.json 解析失败", error=str(e))
        raise TarUnpackError(f"Failed to parse manifest.json: {e}")


@registry.register("tar.list_layers")
def tar_list_layers(tar_path: str) -> List[Dict[str, Any]]:
    """
    列出 tar 文件中的所有层（不解压）

    Args:
        tar_path: tar 文件路径

    Returns:
        层信息列表

    示例:
        >>> layers = tar_list_layers("./image_tar/nginx_latest.tar")
        >>> for layer in layers:
        ...     print(f"Layer: {layer['digest']}")
    """
    logger.debug("列出 tar 层", tar=tar_path)

    try:
        with tarfile.open(tar_path) as tar:
            # 查找 manifest.json
            manifest_member = None
            for member in tar.getmembers():
                if member.name.endswith("manifest.json"):
                    manifest_member = member
                    break

            if not manifest_member:
                raise ManifestNotFoundError("manifest.json not found in tar")

            # 读取并解析 manifest.json
            f = tar.extractfile(manifest_member)
            manifest = json.loads(f.read().decode("utf-8"))

            # 处理两种格式：
            # 1. 列表格式（某些 Docker 版本）
            # 2. 字典格式（OCI 标准）
            if isinstance(manifest, list):
                # 列表格式：manifest[0]["Layers"] 或 manifest[0]["layers"]
                first_manifest = manifest[0] if manifest else {}
                layer_list = first_manifest.get("Layers", first_manifest.get("layers", []))
            else:
                # 字典格式：manifest["Layers"]
                layer_list = manifest.get("Layers", [])

            # 提取层信息
            layers = []
            for layer_data in layer_list:
                layers.append({
                    "layer_id": layer_data,  # 使用 layer_id 而不是 digest
                    "size": 0  # 需要解压后才能获取大小
                })

            logger.debug("层列表获取成功", count=len(layers))
            return layers

    except Exception as e:
        logger.error("列出层失败", error=str(e))
        raise TarUnpackError(f"Failed to list layers: {e}")


@registry.register("tar.extract_file")
async def tar_extract_file(
    tar_path: str,
    member_path: str,
    output_path: str
) -> str:
    """
    从 tar 文件中提取单个文件

    Args:
        tar_path: tar 文件路径
        member_path: 文件在 tar 中的路径
        output_path: 输出目录路径

    Returns:
        extracted_path: 提取后的文件路径

    示例:
        >>> file_path = await tar_extract_file(
        ...     "./tmp/layer.tar",
        ...     "usr/bin/nginx",
        ...     "./files"
        ... )
        >>> # 返回: "./files/usr/bin/nginx"
    """
    logger.debug("从 tar 提取文件",
                tar=tar_path,
                file=member_path)

    try:
        with tarfile.open(tar_path) as tar:
            # 获取成员
            member = tar.getmember(member_path)

            # 确保输出目录存在
            output_file = Path(output_path) / member_path
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # 提取文件（IO 密集型，使用线程池）
            await asyncio.to_thread(
                lambda: tar.extract(member, output_path)
            )

            logger.debug("文件提取成功", path=str(output_file))
            return str(output_file)

    except KeyError:
        logger.error("文件不存在于 tar 中", file=member_path)
        raise TarFileNotFound(f"File not found in tar: {member_path}")
    except Exception as e:
        logger.error("提取文件失败", error=str(e))
        raise TarUnpackError(f"Failed to extract file: {e}")


@registry.register("tar.list_layer_files")
def tar_list_layer_files(layer_tar_path: str) -> List[str]:
    """
    列出层 tar 文件中的所有文件（不解压）

    Args:
        layer_tar_path: 层 tar 文件路径

    Returns:
        文件名列表

    示例:
        >>> filenames = tar_list_layer_files("./tmp/abc123/layer.tar")
        >>> print(f"Found {len(filenames)} files")
    """
    logger.debug("列出层文件", tar=layer_tar_path)

    try:
        filenames = []
        with tarfile.open(layer_tar_path, "r") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    name = member.name
                    # 标准化路径（移除 ./ 前缀）
                    if name.startswith('./'):
                        name = name[2:]
                    filenames.append(name)

        logger.debug("层文件列表获取成功", count=len(filenames))
        return filenames

    except Exception as e:
        logger.error("列出层文件失败", error=str(e))
        raise TarUnpackError(f"Failed to list layer files: {e}")


# 便捷函数：获取层大小
def get_layer_size(layer_tar_path: str) -> int:
    """
    获取层 tar 文件的大小

    Args:
        layer_tar_path: 层 tar 文件路径

    Returns:
        文件大小（字节）
    """
    return Path(layer_tar_path).stat().st_size


# 便捷函数：格式化大小
def format_size(size_bytes: int) -> str:
    """
    格式化文件大小

    Args:
        size_bytes: 字节数

    Returns:
        格式化的字符串（如 "128.5 MB"）
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"
