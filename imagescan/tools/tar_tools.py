"""
Tar 工具模块

用途：
1. 解压 tar 文件
2. 读取 manifest.json
3. 获取层信息

参考：docs/APP_FLOW.md（工具调用详解）
"""

import asyncio
import json,config,toml
import tarfile
import os
from pathlib import Path
from typing import Dict, Any, List

from .registry import registry
from ..utils.logger import get_logger
from ..utils.config import get_config                                                              
                                                                                                    
config = get_config()
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


@registry.register(
    "tar.unpack",
    description="解压 Docker 镜像 tar 文件。参数：tar_path(tar 文件路径), extract_path(解压目标目录)。返回：包含 success, data, summary 的字典"
)
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
        {
            "success": True,
            "data": {"manifest": manifest, "layers_count": 5},
            "summary": "✅ 镜像解压成功：./extract_path (5 层)"
        }

    Raises:
        TarFileNotFound: tar 文件不存在
        TarUnpackError: 解压失败
        ManifestNotFoundError: manifest.json 不存在

    示例:
        >>> result = await tar_unpack(
        ...     "./image_tar/nginx_latest.tar",
        ...     "./tmp/nginx_latest"
        ... )
        >>> print(result["summary"])
    """
    logger.info("解压 tar 文件", tar=tar_path, output=extract_path)

    # 检查 tar 文件是否存在
    tar_file = Path(tar_path)
    if not tar_file.exists():
        logger.error("tar 文件不存在", path=tar_path)
        return {
            "success": False,
            "error": f"tar 文件不存在：{tar_path}",
            "summary": f"❌ tar 文件不存在：{tar_path}"
        }

    # 检查目录是否已存在
    extract_dir = Path(extract_path)
    if extract_dir.exists():
        # 目录已存在，检查是否包含 manifest.json
        manifest_path = extract_dir / "manifest.json"
        if manifest_path.exists():
            # 已经解压过了，直接读取 manifest
            logger.info("tar 已解压，跳过重复解压", path=extract_path)

            # 读取并解析 manifest.json
            with open(manifest_path) as f:
                manifest = json.load(f)

            # 处理两种格式
            if isinstance(manifest, list):
                first_manifest = manifest[0] if manifest else {}
                layer_list = first_manifest.get("Layers", first_manifest.get("layers", []))
            else:
                layer_list = manifest.get("Layers", [])

            logger.info("manifest.json 加载成功", layers=len(layer_list))
            return {
                "success": True,
                "data": {"manifest": manifest, "layers_count": len(layer_list)},
                "summary": f"✅ 镜像已解压：{extract_path} ({len(layer_list)} 层)"
            }
        else:
            # 目录存在但没有 manifest.json，可能是部分解压，清理后重新解压
            logger.info("清理不完整的解压目录", path=extract_path)
            import shutil
            shutil.rmtree(extract_dir)

    # 确保目标目录存在
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 解压 tar 文件（IO 密集型，使用线程池）
        await asyncio.to_thread(
            lambda: tarfile.open(tar_path).extractall(extract_path)
        )

        logger.info("tar 解压成功", path=extract_path)

    except Exception as e:
        logger.error("解压 tar 失败", error=str(e))
        return {
            "success": False,
            "error": f"解压失败：{e}",
            "summary": f"❌ 解压失败：{e}"
        }

    # 读取 manifest.json
    manifest_path = Path(extract_path) / "manifest.json"
    if not manifest_path.exists():
        logger.error("manifest.json 不存在", path=manifest_path)
        return {
            "success": False,
            "error": f"manifest.json 不存在：{manifest_path}",
            "summary": f"❌ manifest.json 不存在"
        }

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
            layers_data = manifest.get("Layers", [])
            logger.info("manifest.json 加载成功", layers=len(layers_data))

        for root, dirs, files in os.walk(extract_path):
                for momo in dirs:
                    os.chmod(os.path.join(root, momo), 0o755)
                for file in files:
                    file_path = os.path.join(root, file)
                    os.chmod(file_path, 0o644) # 确保文件可读

        return {
            "success": True,
            "data": {"manifest": manifest, "layers_count": len(layers_data)},
            "summary": f"✅ 镜像解压成功：{extract_path} ({len(layers_data)} 层)"
        }

    except json.JSONDecodeError as e:
        logger.error("manifest.json 解析失败", error=str(e))
        return {
            "success": False,
            "error": f"manifest.json 解析失败：{e}",
            "summary": f"❌ manifest.json 解析失败：{e}"
        }


@registry.register(
    "tar.list_layers",
    description="列出 tar 文件中的所有镜像层（不需要解压）。参数：tar_path(tar 文件路径)。返回：层信息列表，每个元素包含 layer_id 字段"
)
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


@registry.register(
    "tar.extract_files",
    description="批量从 tar 文件中提取文件。参数：tar_path(tar 文件路径), member_paths(文件在 tar 中的路径列表), output_path(输出目录)。返回：提取后的本地文件路径列表（与输入顺序对应）"
)
async def tar_extract_files(
    tar_path: str,
    member_paths: List[str],
    output_path: str
) -> List[str]:
    """
    批量从 tar 文件中提取文件

    Args:
        tar_path: tar 文件路径
        member_paths: 文件在 tar 中的路径列表
        output_path: 输出目录路径

    Returns:
        extracted_paths: 提取后的文件路径列表

    示例:
        >>> files = await tar_extract_files(
        ...     "./tmp/layer.tar",
        ...     ["etc/config.json", "root/.ssh/config"],
        ...     "./files"
        ... )
        >>> # 返回: ["./files/etc/config.json", "./files/root/.ssh/config"]
    """
    logger.info("批量提取文件", tar=tar_path, count=len(member_paths))

    try:
        extracted_paths = []

        with tarfile.open(tar_path) as tar:
            for member_path in member_paths:
                try:
                    # 获取成员
                    member = tar.getmember(member_path)

                    # 确保输出目录存在
                    output_file = Path(output_path) / member_path
                    output_file.parent.mkdir(parents=True, exist_ok=True)

                    # 提取文件（IO 密集型，使用线程池）
                    await asyncio.to_thread(
                        lambda: tar.extract(member, output_path)
                    )

                    extracted_paths.append(str(output_file))

                except KeyError:
                    logger.warning("文件不存在于 tar 中，跳过", file=member_path)
                    extracted_paths.append(None)  # 保持索引对应

        logger.info("批量提取完成", success=sum(1 for p in extracted_paths if p), total=len(member_paths))
        return extracted_paths

    except Exception as e:
        logger.error("批量提取失败", error=str(e))
        raise TarUnpackError(f"Failed to batch extract files: {e}")



async def _list_all_layer_files(extract_path: str) -> Dict[str, List[str]]:
    """
    一次性列出所有层的文件（内部函数）

    Args:
        extract_path: 解压后的镜像目录路径

    Returns:
        字典 {layer_id: [文件路径列表]}

    示例:
        >>> all_files = await _list_all_layer_files("./output/extracted_image")
        >>> # 返回: {"sha256:abc123": ["etc/config.json", ...], ...}
    """
    import os
    from pathlib import Path

    logger.info("列出所有层的文件", extract_path=extract_path)

    def filter_file_names(files):
        """过滤文件名"""
        prefixes = tuple(config.filter_rules.prefix_exclude)
        stripped_prefixes = tuple(p.lstrip('/') for p in prefixes)
        keywords = config.filter_rules.low_probability_keywords
        extension = config.filter_rules.extension_blacklist

        # 应用学习的模式规则
        from ..core.pattern_learner import get_pattern_learner
        pattern_learner = get_pattern_learner()

        filtered = []
        for member in files:
            if member.isfile():
                name = member.name
                _, ext = os.path.splitext(name)
                # 标准化路径（移除 ./ 前缀）
                if name.startswith('./'):
                    name = name[2:]
                # 过滤以 / 结尾的路径（目录）
                if name.endswith('/'):
                    continue
                # 静态规则过滤
                if name.startswith(prefixes) or name.startswith(stripped_prefixes) or bool([k for k in keywords if k in name]) or ext in extension:
                    continue
                # 学习的模式过滤
                if pattern_learner.should_filter_file(name):
                    continue
                filtered.append(name)
        return filtered

    try:
        result = {}
        extract_dir = Path(extract_path)

        # 读取 manifest.json 获取层列表
        manifest_path = extract_dir / "manifest.json"
        if not manifest_path.exists():
            raise ManifestNotFoundError(f"manifest.json not found in {extract_path}")

        with open(manifest_path) as f:
            manifest = json.load(f)

        # 处理两种格式的 manifest
        if isinstance(manifest, list):
            first_manifest = manifest[0] if manifest else {}
            layers_data = first_manifest.get("Layers", first_manifest.get("layers", []))
        else:
            layers_data = manifest.get("Layers", [])

        # 遍历每一层
        for layer_id in layers_data:
            # 构建层 tar 文件路径
            layer_tar_path = extract_dir / layer_id

            if not layer_tar_path.exists():
                logger.warning("层文件不存在", layer=layer_id)
                result[layer_id] = []
                continue

            try:
                with tarfile.open(layer_tar_path, "r") as tar:
                    files = tar.getmembers()
                    filtered_files = filter_file_names(files)
                    result[layer_id] = filtered_files
                    logger.debug("层文件列表获取成功", layer=layer_id, count=len(filtered_files))

            except Exception as e:
                logger.error("列出层文件失败", layer=layer_id, error=str(e))
                result[layer_id] = []

        total_files = sum(len(files) for files in result.values())
        logger.info("所有层文件列表获取成功", layers=len(result), total_files=total_files)

        return result

    except Exception as e:
        logger.error("列出所有层文件失败", error=str(e))
        raise TarUnpackError(f"Failed to list all layers files: {e}")


@registry.register(
    "tar.analyze_all_layer_files",
    description="分析所有层的文件名，返回可疑文件列表（隔离上下文）。参数：extract_path(解压后的镜像目录)。返回：包含 success, data, summary 的字典，其中 data 包含 suspicious_files, statistics"
)
async def tar_analyze_all_layer_files(extract_path: str) -> Dict[str, Any]:
    """
    分析所有层的文件名，识别可疑的敏感文件（隔离上下文）

    这是隔离上下文的关键工具：文件名分析在独立 LLM 调用中完成，
    只返回可疑文件列表，不污染主对话上下文。

    Args:
        extract_path: 解压后的镜像目录路径

    Returns:
        {
            "success": True,
            "data": {
                "suspicious_files": [
                    {"layer_id": "sha256:abc", "file_path": "app/.env"},
                    {"layer_id": "sha256:abc", "file_path": "config/secret.pem"}
                ],
                "statistics": {
                    "total_layers": 5,
                    "total_files": 10000,
                    "suspicious_count": 50,
                    "medium_count": 100,
                    "filtered_count": 9850
                }
            },
            "summary": ["✅ 文件名分析完成", "  总文件数: 10000", ...]
        }

    示例:
        >>> result = await tar_analyze_all_layer_files("./output/extracted_image")
        >>> print(result["summary"])
    """
    from ..core.llm_client import get_llm_client

    logger.info("开始分析所有层的文件名", extract_path=extract_path)

    # 1. 调用内部函数获取所有文件列表
    all_files = await _list_all_layer_files(extract_path)

    # 2. 业务逻辑：合并所有层的文件
    all_files_flat = []
    for layer_id, files in all_files.items():
        for file_path in files:
            all_files_flat.append({
                "layer_id": layer_id,
                "file_path": file_path
            })

    if not all_files_flat:
        return {
            "success": True,
            "data": {
                "suspicious_files": [],
                "statistics": {
                    "total_layers": len(all_files),
                    "total_files": 0,
                    "suspicious_count": 0,
                    "medium_count": 0,
                    "filtered_count": 0
                }
            },
            "summary": [
                f"✅ 文件名分析完成",
                f"  总文件数: 0",
                f"  高风险文件: 0",
                f"  中风险文件: 0",
                f"  已过滤: 0"
            ]
        }

    # 3. 业务逻辑：限制文件数量（避免 token 超限）
    max_files = 10000
    if len(all_files_flat) > max_files:
        logger.warning(
            "文件数量过多，进行截断",
            total_files=len(all_files_flat),
            truncated=max_files
        )
        all_files_flat = all_files_flat[:max_files]

    # 4. 业务逻辑：构建 prompt
    file_paths = [f["file_path"] for f in all_files_flat]

    prompt = f"""分析以下 {len(file_paths)} 个文件名，识别可能包含敏感凭证的文件。

