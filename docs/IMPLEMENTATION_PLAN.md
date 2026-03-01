# ImageScan-Agent 实施计划文档 (IMPLEMENTATION_PLAN)

## 文档信息

- **项目名称**: ImageScan-Agent
- **文档版本**: 1.0.0
- **最后更新**: 2025-03-01
- **文档状态**: 详细版（逐步构建序列）

---

## 目录

1. [构建总览](#构建总览)
2. [阶段 0: 环境准备](#阶段-0-环境准备)
3. [阶段 1: 基础设施层](#阶段-1-基础设施层)
4. [阶段 2: 工具层](#阶段-2-工具层)
5. [阶段 3: 数据层](#阶段-3-数据层)
6. [阶段 4: LLM 集成层](#阶段-4-llm-集成层)
7. [阶段 5: Agent 核心层](#阶段-5-agent-核心层)
8. [阶段 6: CLI 界面层](#阶段-6-cli-界面层)
9. [阶段 7: API 服务层](#阶段-7-api-服务层)
10. [阶段 8: Web UI 层](#阶段-8-web-ui-层)
11. [阶段 9: 测试与优化](#阶段-9-测试与优化)
12. [阶段 10: 部署与文档](#阶段-10-部署与文档)

---

## 构建总览

### MVP 范围

- ✅ CLI + 基本扫描功能
- ✅ SQLite 数据库持久化
- ✅ 主从 Agent 系统（1 主 + 4 从）
- ✅ 事件总线通信
- ✅ 实时进度反馈

### 构建顺序

```
阶段0: 环境准备
  ↓
阶段1: 基础设施 (项目结构、配置、日志)
  ↓
阶段2: 工具层 (Docker、Tar、文件操作)
  ↓
阶段3: 数据层 (SQLite、数据模型)
  ↓
阶段4: LLM 集成 (Gemini、扫描器)
  ↓
阶段5: Agent 核心 (主从 Agent、事件总线)
  ↓
阶段6: CLI (命令行界面)
  ↓
阶段7: API (FastAPI 后端)
  ↓
阶段8: Web UI (Next.js 前端)
  ↓
阶段9: 测试 (单元测试、集成测试)
  ↓
阶段10: 部署 (Docker、文档)
```

---

## 阶段 0: 环境准备

### 目标
搭建开发环境，确保所有依赖可用

### 步骤

#### 0.1 Python 环境设置

```bash
# 安装 Python 3.11.8
pyenv install 3.11.8
pyenv local 3.11.8

# 验证版本
python --version  # 应该输出 3.11.8

# 升级 pip
pip install --upgrade pip==23.3.1
```

#### 0.2 Node.js 环境设置

```bash
# 安装 Node.js 20.10.0 (LTS)
nvm install 20.10.0
nvm use 20.10.0

# 验证版本
node --version   # 应该输出 20.10.0
npm --version    # 应该输出 10.2.4
```

#### 0.3 Docker 环境验证

```bash
# 验证 Docker 安装
docker --version  # 应该 >= 24.0.7

# 验证 Docker 可用
docker ps  # 应该成功运行
```

#### 0.4 环境变量配置

```bash
# 创建 .env 文件
cat > .env << EOF
# Gemini API
GEMINI_API_KEY=your_gemini_api_key_here

# 路径配置
IMAGE_TAR_PATH=./image_tar
FILES_PATH=./files
SECRETS_PATH=./secrets
OUTPUT_PATH=./output
DATA_PATH=./data

# 日志配置
LOG_LEVEL=INFO
LOG_FORMAT=json
EOF

# 设置权限
chmod 600 .env
```

#### 0.5 Git 仓库初始化

```bash
# 初始化 .gitignore
cat > .gitignore << EOF
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/

# Node.js
node_modules/
.next/
out/

# 项目特定
*.json
tmp/
image_tar/
output/
test*
config*

# 环境变量
.env

# IDE
.vscode/
.idea/
EOF
```

### 验收标准

- [ ] Python 3.11.8 已安装
- [ ] Node.js 20.10.0 已安装
- [ ] Docker 24.0.7+ 已安装并运行
- [ ] .env 文件已创建
- [ ] .gitignore 已配置

---

## 阶段 1: 基础设施层

### 目标
建立项目结构、配置管理、日志系统

### 步骤

#### 1.1 创建项目结构

```bash
# 创建目录结构
mkdir -p imagescan/{core,agents,tools,api,utils}
mkdir -p imagescan/models
mkdir -p tests/{unit,integration}
mkdir -p docs
mkdir -p data
mkdir -p config

# 目录结构
imagescan/
├── core/           # 核心抽象类
├── agents/         # Agent 实现
├── tools/          # 工具注册与实现
├── api/            # FastAPI 端点
├── utils/          # 工具函数
└── models/         # 数据模型
```

#### 1.2 配置管理模块

**文件**: `imagescan/utils/config.py`

```python
from pydantic_settings import BaseSettings
from typing import List
import toml
from pathlib import Path

class FilterRules(BaseModel):
    prefix_exclude: List[str] = []
    low_probability_keywords: List[str] = []

class ScanParameters(BaseModel):
    confidence_threshold: float = 0.7
    max_file_size_mb: int = 10
    max_layers: int = 100
    enable_verification: bool = True
    verification_mode: str = "static"

class SystemConfig(BaseModel):
    log_level: str = "INFO"
    log_format: str = "json"
    log_rotation_days: int = 7
    max_workers: int = 4

class StorageConfig(BaseModel):
    output_path: str = "./output"
    database_path: str = "./data/scanner.db"
    chromadb_path: str = "./data/chromadb"

class APIConfig(BaseModel):
    gemini_api_key: str
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    model: str = "gemini-2.5-flash"
    timeout_seconds: int = 60

class Config(BaseModel):
    api: APIConfig
    filter_rules: FilterRules
    scan_parameters: ScanParameters
    system: SystemConfig
    storage: StorageConfig

    @classmethod
    def load(cls, path: str = "config.toml") -> "Config":
        data = toml.load(path)
        return cls(**data)

# 使用示例
config = Config.load()
```

#### 1.3 日志系统

**文件**: `imagescan/utils/logger.py`

```python
import structlog
import logging
from pathlib import Path
from typing import Any

def setup_logging(
    level: str = "INFO",
    log_format: str = "json",
    log_path: str = "./logs"
):
    """配置结构化日志"""

    # 确保日志目录存在
    Path(log_path).mkdir(parents=True, exist_ok=True)

    # 配置 structlog
    if log_format == "json":
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper("iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        structlog.configure(
            processors=[
                structlog.dev.ConsoleRenderer()
            ]
        )

    # 设置标准库日志级别
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(message)s"
    )

def get_logger(name: str) -> Any:
    """获取 logger 实例"""
    return structlog.get_logger(name)

# 使用示例
logger = get_logger(__name__)
logger.info("Scanner started", task_id="abc-123")
```

#### 1.4 配置文件

**文件**: `config.toml`

```toml
[api]
gemini_api_key = "${GEMINI_API_KEY}"
base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
model = "gemini-2.5-flash"
timeout_seconds = 60

[filter_rules]
prefix_exclude = [
    "/usr",
    "/lib",
    "/bin",
    "/etc/ssl",
    "/var/lib"
]
low_probability_keywords = [
    "node_modules",
    ".git",
    "__pycache__"
]

[scan_parameters]
confidence_threshold = 0.7
max_file_size_mb = 10
max_layers = 100
enable_verification = true
verification_mode = "static"

[system]
log_level = "INFO"
log_format = "json"
log_rotation_days = 7
max_workers = 4

[storage]
output_path = "./output"
database_path = "./data/scanner.db"
chromadb_path = "./data/chromadb"
```

### 验收标准

- [ ] 项目目录结构已创建
- [ ] 配置管理模块可加载 config.toml
- [ ] 日志系统输出结构化 JSON 日志
- [ ] 环境变量正确替换

---

## 阶段 2: 工具层

### 目标
实现 Docker、Tar、文件操作工具

### 步骤

#### 2.1 工具注册表

**文件**: `imagescan/tools/registry.py`

```python
from typing import Dict, Callable, Any
import inspect

class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, Callable] = {}

    def register(self, name: str = None):
        """装饰器：注册工具"""
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            self._tools[tool_name] = func
            return func
        return decorator

    def get(self, name: str) -> Callable:
        """获取工具"""
        if name not in self._tools:
            raise ValueError(f"Tool not found: {name}")
        return self._tools[name]

    def list_tools(self) -> Dict[str, str]:
        """列出所有工具"""
        return {
            name: func.__doc__ or "No description"
            for name, func in self._tools.items()
        }

    def get_schema(self, name: str) -> Dict[str, Any]:
        """获取工具的 JSON Schema"""
        func = self.get(name)
        sig = inspect.signature(func)
        return {
            "name": name,
            "description": func.__doc__,
            "parameters": {
                "type": "object",
                "properties": {
                    name: {
                        "type": "string",
                        "description": param.annotation.__name__ if hasattr(param.annotation, '__name__') else str(param.annotation)
                    }
                    for name, param in sig.parameters.items()
                }
            }
        }

# 全局注册表
registry = ToolRegistry()
```

#### 2.2 Docker 工具

**文件**: `imagescan/tools/docker_tools.py`

```python
import docker
from pathlib import Path
from ..tools.registry import registry
from ..utils.logger import get_logger

logger = get_logger(__name__)

class DockerImageNotFound(Exception):
    pass

class DockerSaveError(Exception):
    pass

@registry.register("docker.save")
async def docker_save(image_name: str, output_path: str) -> str:
    """
    保存 Docker 镜像为 tar 文件

    Args:
        image_name: 镜像名称 (如 "nginx:latest")
        output_path: 输出目录路径

    Returns:
        tar_file_path: 保存的 tar 文件路径
    """
    logger.info("Saving Docker image", image=image_name)

    try:
        client = docker.from_env()
        image = client.images.get(image_name)

        # 确保输出目录存在
        Path(output_path).mkdir(parents=True, exist_ok=True)

        # 构建输出文件名
        safe_name = image_name.replace(":", "_").replace("/", "_")
        tar_path = f"{output_path}/{safe_name}.tar"

        # 保存镜像
        await asyncio.to_thread(image.save, tar_path)

        logger.info("Docker image saved", path=tar_path)
        return tar_path

    except docker.errors.ImageNotFound as e:
        logger.error("Image not found", image=image_name)
        raise DockerImageNotFound(str(e))
    except Exception as e:
        logger.error("Failed to save image", error=str(e))
        raise DockerSaveError(str(e))
```

#### 2.3 Tar 工具

**文件**: `imagescan/tools/tar_tools.py`

```python
import tarfile
from pathlib import Path
from ..tools.registry import registry
from ..utils.logger import get_logger

logger = get_logger(__name__)

@registry.register("tar.unpack")
async def tar_unpack(tar_path: str, extract_path: str) -> dict:
    """
    解压 tar 文件

    Args:
        tar_path: tar 文件路径
        extract_path: 解压目标路径

    Returns:
        manifest: manifest.json 内容
    """
    logger.info("Unpacking tar", tar=tar_path)

    try:
        # 确保目标目录存在
        Path(extract_path).mkdir(parents=True, exist_ok=True)

        # 解压 tar 文件
        await asyncio.to_thread(
            lambda: tarfile.open(tar_path).extractall(extract_path)
        )

        # 读取 manifest.json
        manifest_path = f"{extract_path}/manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)

        logger.info("Tar unpacked", path=extract_path)
        return manifest

    except Exception as e:
        logger.error("Failed to unpack tar", error=str(e))
        raise
```

#### 2.4 文件操作工具

**文件**: `imagescan/tools/file_tools.py`

```python
import tarfile
import aiofiles
from pathlib import Path
from ..tools.registry import registry
from ..utils.logger import get_logger

logger = get_logger(__name__)

@registry.register("file.list_layer_files")
async def file_list_layer_files(layer_tar_path: str) -> list[str]:
    """
    列出层中的所有文件

    Args:
        layer_tar_path: 层 tar 文件路径

    Returns:
        files: 文件路径列表
    """
    logger.debug("Listing layer files", layer=layer_tar_path)

    try:
        with tarfile.open(layer_tar_path) as tar:
            return tar.getnames()
    except Exception as e:
        logger.error("Failed to list files", error=str(e))
        raise

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
    """
    logger.debug("Extracting file", file=file_path)

    try:
        with tarfile.open(layer_tar_path) as tar:
            member = tar.getmember(file_path)

            # 确保输出目录存在
            output_dir = Path(output_path) / Path(file_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            # 提取文件
            await asyncio.to_thread(
                lambda: tar.extract(member, output_path)
            )

            extracted_path = f"{output_path}/{file_path}"
            logger.debug("File extracted", path=extracted_path)
            return extracted_path

    except Exception as e:
        logger.error("Failed to extract file", error=str(e))
        raise

@registry.register("file.read_content")
async def file_read_content(file_path: str) -> str:
    """
    读取文件内容

    Args:
        file_path: 文件路径

    Returns:
        content: 文件内容
    """
    try:
        async with aiofiles.open(file_path, mode='r') as f:
            content = await f.read()
            return content
    except Exception as e:
        logger.error("Failed to read file", error=str(e))
        raise
```

### 验收标准

- [ ] 工具注册表可注册和调用工具
- [ ] docker.save() 成功保存镜像为 tar
- [ ] tar.unpack() 成功解压 tar 文件
- [ ] file_extract_from_layer() 成功提取文件
- [ ] 所有工具支持异步操作

---

## 阶段 3: 数据层

### 目标
实现 SQLite 数据库和数据模型

### 步骤

#### 3.1 数据模型定义

**文件**: `imagescan/models/task.py`

```python
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
import uuid

class ScanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ScanTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_name: str
    image_id: str
    status: ScanStatus = ScanStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    total_layers: int = 0
    processed_layers: int = 0
    total_files: int = 0
    processed_files: int = 0
    credentials_found: int = 0
```

**文件**: `imagescan/models/credential.py`

```python
class CredentialType(str, Enum):
    API_KEY = "api_key"
    PASSWORD = "password"
    TOKEN = "token"
    CERTIFICATE = "certificate"
    PRIVATE_KEY = "private_key"
    DATABASE_URL = "database_url"
    AWS_KEY = "aws_key"
    SSH_KEY = "ssh_key"
    UNKNOWN = "unknown"

class ValidationStatus(str, Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"

class Credential(BaseModel):
    credential_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    cred_type: CredentialType
    confidence: float
    file_path: str
    line_number: Optional[int] = None
    layer_id: str
    context: str
    raw_value: Optional[str] = None
    validation_status: ValidationStatus = ValidationStatus.PENDING
    verified_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}
```

#### 3.2 数据库初始化

**文件**: `imagescan/utils/database.py`

```python
import aiosqlite
from pathlib import Path
from ..utils.logger import get_logger

logger = get_logger(__name__)

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self):
        """初始化数据库表"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            # 启用外键约束
            await db.execute("PRAGMA foreign_keys = ON")

            # 创建 scan_tasks 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scan_tasks (
                    task_id TEXT PRIMARY KEY,
                    image_name TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    total_layers INTEGER NOT NULL DEFAULT 0,
                    processed_layers INTEGER NOT NULL DEFAULT 0,
                    total_files INTEGER NOT NULL DEFAULT 0,
                    processed_files INTEGER NOT NULL DEFAULT 0,
                    credentials_found INTEGER NOT NULL DEFAULT 0
                )
            """)

            # 创建 credentials 表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS credentials (
                    credential_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    cred_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    file_path TEXT NOT NULL,
                    line_number INTEGER,
                    layer_id TEXT NOT NULL,
                    context TEXT NOT NULL,
                    raw_value TEXT,
                    validation_status TEXT NOT NULL,
                    verified_at TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (task_id) REFERENCES scan_tasks(task_id) ON DELETE CASCADE
                )
            """)

            # 创建索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_credentials_task_id
                ON credentials(task_id)
            """)

            await db.commit()
            logger.info("Database initialized", path=self.db_path)

    async def insert_task(self, task: ScanTask) -> str:
        """插入扫描任务"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO scan_tasks (
                    task_id, image_name, image_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (task.task_id, task.image_name, task.image_id,
                 task.status.value, task.created_at.isoformat())
            )
            await db.commit()
            return task.task_id

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        **kwargs
    ):
        """更新任务状态"""
        async with aiosqlite.connect(self.db_path) as db:
            updates = ["status = ?"]
            values = [status]

            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(value)

            values.append(task_id)

            await db.execute(
                f"UPDATE scan_tasks SET {', '.join(updates)} WHERE task_id = ?",
                values
            )
            await db.commit()

    async def insert_credential(self, cred: Credential) -> str:
        """插入凭证"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO credentials (
                    credential_id, task_id, cred_type, confidence,
                    file_path, line_number, layer_id, context,
                    validation_status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cred.credential_id, cred.task_id, cred.cred_type.value,
                    cred.confidence, cred.file_path, cred.line_number,
                    cred.layer_id, cred.context, cred.validation_status.value,
                    json.dumps(cred.metadata)
                )
            )
            await db.commit()
            return cred.credential_id
```

### 验收标准

- [ ] 数据库表成功创建
- [ ] ScanTask 和 Credential 模型定义完整
- [ ] 数据库可插入和更新记录
- [ ] 外键约束正常工作

---

## 阶段 4: LLM 集成层

### 目标
实现 Gemini API 集成和 LLM 扫描器

### 步骤

#### 4.1 LLM 客户端

**文件**: `imagescan/core/llm_client.py`

```python
from openai import AsyncOpenAI
from ..utils.config import Config
from ..utils.logger import get_logger

logger = get_logger(__name__)

class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api.gemini_api_key,
            base_url=config.api.base_url
        )
        self.model = config.api.model

    async def think(self, prompt: str, system_prompt: str = None) -> dict:
        """
        通用 LLM 调用

        Args:
            prompt: 用户提示
            system_prompt: 系统提示

        Returns:
            response: JSON 格式响应
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_mime_type="application/json"
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error("LLM call failed", error=str(e))
            raise
```

#### 4.2 文件名分析器

**文件**: `imagescan/core/filename_analyzer.py`

```python
SYSTEM_PROMPT = """
你是 Docker 镜像文件安全分析专家。
你的任务是分析文件名，判断哪些文件可能包含敏感凭证。

判断标准:
- .env, .config, config.json: 高风险
- *.pem, *.key, *.cert: 证书/私钥，高风险
- docker-compose.yml, k8s/*.yaml: 可能包含密钥
- __pycache__, node_modules: 低风险（系统目录）

返回 JSON 格式:
{
    "high_risk": ["文件路径"],
    "medium_risk": ["文件路径"],
    "low_risk": ["文件路径"]
}
"""

class FilenameAnalyzer:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def analyze(self, files: list[str]) -> dict:
        """
        分析文件名

        Args:
            files: 文件路径列表

        Returns:
            classification: 文件分类结果
        """
        prompt = f"""
        分析以下文件列表，判断哪些可能包含敏感凭证:

        {json.dumps(files, indent=2)}

        返回 JSON 格式分类。
        """

        response = await self.llm.think(prompt, SYSTEM_PROMPT)
        return response
```

#### 4.3 内容扫描器

**文件**: `imagescan/core/content_scanner.py`

```python
SYSTEM_PROMPT = """
你是凭证检测专家，专门识别 Docker 镜像中的敏感凭证。

检测目标:
1. API Keys (AWS, Google, GitHub, etc.)
2. 密码
3. Tokens (JWT, OAuth, Bearer)
4. 证书/私钥 (PEM, KEY)
5. 数据库连接串

返回 JSON 格式:
{
    "credentials": [
        {
            "type": "api_key",
            "value": "AKIAIOSFODNN7EXAMPLE",
            "line_number": 10,
            "context": "AWS_ACCESS_KEY: AKIA...",
            "confidence": 0.95
        }
    ]
}

注意:
- 只返回真正看起来像凭证的内容
- 提供足够的上下文（前后2行）
- 置信度范围 0.0 - 1.0
"""

class ContentScanner:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def scan(
        self,
        file_path: str,
        content: str,
        max_length: int = 10000
    ) -> list:
        """
        扫描文件内容

        Args:
            file_path: 文件路径
            content: 文件内容
            max_length: 最大内容长度（避免 token 超限）

        Returns:
            credentials: 检测到的凭证列表
        """
        # 截断过长内容
        if len(content) > max_length:
            content = content[:max_length]

        prompt = f"""
        文件: {file_path}
        内容:
        {content}

        检测敏感凭证，返回 JSON 格式。
        """

        response = await self.llm.think(prompt, SYSTEM_PROMPT)
        return response.get("credentials", [])
```

### 验收标准

- [ ] LLMClient 可成功调用 Gemini API
- [ ] FilenameAnalyzer 可正确分类文件
- [ ] ContentScanner 可检测凭证
- [ ] 所有响应为 JSON 格式

---

## 阶段 5: Agent 核心层

### 目标
实现主从 Agent 系统和事件总线

### 步骤

#### 5.1 事件定义

**文件**: `imagescan/core/events.py`

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Literal, Optional

class TaskCreatedEvent(BaseModel):
    event_type: Literal["task.created"] = "task.created"
    task_id: str
    image_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class LayerExtractedEvent(BaseModel):
    event_type: Literal["layer.extracted"] = "layer.extracted"
    task_id: str
    layers: list[dict]

class FilenameAnalyzedEvent(BaseModel):
    event_type: Literal["filename.analyzed"] = "filename.analyzed"
    task_id: str
    layer_id: str
    classification: dict

class CredentialFoundEvent(BaseModel):
    event_type: Literal["credential.found"] = "credential.found"
    task_id: str
    credential: dict

class TaskCompletedEvent(BaseModel):
    event_type: Literal["task.completed"] = "task.completed"
    task_id: str
    status: str
    credentials_count: int
    duration_seconds: float
```

#### 5.2 事件总线

**文件**: `imagescan/core/event_bus.py`

```python
import asyncio
from typing import Callable, Dict
from ..utils.logger import get_logger

logger = get_logger(__name__)

class EventBus:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.subscribers: Dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """订阅事件"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)
        logger.debug("Subscriber added", event=event_type)

    async def publish(self, event: BaseModel):
        """发布事件"""
        await self.queue.put(event)
        logger.debug("Event published", type=event.event_type)

    async def dispatch(self, event: BaseModel):
        """分发事件给订阅者"""
        event_type = event.event_type
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                try:
                    await callback(event)
                except Exception as e:
                    logger.error("Subscriber failed", error=str(e))

    async def run(self):
        """运行事件总线"""
        while True:
            event = await self.queue.get()
            await self.dispatch(event)
            self.queue.task_done()
```

#### 5.3 基础 Agent

**文件**: `imagescan/core/agent.py`

```python
from abc import ABC, abstractmethod
from ..core.event_bus import EventBus
from ..utils.logger import get_logger

logger = get_logger(__name__)

class Agent(ABC):
    def __init__(self, event_bus: EventBus, name: str):
        self.event_bus = event_bus
        self.name = name
        self.logger = logger.bind(agent=name)

    @abstractmethod
    async def run(self):
        """运行 Agent"""
        pass
```

#### 5.4 主 Agent

**文件**: `imagescan/agents/master_agent.py`

```python
from ..core.agent import Agent
from ..core.events import *
from ..core.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger(__name__)

class MasterAgent(Agent):
    def __init__(
        self,
        event_bus: EventBus,
        llm_client: LLMClient,
        task_id: str,
        image_name: str
    ):
        super().__init__(event_bus, "master")
        self.llm = llm_client
        self.task_id = task_id
        self.image_name = image_name
        self.credentials = []

    async def run(self):
        """运行主 Agent"""
        self.logger.info("Master agent started", task_id=self.task_id)

        # 订阅事件
        self.event_bus.subscribe("credential.found", self.on_credential_found)
        self.event_bus.subscribe("task.completed", self.on_task_completed)

        # 1. 制定计划
        plan = await self.create_plan()
        self.logger.info("Plan created", plan=plan)

        # 2. 分发任务
        await self.event_bus.publish(LayerExtractionRequest(
            task_id=self.task_id,
            image_name=self.image_name
        ))

    async def create_plan(self) -> dict:
        """制定扫描计划"""
        prompt = f"""
        任务: 扫描 Docker 镜像 {self.image_name}

        请制定扫描计划:
        1. 保存镜像为 tar
        2. 解压 tar 获取层列表
        3. 逐层分析文件名
        4. 提取可疑文件内容
        5. LLM 分析内容检测凭证
        6. 生成报告

        返回 JSON 格式计划。
        """

        response = await self.llm.think(prompt)
        return response

    async def on_credential_found(self, event: CredentialFoundEvent):
        """处理凭证发现事件"""
        self.credentials.append(event.credential)
        self.logger.info("Credential found", total=len(self.credentials))

    async def on_task_completed(self, event: TaskCompletedEvent):
        """处理任务完成事件"""
        self.logger.info("Task completed", status=event.status)
```

#### 5.5 执行 Agent

**文件**: `imagescan/agents/executor_agent.py`

```python
from ..core.agent import Agent
from ..core.events import *
from ..tools.registry import registry
from ..core.filename_analyzer import FilenameAnalyzer
from ..core.content_scanner import ContentScanner
from ..utils.logger import get_logger

logger = get_logger(__name__)

class ExecutorAgent(Agent):
    def __init__(
        self,
        event_bus: EventBus,
        filename_analyzer: FilenameAnalyzer,
        content_scanner: ContentScanner
    ):
        super().__init__(event_bus, "executor")
        self.filename_analyzer = filename_analyzer
        self.content_scanner = content_scanner

    async def run(self):
        """运行执行 Agent"""
        self.logger.info("Executor agent started")

        # 订阅事件
        self.event_bus.subscribe("layer.extracted", self.on_layer_extracted)
        self.event_bus.subscribe("filename.analyzed", self.on_filename_analyzed)

    async def on_layer_extracted(self, event: LayerExtractedEvent):
        """处理层提取完成事件"""
        for layer in event.layers:
            # 1. 列出文件
            files = await registry.get("file.list_layer_files")(layer["tar_path"])

            # 2. LLM 分析文件名
            classification = await self.filename_analyzer.analyze(files)

            # 3. 发布分析完成事件
            await self.event_bus.publish(FilenameAnalyzedEvent(
                task_id=event.task_id,
                layer_id=layer["layer_id"],
                classification=classification
            ))

    async def on_filename_analyzed(self, event: FilenameAnalyzedEvent):
        """处理文件名分析完成事件"""
        high_risk = event.classification.get("high_risk", [])

        for file_path in high_risk:
            # 1. 提取文件
            extracted = await registry.get("file.extract_from_layer")(
                event.layer_id, file_path, "./files"
            )

            # 2. 读取内容
            content = await registry.get("file.read_content")(extracted)

            # 3. 扫描凭证
            credentials = await self.content_scanner.scan(file_path, content)

            # 4. 发布凭证发现事件
            for cred in credentials:
                await self.event_bus.publish(CredentialFoundEvent(
                    task_id=event.task_id,
                    credential=cred
                ))
```

### 验收标准

- [ ] 事件总线可发布和订阅事件
- [ ] 主 Agent 可制定计划并分发任务
- [ ] 执行 Agent 可处理层和文件
- [ ] Agent 间通过事件正确通信

---

## 阶段 6: CLI 界面层

### 目标
实现命令行界面

### 步骤

#### 6.1 CLI 入口

**文件**: `imagescan/cli/main.py`

```python
import typer
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn

app = typer.Typer()
console = Console()

@app.command()
def scan(
    image_name: str = typer.Argument(..., help="Docker image name (e.g., nginx:latest)")
):
    """扫描 Docker 镜像中的敏感凭证"""
    from ..agents.master_agent import MasterAgent
    from ..core.event_bus import EventBus
    from ..utils.config import Config
    from ..utils.database import Database
    from ..utils.logger import setup_logging, get_logger

    # 加载配置
    config = Config.load()
    setup_logging(
        level=config.system.log_level,
        log_format=config.system.log_format
    )
    logger = get_logger(__name__)

    # 初始化数据库
    db = Database(config.storage.database_path)
    await db.init()

    # 创建任务
    task = ScanTask(image_name=image_name, image_id="...")
    task_id = await db.insert_task(task)

    console.print(f"✅ Task created: {task_id}")

    # 启动 Agent 系统
    event_bus = EventBus()

    # 启动进度显示
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("Files: {task.fields[files]}"),
        TextColumn("Credentials: {task.fields[creds]}")
    ) as progress:

        task_progress = progress.add_task(
            "Scanning...",
            total=100,
            files=0,
            creds=0
        )

        # 订阅进度
        async def on_progress(event):
            progress.update(
                task_progress,
                completed=event.processed_files / event.total_files * 100,
                files=f"{event.processed_files}/{event.total_files}",
                creds=event.credentials_found
            )

        event_bus.subscribe("progress.update", on_progress)

        # 启动主 Agent
        master = MasterAgent(event_bus, llm_client, task_id, image_name)
        await master.run()

    console.print("✅ Scan completed!")

@app.command()
def history():
    """查看扫描历史"""
    console.print("History command")

@app.command()
def config():
    """查看/修改配置"""
    console.print("Config command")

@app.command()
def verify(credential_id: str):
    """验证凭证"""
    console.print(f"Verify: {credential_id}")

if __name__ == "__main__":
    app()
```

#### 6.2 命令注册

**文件**: `setup.py`

```python
from setuptools import setup

setup(
    name="imagescan-agent",
    version="1.0.0",
    packages=["imagescan"],
    install_requires=[
        "fastapi==0.104.1",
        "uvicorn==0.24.0",
        "typer==0.9.0",
        "rich==13.7.0",
        # ... 其他依赖
    ],
    entry_points={
        "console_scripts": [
            "imagescan=imagescan.cli.main:app"
        ]
    }
)
```

### 验收标准

- [ ] `imagescan scan nginx:latest` 可执行
- [ ] 进度条正确显示
- [ ] 命令可正常退出

---

## 阶段 7-10: 后续阶段

（由于篇幅限制，后续阶段简要列出）

### 阶段 7: API 服务层
- FastAPI 端点实现
- WebSocket 实时通信
- API 文档生成

### 阶段 8: Web UI 层
- Next.js 项目初始化
- 页面组件开发
- API 集成

### 阶段 9: 测试与优化
- 单元测试 (pytest)
- 集成测试
- 性能优化

### 阶段 10: 部署与文档
- Docker 镜像构建
- Docker Compose 配置
- 用户文档编写

---

## 总结

本实施计划详细描述了从环境准备到最终部署的完整构建序列。**每个阶段都有明确的步骤和验收标准**，确保开发过程可追踪、可验证。

**关键里程碑**:
- 阶段 0-2: 基础设施和工具 ✅
- 阶段 3-5: 数据层、LLM、Agent 核心 ✅
- 阶段 6: MVP CLI 完成 ✅
- 阶段 7-10: 完整系统和部署

---

**文档结束**
