"""
框架检测器 - 根据目录结构识别框架类型，并优化扫描策略

核心功能：
1. 检测镜像使用的主要框架/语言
2. 评估凭证风险等级
3. 推荐扫描策略（哪些路径优先，哪些可以跳过）
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FrameworkInfo:
    """框架信息"""
    name: str                      # 框架名称
    risk_level: str                # 风险等级：high, medium, low
    confidence: float              # 检测置信度 0-1
    credential_types: List[str]    # 可能的凭证类型
    priority_paths: List[str]      # 优先扫描路径
    skip_paths: List[str]          # 可以跳过的路径
    evidence: List[str]            # 检测证据（匹配到的文件）


# 框架特征库
FRAMEWORK_SIGNATURES = {
    # ========== 前端框架 ==========
    "react": {
        "risk_level": "medium",
        "files": ["package.json", "src/App.jsx", "src/App.js", "public/index.html"],
        "signature_keywords": ["react", "react-dom", "react-scripts"],
        "credential_types": ["build_env", "api_key", "third_party_key"],
        "priority_paths": [
            ".env",
            ".env.local",
            ".env.development",
            ".env.production",
            "config/",
            "src/config/",
            "public/config.js",
        ],
        "skip_paths": [
            "node_modules/",
            "src/components/",
            "src/pages/",
            "src/hooks/",
            "src/utils/",
            "dist/",
            "build/",
        ]
    },

    "vue": {
        "risk_level": "medium",
        "files": ["package.json", "src/App.vue", "vue.config.js"],
        "signature_keywords": ["vue", "@vue/cli-service"],
        "credential_types": ["build_env", "api_key", "third_party_key"],
        "priority_paths": [
            ".env",
            ".env.local",
            ".env.production",
            "src/config/",
            "vue.config.js",
        ],
        "skip_paths": [
            "node_modules/",
            "src/components/",
            "src/views/",
            "dist/",
        ]
    },

    "angular": {
        "risk_level": "medium",
        "files": ["package.json", "angular.json", "src/index.html"],
        "signature_keywords": ["@angular/core", "@angular/cli"],
        "credential_types": ["build_env", "api_key", "third_party_key"],
        "priority_paths": [
            ".env",
            "src/environments/environment.ts",
            "angular.json",
        ],
        "skip_paths": [
            "node_modules/",
            "src/app/",
            "dist/",
        ]
    },

    "nextjs": {
        "risk_level": "high",  # SSR 框架，风险高
        "files": ["package.json", "next.config.js", "pages/"],
        "signature_keywords": ["next", "next-auth"],
        "credential_types": ["database_url", "api_secret", "build_env", "session_secret"],
        "priority_paths": [
            ".env",
            ".env.local",
            ".env.production",
            "next.config.js",
            "pages/api/",
            "src/app/api/",
            "server/",
        ],
        "skip_paths": [
            "node_modules/",
            ".next/",
            "public/",
        ]
    },

    "nuxtjs": {
        "risk_level": "high",  # SSR 框架，风险高
        "files": ["package.json", "nuxt.config.js"],
        "signature_keywords": ["nuxt", "@nuxt/vue-app"],
        "credential_types": ["database_url", "api_secret", "build_env"],
        "priority_paths": [
            ".env",
            ".env.production",
            "nuxt.config.js",
            "server/api/",
        ],
        "skip_paths": [
            "node_modules/",
            ".nuxt/",
        ]
    },

    # ========== 后端框架 ==========
    "nodejs_backend": {
        "risk_level": "high",
        "files": ["package.json", "server.js", "app.js", "index.js"],
        "signature_keywords": ["express", "koa", "fastify", "nest"],
        "credential_types": [
            "database_password",
            "api_secret",
            "jwt_secret",
            "redis_password",
            "aws_credentials"
        ],
        "priority_paths": [
            ".env",
            "config/",
            "secrets/",
            ".aws/",
            "credentials/",
        ],
        "skip_paths": [
            "node_modules/",
            "tests/",
            "test/",
        ]
    },

    "python": {
        "risk_level": "high",
        "files": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
        "signature_keywords": ["django", "flask", "fastapi", "sqlalchemy"],
        "credential_types": [
            "database_password",
            "api_secret",
            "secret_key",
            "aws_credentials",
            "redis_password"
        ],
        "priority_paths": [
            ".env",
            "settings.py",
            "config.py",
            "config/",
            ".aws/",
            "secrets/",
        ],
        "skip_paths": [
            "site-packages/",
            "__pycache__/",
            "tests/",
            "test/",
            ".venv/",
            "venv/",
        ]
    },

    "django": {
        "risk_level": "high",
        "files": ["manage.py", "settings.py", "wsgi.py"],
        "signature_keywords": ["django", "djangorestframework"],
        "credential_types": ["secret_key", "database_password", "api_secret"],
        "priority_paths": [
            ".env",
            "settings.py",
            "settings/",
            "config/",
        ],
        "skip_paths": [
            "static/",
            "media/",
            "migrations/",
            "tests/",
        ]
    },

    "java": {
        "risk_level": "high",
        "files": ["pom.xml", "build.gradle", "application.properties", "application.yml"],
        "signature_keywords": ["spring-boot", "javax.servlet"],
        "credential_types": [
            "database_password",
            "jmx_password",
            "keystore_password",
            "api_secret"
        ],
        "priority_paths": [
            "application.properties",
            "application.yml",
            "WEB-INF/",
            "META-INF/",
            "config/",
        ],
        "skip_paths": [
            "target/",
            "build/",
            "WEB-INF/lib/",
            "*.jar",
        ]
    },

    "go": {
        "risk_level": "high",
        "files": ["go.mod", "go.sum", "main.go"],
        "signature_keywords": ["gin", "echo", "http"],
        "credential_types": ["database_password", "api_secret", "jwt_secret"],
        "priority_paths": [
            ".env",
            "config/",
            "secrets/",
        ],
        "skip_paths": [
            "vendor/",
            "tests/",
        ]
    },

    "php": {
        "risk_level": "high",
        "files": ["composer.json", "index.php"],
        "signature_keywords": ["laravel", "symfony", "wordpress"],
        "credential_types": ["database_password", "api_key", "app_secret"],
        "priority_paths": [
            ".env",
            ".env.local",
            ".env.production",
            "config/",
            "wp-config.php",
        ],
        "skip_paths": [
            "vendor/",
            "storage/framework/",
            "bootstrap/cache/",
        ]
    },

    "ruby": {
        "risk_level": "high",
        "files": ["Gemfile", "config.ru", "Rakefile"],
        "signature_keywords": ["rails", "sinatra"],
        "credential_types": [
            "secret_key_base",
            "database_password",
            "aws_credentials"
        ],
        "priority_paths": [
            ".env",
            "config/secrets.yml",
            "config/database.yml",
            "credentials/",
        ],
        "skip_paths": [
            "vendor/bundle/",
            "tmp/",
            "log/",
        ]
    },

    "dotnet": {
        "risk_level": "high",
        "files": ["*.csproj", "*.sln", "appsettings.json", "web.config"],
        "signature_keywords": ["Microsoft.AspNetCore", "EntityFramework"],
        "credential_types": [
            "connection_string",
            "api_secret",
            "azure_credentials"
        ],
        "priority_paths": [
            "appsettings.json",
            "appsettings.Production.json",
            "web.config",
            "config/",
        ],
        "skip_paths": [
            "bin/",
            "obj/",
            "wwwroot/",
        ]
    },

    # ========== Web 服务器 ==========
    "nginx": {
        "risk_level": "low",
        "files": ["nginx.conf", "/etc/nginx/nginx.conf"],
        "signature_keywords": ["nginx"],
        "credential_types": ["basic_auth_password", "ssl_certificate_key"],
        "priority_paths": [
            "nginx.conf",
            "conf.d/",
            ".htpasswd",
        ],
        "skip_paths": [
            "html/",
            "usr/share/nginx/",
            "var/log/nginx/",
        ]
    },

    "apache": {
        "risk_level": "low",
        "files": ["httpd.conf", "apache2.conf", ".htaccess"],
        "signature_keywords": ["apache"],
        "credential_types": ["basic_auth_password", "ssl_certificate_key"],
        "priority_paths": [
            "httpd.conf",
            "apache2.conf",
            ".htaccess",
            ".htpasswd",
            "sites-enabled/",
        ],
        "skip_paths": [
            "htdocs/",
            "var/www/",
            "logs/",
        ]
    },

    # ========== 基础设施 ==========
    "docker_base": {
        "risk_level": "low",
        "files": ["Dockerfile", "docker-compose.yml"],
        "signature_keywords": ["FROM", "docker"],
        "credential_types": ["docker_credentials", "registry_password"],
        "priority_paths": [
            "/root/.docker/",
            "/etc/docker/",
            "Dockerfile",
        ],
        "skip_paths": [
            "usr/",
            "lib/",
            "bin/",
        ]
    },
}


class FrameworkDetector:
    """框架检测器"""

    def __init__(self):
        self.signatures = FRAMEWORK_SIGNATURES

    async def detect(self, file_list: List[str]) -> FrameworkInfo:
        """
        检测镜像使用的框架

        Args:
            file_list: 镜像中的所有文件列表

        Returns:
            FrameworkInfo: 框架信息
        """
        logger.info("开始检测框架", total_files=len(file_list))

        # 检测每个框架的匹配度
        detected_frameworks = []

        for framework_name, signatures in self.signatures.items():
            matches = self._check_framework(file_list, framework_name, signatures)

            if matches["score"] > 0:
                detected_frameworks.append({
                    "name": framework_name,
                    "score": matches["score"],
                    "evidence": matches["evidence"],
                    "risk_level": signatures["risk_level"],
                    "confidence": min(1.0, matches["score"] / 3),  # 3个证据即100%置信度
                })

        # 如果没有检测到任何框架
        if not detected_frameworks:
            logger.warning("未检测到已知框架", defaulting_to="unknown")
            return FrameworkInfo(
                name="unknown",
                risk_level="medium",  # 未知风险，谨慎扫描
                confidence=0.0,
                credential_types=["unknown"],
                priority_paths=[".env", "config/", "secrets/"],
                skip_paths=["usr/", "lib/", "bin/"],
                evidence=[]
            )

        # 排序：优先选择风险级别高、置信度高的框架
        detected_frameworks.sort(
            key=lambda x: (
                self._risk_level_order(x["risk_level"]),
                x["confidence"]
            ),
            reverse=True
        )

        primary = detected_frameworks[0]
        framework_name = primary["name"]
        signatures = self.signatures[framework_name]

        logger.info(
            "检测到主框架",
            framework=framework_name,
            risk_level=primary["risk_level"],
            confidence=primary["confidence"]
        )

        return FrameworkInfo(
            name=framework_name,
            risk_level=primary["risk_level"],
            confidence=primary["confidence"],
            credential_types=signatures["credential_types"],
            priority_paths=signatures["priority_paths"],
            skip_paths=signatures["skip_paths"],
            evidence=primary["evidence"]
        )

    def _check_framework(
        self,
        file_list: List[str],
        framework_name: str,
        signatures: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        检查是否匹配特定框架

        Returns:
            {
                "score": 匹配分数（证据数量）,
                "evidence": ["匹配到的文件1", "匹配到的文件2"]
            }
        """
        score = 0
        evidence = []

        # 检查特征文件
        for pattern in signatures["files"]:
            for file_path in file_list:
                # 支持通配符匹配
                if "*" in pattern:
                    # 简单的通配符处理（只处理 *.xxx 格式）
                    if pattern.startswith("*."):
                        ext = pattern[1:]
                        if file_path.endswith(ext):
                            score += 1
                            if len(evidence) < 5:
                                evidence.append(file_path)
                else:
                    if pattern in file_path:
                        score += 1
                        if len(evidence) < 5:
                            evidence.append(file_path)

        # 检查关键词（需要读取 package.json 等文件内容，这里简化处理）
        # 实际实现中可以添加文件内容分析

        return {"score": score, "evidence": evidence}

    def _risk_level_order(self, risk_level: str) -> int:
        """风险等级排序权重"""
        order = {"high": 3, "medium": 2, "low": 1}
        return order.get(risk_level, 0)

    def should_skip_file(self, file_path: str, framework_info: FrameworkInfo) -> bool:
        """
        判断是否应该跳过某个文件

        Args:
            file_path: 文件路径
            framework_info: 框架信息

        Returns:
            True 表示跳过，False 表示扫描
        """
        # 检查是否在 skip_paths 中
        for skip_pattern in framework_info.skip_paths:
            if skip_pattern in file_path:
                return True

        return False

    def get_scan_priority(self, file_path: str, framework_info: FrameworkInfo) -> int:
        """
        获取文件扫描优先级

        Returns:
            0 = 最高优先级（必须扫描）
            1 = 高优先级
            2 = 中等优先级
            3 = 低优先级（可能跳过）
        """
        # 检查是否在 priority_paths 中
        for i, priority_pattern in enumerate(framework_info.priority_paths):
            if priority_pattern in file_path:
                return 0 if i < 3 else 1  # 前3个最高优先级

        # 检查是否在 skip_paths 中
        if self.should_skip_file(file_path, framework_info):
            return 3

        return 2  # 默认中等优先级


# 便捷函数
async def detect_framework(file_list: List[str]) -> FrameworkInfo:
    """便捷函数：检测框架"""
    detector = FrameworkDetector()
    return await detector.detect(file_list)
