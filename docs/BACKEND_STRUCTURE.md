# ImageScan-Agent 后端结构文档 (BACKEND_STRUCTURE)

## 文档信息

- **项目名称**: ImageScan-Agent
- **文档版本**: 1.0.0
- **最后更新**: 2025-03-01
- **文档状态**: 完整版（数据模型、API端点、存储架构）

---

## 1. 数据模型

### 1.1 核心数据实体

#### 1.1.1 ScanTask（扫描任务）

```python
class ScanTask(BaseModel):
    """扫描任务模型"""
    task_id: str                    # UUID，唯一标识
    image_name: str                 # 镜像名称（如 "nginx:latest"）
    image_id: str                   # 镜像 SHA256
    status: ScanStatus              # 扫描状态
    created_at: datetime            # 创建时间
    started_at: Optional[datetime]  # 开始时间
    completed_at: Optional[datetime] # 完成时间
    error_message: Optional[str]    # 错误信息
    total_layers: int               # 总层数
    processed_layers: int           # 已处理层数
    total_files: int                # 总文件数
    processed_files: int            # 已处理文件数
    credentials_found: int          # 发现凭证数
```

**ScanStatus 枚举**:
```python
class ScanStatus(str, Enum):
    PENDING = "pending"           # 等待执行
    RUNNING = "running"           # 执行中
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败
    CANCELLED = "cancelled"       # 已取消
```

#### 1.1.2 Credential（凭证）

```python
class Credential(BaseModel):
    """凭证模型"""
    credential_id: str            # UUID
    task_id: str                  # 关联扫描任务
    cred_type: CredentialType     # 凭证类型
    confidence: float             # 置信度 (0.0 - 1.0)
    file_path: str                # 文件路径
    line_number: Optional[int]    # 行号
    layer_id: str                 # 所在层 ID
    context: str                  # 上下文（脱敏后）
    raw_value: Optional[str]      # 原始值（加密存储）
    validation_status: ValidationStatus # 验证状态
    verified_at: Optional[datetime]    # 验证时间
    metadata: Dict[str, Any]      # 额外元数据
```

**CredentialType 枚举**:
```python
class CredentialType(str, Enum):
    API_KEY = "api_key"                    # API Key
    PASSWORD = "password"                  # 密码
    TOKEN = "token"                        # Token (JWT, OAuth等)
    CERTIFICATE = "certificate"            # 证书
    PRIVATE_KEY = "private_key"            # 私钥
    DATABASE_URL = "database_url"          # 数据库连接串
    AWS_KEY = "aws_key"                    # AWS凭证
    SSH_KEY = "ssh_key"                    # SSH密钥
    UNKNOWN = "unknown"                    # 未知类型
```

**ValidationStatus 枚举**:
```python
class ValidationStatus(str, Enum):
    PENDING = "pending"           # 待验证
    VALID = "valid"               # 有效
    INVALID = "invalid"           # 无效
    UNKNOWN = "unknown"           # 无法确定
    SKIPPED = "skipped"           # 跳过验证
```

#### 1.1.3 ScanLayer（扫描层）

```python
class ScanLayer(BaseModel):
    """镜像层模型"""
    layer_id: str                 # 层 SHA256
    task_id: str                  # 关联扫描任务
    layer_index: int              # 层序号（从0开始）
    size_bytes: int               # 层大小（字节）
    file_count: int               # 文件数
    sensitive_files: int          # 敏感文件数
    credentials_found: int        # 发现凭证数
    processed: bool               # 是否已处理
```

#### 1.1.4 ScanMetadata（扫描元数据）

```python
class ScanMetadata(BaseModel):
    """扫描元数据"""
    task_id: str                  # 任务 ID
    image_name: str               # 镜像名称
    image_id: str                 # 镜像 ID
    scanner_version: str          # 扫描器版本
    scan_duration_seconds: float  # 扫描耗时（秒）
    total_size_bytes: int         # 镜像总大小
    layers_scanned: int           # 扫描层数
    files_scanned: int            # 扫描文件数
    credentials_found: int        # 发现凭证数
    false_positive_count: int     # 误报数（人工标注后）
    statistics: ScanStatistics    # 统计信息
```

#### 1.1.5 ScanStatistics（统计信息）

