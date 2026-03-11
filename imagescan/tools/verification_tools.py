"""
凭证验证工具模块

用途：
1. 使用 TruffleHog 验证发现的凭证
2. 向云厂商真实发包验证凭证存活状态
3. 区分有效凭证和废弃凭证

参考：docs/APP_FLOW.md（工具调用详解）
"""

import asyncio
import json
import os
import subprocess
from typing import Dict, Any

from .registry import registry
from ..utils.logger import get_logger

logger = get_logger(__name__)


@registry.register(
    "verify.trufflehog",
    description="使用 TruffleHog 验证目录中的凭证（真实验证，向云厂商发包）。参数：directory(要扫描的目录路径)。返回：{success, data: {findings, count}, summary}。注意：验证需要时间，可能需要几分钟，且需要网络连接"
)
async def verify_with_trufflehog(
    directory: str
) -> Dict[str, Any]:
    """
    使用 TruffleHog Docker 容器扫描并验证凭证

    真实验证：向 AWS/GitHub/GitLab 等云厂商发包检测凭证是否存活

    Args:
        directory: 要扫描的目录路径（包含待验证的敏感文件）

    Returns:
        {
            "success": True,
            "data": {
                "findings": [...],  # TruffleHog 输出的验证结果
                "count": 5
            },
            "summary": ["✅ TruffleHog 验证完成", "• 发现有效凭证: 5 个"]
        }

    示例:
        >>> result = await verify_with_trufflehog("./files")
        >>> print(result["summary"])  # ["✅ TruffleHog 验证完成", ...]
    """
    logger.info("开始 TruffleHog 验证", directory=directory)
    abs_directory = os.path.abspath(directory)

    try:
        # 使用 asyncio.to_thread 在后台运行同步 subprocess
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "docker", "run", "--rm",
                "-v", f"{abs_directory}:/workspace:ro",  # 只读挂载，保护宿主机
                "trufflesecurity/trufflehog:latest",
                "filesystem", "/workspace",
                "--json",
                # "--only-verified",    # 只返回验证通过的凭证
                "--no-update",
            ],
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时（验证可能需要较长时间）
        )
        
        print(' '.join([
                "docker", "run", "--rm",
                "-v", f"{abs_directory}:/workspace:ro",  # 只读挂载，保护宿主机
                "trufflesecurity/trufflehog:latest",
                "filesystem", "/workspace",
                "--json",
                # "--only-verified",    # 只返回验证通过的凭证
                "--no-update",
            ]))
        # 从 stdout 逐行解析 JSON
        findings = []
        print(result.stdout)
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        findings.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.debug("跳过无效 JSON 行", line=line[:100])
                        continue

        if result.returncode == 0:
            summary_lines = [
                f"✅ TruffleHog 验证完成",
                f"• 扫描目录: {directory}",
                f"• 发现有效凭证: {len(findings)} 个"
            ]

            # 记录发现的凭证类型统计
            if findings:
                cred_types = {}
                for finding in findings:
                    cred_type = finding.get("SourceMetadata", {}).get("Data", {}).get("DetectorType", "Unknown")
                    cred_types[cred_type] = cred_types.get(cred_type, 0) + 1

                summary_lines.append("• 凭证类型分布:")
                for cred_type, count in sorted(cred_types.items(), key=lambda x: -x[1]):
                    summary_lines.append(f"  - {cred_type}: {count}")

            logger.info(
                "TruffleHog 验证成功",
                findings_count=len(findings),
                directory=directory
            )

            return {
                "success": True,
                "data": {"findings": findings, "count": len(findings)},
                "summary": summary_lines
            }
        else:
            logger.error("TruffleHog 执行失败", stderr=result.stderr)
            return {
                "success": False,
                "error": result.stderr,
                "summary": f"❌ TruffleHog 执行失败: {result.stderr[:200]}"
            }

    except subprocess.TimeoutExpired:
        logger.error("TruffleHog 验证超时")
        return {
            "success": False,
            "error": "验证超时（5分钟）",
            "summary": "❌ 验证超时（5分钟），可能网络问题或凭证数量过多"
        }
    except FileNotFoundError:
        logger.error("Docker 未安装")
        return {
            "success": False,
            "error": "Docker 未安装或不可用",
            "summary": "❌ Docker 未安装，无法运行 TruffleHog"
        }
    except Exception as e:
        logger.error("TruffleHog 验证异常", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "summary": f"❌ 验证异常: {e}"
        }

async def main():
    await verify_with_trufflehog('output')

if __name__ == "__main__":
    asyncio.run(main())