文件名列表：
{json.dumps(file_paths, ensure_ascii=False, indent=2)}

请只返回可疑文件（可能包含敏感凭证的文件）。

返回 JSON 格式：
{{
    "suspicious": ["文件路径1", "文件路径2"]
}}

规则：
- 重点关注配置文件、环境文件、密钥文件、凭证文件（如 .env、config.json、secret.pem、credentials.json、docker-compose.yaml 等）
- 对于测试文件、示例文件、占位符文件，降低置信度
- 忽略明显的库文件
- 宁可漏报，不要误报
"""

    try:
        # 5. 调用 LLM（使用通用方法）
        llm_client = get_llm_client()
        result = await llm_client.think(prompt, temperature=0.0)

        # 6. 业务逻辑：处理结果
        suspicious_set = set(result.get("suspicious", []))

        suspicious_files = []

        for item in all_files_flat:
            file_path = item["file_path"]
            if file_path in suspicious_set:
                suspicious_files.append({
                    "layer_id": item["layer_id"],
                    "file_path": file_path
                })

        filtered_count = len(all_files_flat) - len(suspicious_files)

        logger.info(
            "文件名分析完成",
            total_files=len(all_files_flat),
            suspicious=len(suspicious_files),
            filtered=filtered_count
        )
        logger.info(
            '可疑文件: ', suspicious_files
        )

        return {
            "success": True,
            "data": {
                "suspicious_files": suspicious_files,
                "statistics": {
                    "total_layers": len(all_files),
                    "total_files": len(all_files_flat),
                    "suspicious_count": len(suspicious_files),
                    "filtered_count": filtered_count
                }
            },
            "summary": [
                f"✅ 文件名分析完成",
                f"  总文件数: {len(all_files_flat)}",
                f"  高风险文件: {len(suspicious_files)}",
                f"  已过滤: {filtered_count}"
            ]
        }

    except asyncio.TimeoutError:
        # ========== 超时情况：分段处理 + 学习 ==========
        logger.warning("LLM分析超时，开始分段处理", total_files=len(file_paths))

        chunk_size = 500
        suspicious_files_list = []  # 只收集可疑文件

        for i in range(0, len(file_paths), chunk_size):
            chunk = file_paths[i:i+chunk_size]
            chunk_num = i // chunk_size + 1
            total_chunks = (len(file_paths) - 1) // chunk_size + 1

            logger.info(
                "处理分段",
                chunk=f"{chunk_num}/{total_chunks}",
                chunk_size=len(chunk)
            )

            # 构建分段 prompt（只返回可疑文件）
            chunk_prompt = f"""分析以下 {len(chunk)} 个文件名，识别可能包含敏感凭证的文件。