```python
class ScanStatistics(BaseModel):
    """扫描统计"""
    confidence_distribution: Dict[str, int]  # 置信度分布
    credential_type_distribution: Dict[str, int] # 类型分布
    layer_distribution: Dict[str, int]      # 层分布
    high_risk_count: int                    # 高风险凭证数
    medium_risk_count: int                  # 中风险凭证数
    low_risk_count: int                     # 低风险凭证数
    comparison_with_trufflehog: Optional[Dict[str, Any]] # 与TruffleHog对比
```

---

## 2. SQLite 数据库模式

### 2.1 表结构

#### 2.1.1 scan_tasks 表

```sql
CREATE TABLE scan_tasks (
    task_id TEXT PRIMARY KEY,
    image_name TEXT NOT NULL,
    image_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- ScanStatus
    created_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    total_layers INTEGER NOT NULL DEFAULT 0,
    processed_layers INTEGER NOT NULL DEFAULT 0,
    total_files INTEGER NOT NULL DEFAULT 0,
    processed_files INTEGER NOT NULL DEFAULT 0,
    credentials_found INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_scan_tasks_status ON scan_tasks(status);
CREATE INDEX idx_scan_tasks_created_at ON scan_tasks(created_at);
```

#### 2.1.2 credentials 表

```sql
CREATE TABLE credentials (
    credential_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    cred_type TEXT NOT NULL,  -- CredentialType
    confidence REAL NOT NULL,
    file_path TEXT NOT NULL,
    line_number INTEGER,
    layer_id TEXT NOT NULL,
    context TEXT NOT NULL,
    raw_value BLOB,  -- 加密存储
    validation_status TEXT NOT NULL,  -- ValidationStatus
    verified_at TIMESTAMP,
    metadata TEXT,  -- JSON
    FOREIGN KEY (task_id) REFERENCES scan_tasks(task_id) ON DELETE CASCADE
);

CREATE INDEX idx_credentials_task_id ON credentials(task_id);
CREATE INDEX idx_credentials_type ON credentials(cred_type);
CREATE INDEX idx_credentials_confidence ON credentials(confidence);
CREATE INDEX idx_credentials_layer_id ON credentials(layer_id);
```

#### 2.1.3 scan_layers 表

```sql
CREATE TABLE scan_layers (
    layer_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    layer_index INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    sensitive_files INTEGER NOT NULL DEFAULT 0,
    credentials_found INTEGER NOT NULL DEFAULT 0,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (task_id) REFERENCES scan_tasks(task_id) ON DELETE CASCADE
);

CREATE INDEX idx_scan_layers_task_id ON scan_layers(task_id);
CREATE INDEX idx_scan_layers_processed ON scan_layers(processed);
```

#### 2.1.4 scan_metadata 表

```sql
CREATE TABLE scan_metadata (
    task_id TEXT PRIMARY KEY,
    image_name TEXT NOT NULL,
    image_id TEXT NOT NULL,
    scanner_version TEXT NOT NULL,
    scan_duration_seconds REAL NOT NULL,
    total_size_bytes INTEGER NOT NULL,
    layers_scanned INTEGER NOT NULL,
    files_scanned INTEGER NOT NULL,
    credentials_found INTEGER NOT NULL,
    false_positive_count INTEGER NOT NULL DEFAULT 0,
    statistics TEXT NOT NULL,  -- JSON
    FOREIGN KEY (task_id) REFERENCES scan_tasks(task_id) ON DELETE CASCADE
);
```

#### 2.1.5 knowledge_entries 表（RAG）

```sql
CREATE TABLE knowledge_entries (
    entry_id TEXT PRIMARY KEY,
    entry_type TEXT NOT NULL,  -- 'case' or 'pattern'
    content TEXT NOT NULL,     -- 向量化内容
    embedding BLOB,            -- 向量（ChromaDB存储）
    metadata TEXT,             -- JSON（置信度、误报标记等）
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_knowledge_entries_type ON knowledge_entries(entry_type);
```

### 2.2 数据库关系图

