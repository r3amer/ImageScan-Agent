"""
Docker 工具模块

用途：
1. 保存 Docker 镜像为 tar 文件
2. 检查镜像是否存在
3. 获取镜像信息

注意：使用 docker CLI 而非 Docker SDK，避免连接问题

参考：docs/APP_FLOW.md（工具调用详解）
"""

import asyncio
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from .registry import registry
from ..utils.logger import get_logger

logger = get_logger(__name__)


# 自定义异常类
class DockerImageNotFound(Exception):
    """镜像不存在异常"""
    pass


class DockerSaveError(Exception):
    """保存镜像失败异常"""
    pass


class DockerCommandError(Exception):
    """Docker 命令执行失败异常"""
    pass


async def _run_docker_command(
    args: List[str],
    check: bool = True,
    capture: bool = True
) -> subprocess.CompletedProcess:
    """
    运行 docker 命令

    Args:
        args: 命令参数列表
        check: 是否检查返回码
        capture: 是否捕获输出

    Returns:
        CompletedProcess 对象

    Raises:
        DockerCommandError: 命令执行失败
    """
    cmd = ["docker"] + args
    logger.debug("执行 docker 命令", cmd=" ".join(cmd))

    try:
        # 使用线程池执行（同步命令）
        process = await asyncio.to_thread(
            subprocess.run,
            cmd,
            check=check,
            capture_output=capture,
            text=True
        )

        logger.debug("命令执行完成", returncode=process.returncode)
        return process

    except subprocess.CalledProcessError as e:
        logger.error("docker 命令失败",
                     cmd=" ".join(cmd),
                     returncode=e.returncode,
                     stderr=e.stderr)
        raise DockerCommandError(
            f"Docker command failed: {e.stderr if e.stderr else str(e)}"
        )
    except FileNotFoundError:
        logger.error("docker 命令未找到")
        raise DockerCommandError("docker command not found. Please install Docker.")


@registry.register(
    "docker.save",
    description="保存 Docker 镜像为 tar 文件。参数：image_name(镜像名称), output_path(输出目录)。返回：包含 success, data, summary 的字典"
)
async def docker_save(
    image_name: str,
    output_path: str
) -> Dict[str, Any]:
    """
    保存 Docker 镜像为 tar 文件

    Args:
        image_name: 镜像名称（如 "nginx:latest"）
        output_path: 输出目录路径

    Returns:
        {
            "success": True,
            "data": {"tar_path": "...", "size_mb": "..."},
            "summary": "✅ 镜像已保存：./path/to/file.tar (123.45 MB)"
        }

    Raises:
        DockerImageNotFound: 镜像不存在
        DockerSaveError: 保存失败

    示例:
        >>> result = await docker_save("nginx:latest", "./image_tar")
        >>> print(result["summary"])
    """
    logger.info("保存 Docker 镜像", image=image_name, output=output_path)

    # 检查镜像是否存在
    if not await docker_exists(image_name):
        logger.error("镜像不存在", image=image_name)
        return {
            "success": False,
            "error": f"镜像 '{image_name}' 不存在，请先拉取：docker pull {image_name}",
            "summary": f"❌ 镜像不存在，需要先拉取"
        }

    # 确保输出目录存在
    Path(output_path).mkdir(parents=True, exist_ok=True)

    # 构建输出文件名（替换特殊字符）
    safe_name = image_name.replace(":", "_").replace("/", "_")
    tar_path = f"{output_path}/{safe_name}.tar"

    # 执行 docker save 命令
    try:
        await _run_docker_command(
            ["save", "-o", tar_path, image_name],
            check=True
        )

        # 检查文件是否创建成功
        if not Path(tar_path).exists():
            return {
                "success": False,
                "error": f"tar 文件未创建：{tar_path}",
                "summary": f"❌ 镜像保存失败"
            }

        # 获取文件大小
        file_size = Path(tar_path).stat().st_size
        size_mb = f"{file_size / 1024 / 1024:.2f}"

        logger.info("镜像保存成功", path=tar_path, size=size_mb)

        return {
            "success": True,
            "data": {"tar_path": tar_path, "size_mb": size_mb},
            "summary": f"✅ 镜像已保存：{tar_path} ({size_mb} MB)"
        }

    except DockerCommandError as e:
        logger.error("保存镜像失败", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "summary": f"❌ 镜像保存失败：{str(e)}"
        }


@registry.register(
    "docker.exists",
    description="检查 Docker 镜像是否存在于本地。参数：image_name(镜像名称)。返回：包含 success, data, summary 的字典"
)
async def docker_exists(image_name: str) -> Dict[str, Any]:
    """
    检查 Docker 镜像是否存在

    Args:
        image_name: 镜像名称

    Returns:
        {
            "success": True,
            "data": {"exists": true},
            "summary": "✅ 镜像存在，可以直接保存"
        }

    示例:
        >>> result = await docker_exists("nginx:latest")
        >>> print(result["summary"])
    """
    try:
        process = await _run_docker_command(
            ["inspect", "--type", "image", image_name],
            check=False
        )
        exists = process.returncode == 0

        if exists:
            return {
                "success": True,
                "data": {"exists": True},
                "summary": "✅ 镜像存在，可以直接保存"
            }
        else:
            return {
                "success": True,
                "data": {"exists": False},
                "summary": "❌ 镜像不存在，需要先拉取"
            }

    except DockerCommandError:
        return {
            "success": False,
            "error": "检查镜像失败",
            "summary": "❌ 检查镜像失败"
        }