文件名列表：
{json.dumps(chunk, ensure_ascii=False, indent=2)}

请只返回可疑文件（可能包含敏感凭证的文件）。

返回 JSON 格式：
{{
    "suspicious": ["文件路径1", "文件路径2"]
}}

规则：
- 重点关注配置文件、环境文件、密钥文件、凭证文件（如 .env、config.json、secret.pem、credentials.json、docker-compose.yaml 等）
- 忽略系统文件、颜色定义、帮助文件等明显不包含凭证的文件
- 宁可漏报，不要误报"""

            try:
                # 调用 LLM 分析分段
                chunk_result = await llm_client.think(chunk_prompt, temperature=0.0)

                # 收集可疑文件
                suspicious_files_list.extend(chunk_result.get("suspicious", []))

            except asyncio.TimeoutError:
                logger.warning(f"分段 {chunk_num} 分析超时，跳过", chunk=chunk_num)
                continue
            except Exception as e:
                logger.error(f"分段 {chunk_num} 分析失败", error=str(e))
                continue

        # ========== 计算低风险文件 ==========
        suspicious_set = set(suspicious_files_list)
        low_risk_files = [f for f in file_paths if f not in suspicious_set]

        logger.info(
            "分段分析完成",
            total_files=len(file_paths),
            suspicious=len(suspicious_set),
            low_risk=len(low_risk_files)
        )

        # ========== 学习低风险文件模式 ==========
        from ..core.pattern_learner import get_pattern_learner
        pattern_learner = get_pattern_learner()

        try:
            learn_result = await pattern_learner.learn_from_files(files=low_risk_files)

            logger.info(
                "低风险文件模式学习完成",
                prefixes_learned=learn_result["prefixes_learned"],
                extensions_learned=learn_result["extensions_learned"]
            )

        except Exception as e:
            logger.error("模式学习失败", error=str(e))

        # ========== 处理分段后的结果 ==========
        suspicious_files = []

        for item in all_files_flat:
            file_path = item["file_path"]
            if file_path in suspicious_set:
                suspicious_files.append({
                    "layer_id": item["layer_id"],
                    "file_path": file_path
                })

        filtered_count = len(all_files_flat) - len(suspicious_files)

        logger.info(
            "分段文件名分析完成",
            total_files=len(all_files_flat),
            suspicious=len(suspicious_files),
            filtered=filtered_count
        )

        return {
            "success": True,
            "data": {
                "suspicious_files": suspicious_files,
                "statistics": {
                    "total_layers": len(all_files),
                    "total_files": len(all_files_flat),
                    "suspicious_count": len(suspicious_files),
                    "medium_count": 0,  # 超时情况下不区分
                    "filtered_count": filtered_count
                }
            },
            "summary": [
                f"✅ 文件名分析完成（分段处理）",
                f"  总文件数: {len(all_files_flat)}",
                f"  可疑文件: {len(suspicious_files)}",
                f"  已过滤: {filtered_count}"
            ]
        }

    except Exception as e:
        logger.error("文件名分析失败", error=str(e))
        # 返回空结果
        return {
            "success": False,
            "error": f"文件名分析失败：{e}",
            "data": {
                "suspicious_files": [],
                "statistics": {
                    "total_layers": len(all_files) if all_files else 0,
                    "total_files": len(all_files_flat) if all_files_flat else 0,
                    "suspicious_count": 0,
                    "medium_count": 0,
                    "filtered_count": len(all_files_flat) if all_files_flat else 0
                }
            },
            "summary": f"❌ 文件名分析失败：{e}"
        }


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


@registry.register(
    "tar.extract_files_from_layers",
    description="从多个层中批量提取文件。参数：extract_path(解压后的镜像目录), layer_files(字典 {layer_id: [文件路径列表]}), output_path(输出目录)。返回：字典 {layer_id: [提取后的本地路径列表]}"
)
async def tar_extract_files_from_layers(
    extract_path: str,
    layer_files: Dict[str, List[str]],
    output_path: str
) -> Dict[str, List[str]]:
    """
    批量从多个层提取文件

    Args:
        extract_path: 解压后的镜像目录路径
        layer_files: 字典 {layer_id: [文件路径列表]}
        output_path: 输出目录路径

    Returns:
        字典 {layer_id: [提取后的本地路径列表]}

    示例:
        >>> layer_files = {
        ...     "sha256:abc123": ["etc/config.json", "root/.ssh/config"],
        ...     "sha256:def456": ["app/main.py"]
        ... }
        >>> result = await tar_extract_files_from_layers(
        ...     "./output/extracted_image",
        ...     layer_files,
        ...     "./output/temp_files"
        ... )
    """
    from pathlib import Path

    logger.info("批量从多层提取文件", layers=len(layer_files))

    try:
        result = {}
        extract_dir = Path(extract_path)
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 遍历每一层
        for layer_id, file_paths in layer_files.items():
            layer_tar_path = extract_dir / layer_id

            if not layer_tar_path.exists():
                logger.warning("层文件不存在", layer=layer_id)
                result[layer_id] = [None] * len(file_paths)
                continue

            try:
                with tarfile.open(layer_tar_path, "r") as tar:
                    extracted_paths = []

                    for file_path in file_paths:
                        try:
                            # 获取成员
                            member = tar.getmember(file_path)

                            # 确保输出目录存在
                            output_file = output_dir / file_path
                            output_file.parent.mkdir(parents=True, exist_ok=True)

                            # 提取文件
                            await asyncio.to_thread(
                                lambda: tar.extract(member, output_path)
                            )

                            extracted_paths.append(str(output_file))

                        except KeyError:
                            logger.warning("文件不存在于层中，跳过", layer=layer_id, file=file_path)
                            extracted_paths.append(None)

                    result[layer_id] = extracted_paths
                    logger.debug("层文件提取完成", layer=layer_id, success=sum(1 for p in extracted_paths if p))

            except Exception as e:
                logger.error("提取层文件失败", layer=layer_id, error=str(e))
                result[layer_id] = [None] * len(file_paths)

        total_extracted = sum(len([p for p in paths if p]) for paths in result.values())
        logger.info("批量提取完成", extracted=total_extracted)

        return result

    except Exception as e:
        logger.error("批量从多层提取失败", error=str(e))
        raise TarUnpackError(f"Failed to extract files from layers: {e}")


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