```
┌─────────────────┐
│   scan_tasks    │
└────────┬────────┘
         │ 1:N
         ├─────────────────┐
         │                 │
    ┌────▼────┐      ┌────▼──────┐
    │credentials│    │scan_layers│
    └─────────┘      └───────────┘
         │
         │ 1:1
    ┌────▼──────┐
    │scan_metadata│
    └───────────┘

┌────────────────┐
│knowledge_entries│ (独立表，用于RAG)
└────────────────┘
```

---

## 3. ChromaDB 向量数据库模式

### 3.1 Collection 结构

#### 3.1.1 historical_cases Collection

```python
{
    "collection_name": "historical_cases",
    "metadata": {
        "description": "历史扫描案例库",
        "embedding_model": "all-MiniLM-L6-v2"
    },
    "schema": {
        "document": "案例描述（文本）",
        "embedding": "向量表示（自动生成）",
        "metadata": {
            "task_id": "扫描任务ID",
            "file_path": "文件路径",
            "cred_type": "凭证类型",
            "is_true_positive": "是否真阳性（人工标注）",
            "confidence": "置信度",
            "created_at": "创建时间"
        }
    }
}
```

#### 3.1.2 credential_patterns Collection

```python
{
    "collection_name": "credential_patterns",
    "metadata": {
        "description": "凭证模式库",
        "embedding_model": "all-MiniLM-L6-v2"
    },
    "schema": {
        "document": "模式描述（文本）",
        "embedding": "向量表示（自动生成）",
        "metadata": {
            "pattern_type": "模式类型（如 AWS Key、JWT等）",
            "regex_pattern": "正则表达式",
            "confidence_threshold": "置信度阈值",
            "source": "来源（手动/自动学习）",
            "created_at": "创建时间"
        }
    }
}
```

### 3.2 向量检索流程

```
输入: 待检测文件内容
  ↓
生成向量 (sentence-transformers)
  ↓
查询 ChromaDB (historical_cases + credential_patterns)
  ↓
返回: 相似历史案例 + 匹配模式
  ↓
Agent 综合判断
```

---

## 4. API 端点设计

### 4.1 扫描任务 API

#### 4.1.1 创建扫描任务

```http
POST /api/v1/scan/tasks
Content-Type: application/json

{
    "image_name": "nginx:latest",
    "scan_options": {
        "max_layers": 100,
        "max_files": 10000,
        "enable_verification": true
    }
}
```

**响应**:
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "created_at": "2025-03-01T12:00:00Z"
}
```

#### 4.1.2 获取任务状态

```http
GET /api/v1/scan/tasks/{task_id}
```

**响应**:
```json
{
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "running",
    "progress": {
        "total_layers": 5,
        "processed_layers": 3,
        "total_files": 1250,
        "processed_files": 800,
        "credentials_found": 2
    }
}
```

#### 4.1.3 列出历史任务

```http
GET /api/v1/scan/tasks?status=completed&limit=10&offset=0
```

**响应**:
```json
{
    "total": 100,
    "items": [
        {
            "task_id": "...",
            "image_name": "nginx:latest",
            "status": "completed",
            "created_at": "2025-03-01T12:00:00Z",
            "credentials_found": 5
        }
    ]
}
```

#### 4.1.4 取消任务

```http
POST /api/v1/scan/tasks/{task_id}/cancel
```

### 4.2 凭证结果 API

#### 4.2.1 获取任务凭证列表

```http
GET /api/v1/scan/tasks/{task_id}/credentials?limit=50&offset=0
```

**响应**:
```json
{
    "total": 25,
    "items": [
        {
            "credential_id": "...",
            "cred_type": "api_key",
            "confidence": 0.95,
            "file_path": "/app/config.json",
            "line_number": 10,
            "context": "AWS_ACCESS_KEY: AKIA***QAZ",
            "validation_status": "valid"
        }
    ]
}
```

#### 4.2.2 获取凭证详情

```http
GET /api/v1/credentials/{credential_id}
```

#### 4.2.3 更新验证状态

```http
PATCH /api/v1/credentials/{credential_id}/validation
Content-Type: application/json