@registry.register(
    "docker.inspect",
    description="获取 Docker 镜像的详细信息。参数：image_name(镜像名称)。返回：包含镜像元数据的字典（id、tags、size、layers 等）"
)
async def docker_inspect(image_name: str) -> Dict[str, Any]:
    """
    获取 Docker 镜像详细信息

    Args:
        image_name: 镜像名称

    Returns:
        镜像信息字典

    Raises:
        DockerImageNotFound: 镜像不存在

    示例:
        >>> info = await docker_inspect("nginx:latest")
        >>> print(f"ID: {info['id']}")
    """
    try:
        process = await _run_docker_command(
            ["inspect", "--type", "image", image_name],
            check=True
        )

        # 解析 JSON 输出
        inspect_data = json.loads(process.stdout)

        # 返回第一个（且唯一）镜像的信息
        image_info = inspect_data[0]

        return {
            "id": image_info["Id"],
            "tags": image_info.get("RepoTags", []),
            "size": image_info.get("Size", 0),
            "created": image_info.get("Created", ""),
            "architecture": image_info.get("Architecture", ""),
            "os": image_info.get("Os", ""),
            "layers": len(image_info.get("RootFS", {}).get("Layers", []))
        }

    except DockerCommandError as e:
        if "No such image" in str(e):
            raise DockerImageNotFound(f"Image not found: {image_name}")
        raise DockerCommandError(f"Failed to inspect image: {e}")
    except json.JSONDecodeError as e:
        logger.error("解析 docker inspect 输出失败", error=str(e))
        raise DockerCommandError(f"Failed to parse inspect output: {e}")


@registry.register(
    "docker.list_images",
    description="列出本地所有的 Docker 镜像。参数：无。返回：镜像信息列表，每个镜像包含 id、tags、size 等字段"
)
async def docker_list_images() -> List[Dict[str, Any]]:
    """
    列出本地所有 Docker 镜像

    Returns:
        镜像信息列表

    示例:
        >>> images = await docker_list_images()
        >>> for img in images:
        ...     print(f"{img['tags']} - {img['id']}")
    """
    try:
        process = await _run_docker_command(
            ["images", "--format", "{{json .}}"],
            check=True
        )

        # 解析 JSON 输出（每行一个 JSON 对象）
        images = []
        for line in process.stdout.strip().split('\n'):
            if line:
                try:
                    img_data = json.loads(line)
                    images.append({
                        "id": img_data.get("ID", ""),
                        "tags": img_data.get("RepoTags", ["<none>"]),
                        "size": _parse_size_to_bytes(img_data.get("Size", "0")),  # 转换为字节数
                        "created": img_data.get("Created", "")
                    })
                except json.JSONDecodeError as e:
                    logger.warning("解析镜像行失败", line=line, error=str(e))

        logger.info("列出镜像成功", count=len(images))
        return images

    except DockerCommandError as e:
        logger.error("列出镜像失败", error=str(e))
        raise DockerCommandError(f"Failed to list images: {e}")


@registry.register(
    "docker.pull",
    description="从仓库拉取 Docker 镜像。参数：image_name(镜像名称)。返回：无（成功时无返回值）"
)
async def docker_pull(image_name: str) -> None:
    """
    拉取 Docker 镜像

    Args:
        image_name: 镜像名称

    Raises:
        DockerCommandError: 拉取失败

    示例:
        >>> await docker_pull("nginx:latest")
    """
    logger.info("拉取镜像", image=image_name)

    try:
        await _run_docker_command(
            ["pull", image_name],
            check=True
        )

        logger.info("镜像拉取成功", image=image_name)

    except DockerCommandError as e:
        logger.error("拉取镜像失败", image=image_name, error=str(e))
        raise


def _parse_size_to_bytes(size_str: str) -> int:
    """
    将人类可读的大小字符串转换为字节数

    Args:
        size_str: 大小字符串（如 "1.4GB", "125MB"）

    Returns:
        字节数
    """
    if not size_str:
        return 0

    size_str = size_str.strip().upper()
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}

    for unit, multiplier in units.items():
        if size_str.endswith(unit):
            number_part = size_str[:-len(unit)].strip()
            try:
                return int(float(number_part) * multiplier)
            except ValueError:
                return 0

    # 如果没有单位，假设已经是字节数
    try:
        return int(size_str)
    except ValueError:
        return 0


# 便捷函数：获取镜像的真实名称
def get_image_safe_name(image_name: str) -> str:
    """
    将镜像名称转换为文件系统安全的名称

    Args:
        image_name: 原始镜像名称

    Returns:
        安全的文件名

    示例:
        >>> get_image_safe_name("nginx:latest")
        'nginx_latest'
        >>> get_image_safe_name("library/nginx:1.23")
        'library_nginx_1_23'
    """
    return image_name.replace(":", "_").replace("/", "_")