{
    "validation_status": "invalid",
    "user_note": "已过期凭证"
}
```

### 4.3 扫描结果 API

#### 4.3.1 获取完整报告（JSON）

```http
GET /api/v1/scan/tasks/{task_id}/report
```

**响应**:
```json
{
    "metadata": {
        "task_id": "...",
        "image_name": "nginx:latest",
        "scanner_version": "1.0.0",
        "scan_duration_seconds": 125.5
    },
    "credentials": [...],
    "statistics": {
        "high_risk_count": 3,
        "medium_risk_count": 10,
        "low_risk_count": 12
    }
}
```

#### 4.3.2 下载报告文件

```http
GET /api/v1/scan/tasks/{task_id}/report/download
```

**响应**: 文件下载（`results.json`）

### 4.4 配置管理 API

#### 4.4.1 获取配置

```http
GET /api/v1/config
```

**响应**:
```json
{
    "filter_rules": {
        "prefix_exclude": ["/usr", "/lib", "/bin"]
    },
    "scan_parameters": {
        "confidence_threshold": 0.7,
        "max_file_size_mb": 10
    }
}
```

#### 4.4.2 更新配置

```http
PATCH /api/v1/config
Content-Type: application/json

{
    "scan_parameters": {
        "confidence_threshold": 0.8
    }
}
```

### 4.5 知识库 API

#### 4.5.1 添加知识条目

```http
POST /api/v1/knowledge/entries
Content-Type: application/json

{
    "entry_type": "case",
    "content": "发现 AWS_ACCESS_KEY_ID 格式的凭证",
    "metadata": {
        "cred_type": "aws_key",
        "is_true_positive": true
    }
}
```

#### 4.5.2 搜索相似案例

```http
POST /api/v1/knowledge/search
Content-Type: application/json

{
    "query": "配置文件中的 API Key",
    "collection": "historical_cases",
    "top_k": 5
}
```

### 4.6 WebSocket API（实时进度）

#### 4.6.1 订阅任务进度

```javascript
// WebSocket 连接
const ws = new WebSocket(`ws://localhost:8000/ws/scan/tasks/{task_id}`);

// 接收进度更新
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // {
    //   "type": "progress",
    //   "data": {
    //     "layer_id": "...",
    //     "file_path": "...",
    //     "credentials_found": 3
    //   }
    // }
};
```

---

## 5. 文件存储结构

### 5.1 输出目录结构

```
output/
├── {timestamp}/                    # 时间戳目录（如 20250301_120000）
│   └── {image_name}/               # 镜像名称（如 nginx_latest）
│   │   ├── results.json            # 完整扫描结果
│   │   ├── metadata.json           # 元数据
│   │   ├── files/                  # 提取的敏感文件
│   │   │   ├── layer_{id}/
│   │   │   │   ├── config.json
│   │   │   │   └── .env
│   │   │   └── ...
│   │   └── errors.log              # 错误日志
└── ...
```

### 5.2 results.json 格式

```json
{
    "version": "1.0.0",
    "metadata": {
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "image_name": "nginx:latest",
        "image_id": "sha256:abc123...",
        "scanner_version": "1.0.0",
        "scan_duration_seconds": 125.5,
        "total_size_bytes": 134217728,
        "created_at": "2025-03-01T12:00:00Z",
        "completed_at": "2025-03-01T12:02:05Z"
    },
    "layers": [
        {
            "layer_id": "sha256:def456...",
            "layer_index": 0,
            "size_bytes": 5242880,
            "credentials_found": 2
        }
    ],
    "credentials": [
        {
            "credential_id": "...",
            "cred_type": "api_key",
            "confidence": 0.95,
            "file_path": "/app/config.json",
            "line_number": 10,
            "layer_id": "sha256:def456...",
            "context": "AWS_ACCESS_KEY: AKIA***QAZ",
            "validation_status": "valid"
        }
    ],
    "statistics": {
        "confidence_distribution": {
            "high": 5,
            "medium": 10,
            "low": 10
        },
        "credential_type_distribution": {
            "api_key": 8,
            "password": 7,
            "token": 10
        },
        "high_risk_count": 5,
        "medium_risk_count": 10,
        "low_risk_count": 10
    },
    "errors": [
        {
            "layer_id": "sha256:...",
            "error_type": "ExtractionError",
            "message": "Failed to extract layer",
            "timestamp": "2025-03-01T12:01:30Z"
        }
    ]
}
```

---

## 6. 配置文件结构

### 6.1 config.toml 格式

```toml
# API 配置
[api]
gemini_api_key = "${GEMINI_API_KEY}"  # 从环境变量读取
base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
model = "gemini-2.5-flash"
timeout_seconds = 60

# 过滤规则
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

# 扫描参数
[scan_parameters]
confidence_threshold = 0.7
max_file_size_mb = 10
max_layers = 100
enable_verification = true
verification_mode = "static"  # static or manual

# 系统配置
[system]
log_level = "INFO"  # DEBUG, INFO, WARNING, ERROR
log_format = "json"  # json or text
log_rotation_days = 7
max_workers = 4

# 存储配置
[storage]
output_path = "./output"
database_path = "./data/scanner.db"
chromadb_path = "./data/chromadb"

# RAG 配置
[rag]
enabled = true
embedding_model = "all-MiniLM-L6-v2"
similarity_threshold = 0.8
top_k_results = 5
```

---

## 7. Agent 通信协议

### 7.1 事件总线消息格式

#### 7.1.1 任务创建事件

```python
class TaskCreatedEvent(BaseModel):
    """任务创建事件"""
    event_type: Literal["task.created"]
    task_id: str
    image_name: str
    timestamp: datetime
```

#### 7.1.2 进度更新事件

```python
class ProgressUpdateEvent(BaseModel):
    """进度更新事件"""
    event_type: Literal["progress.update"]
    task_id: str
    layer_id: str
    file_path: str
    processed_files: int
    total_files: int
    credentials_found: int
    timestamp: datetime
```

#### 7.1.3 凭证发现事件

```python
class CredentialFoundEvent(BaseModel):
    """凭证发现事件"""
    event_type: Literal["credential.found"]
    task_id: str
    credential: Credential
    timestamp: datetime
```

#### 7.1.4 任务完成事件

```python
class TaskCompletedEvent(BaseModel):
    """任务完成事件"""
    event_type: Literal["task.completed"]
    task_id: str
    status: ScanStatus
    credentials_count: int
    duration_seconds: float
    timestamp: datetime
```

### 7.2 事件处理流程

```
主 Agent (事件发布者)
  ↓
  发布事件到 asyncio.Queue
  ↓
从 Agent (事件订阅者)
  ├─ 执行 Agent → 扫描操作 → 发布进度事件
  ├─ 验证 Agent → 验证操作 → 发布凭证事件
  ├─ 知识 Agent → 查询操作 → 发布知识事件
  └─ 研判 Agent → 评估操作 → 发布结果事件
  ↓
主 Agent (事件聚合者)
  ↓
  更新数据库状态
  ↓
  通知客户端（WebSocket + CLI）
```

---

## 8. 错误处理

### 8.1 错误类型定义

```python
class ImageScanError(Exception):
    """基础错误类"""
    code: str
    message: str
    details: Optional[Dict[str, Any]]

class ImageNotFoundError(ImageScanError):
    """镜像不存在"""
    code = "IMAGE_NOT_FOUND"

class LayerExtractionError(ImageScanError):
    """层提取失败"""
    code = "LAYER_EXTRACTION_ERROR"

class CredentialValidationError(ImageScanError):
    """凭证验证失败"""
    code = "CREDENTIAL_VALIDATION_ERROR"

class LLMTimeoutError(ImageScanError):
    """LLM 超时"""
    code = "LLM_TIMEOUT"
```

### 8.2 错误响应格式

```json
{
    "error": {
        "code": "IMAGE_NOT_FOUND",
        "message": "Docker image 'nginx:xxx' not found",
        "details": {
            "image_name": "nginx:xxx",
            "available_images": ["nginx:latest", "nginx:alpine"]
        },
        "timestamp": "2025-03-01T12:00:00Z"
    }
}
```

---

## 9. 安全考虑

### 9.1 敏感数据加密

**凭证原始值加密存储**:
```python
from cryptography.fernet import Fernet

def encrypt_credential(value: str, key: bytes) -> bytes:
    """加密凭证原始值"""
    f = Fernet(key)
    return f.encrypt(value.encode())

def decrypt_credential(encrypted: bytes, key: bytes) -> str:
    """解密凭证原始值"""
    f = Fernet(key)
    return f.decrypt(encrypted).decode()
```

### 9.2 API 认证

**未来可选**: 添加 API Key 认证
```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key
```

---

**文档结束**
