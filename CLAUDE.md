# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Last Updated**: 2026-03-09
**Project Status**: v2.0.0 (ScanAgent 重构版 - 阶段 4 完成)
**Code Scale**: ~14,825 lines of Python code

---

## 项目概述

**项目名称**: ImageScan-Agent

**核心价值**: 智能化 + 准确性

**目标用户**: 开源社区

**项目定位**: 基于 Google Gemini 2.5 Flash LLM 的 Docker 镜像敏感凭证扫描智能体系统

**核心特性**:
- 单一智能体自主规划（非主从模式）
- LLM 工具调用能力
- 事件驱动架构
- 工具返回值标准化
- 隔离上下文设计

---

## 架构设计（单一智能体模式）

### Agent 架构

```
ScanAgent (单一智能体)
  ├── 自主规划扫描流程
  │   └── LLM 动态规划扫描步骤
  │
  ├── LLM 工具调用能力
  │   ├── Docker 工具（保存、检查镜像）
  │   ├── Tar 工具（解压、分析文件）
  │   └── File 工具（扫描凭证）
  │
  ├── 动态决策与调整
  │   ├── 最大 30 步迭代
  │   ├── 重复调用检测
  │   └── 上下文压缩（429 错误时）
  │
  └── 事件驱动通信
      └── 发布进度、凭证、完成等事件
```

### 设计优势

| 特性 | 优势 |
|------|------|
| **单一智能体** | 简化架构，减少通信开销 |
| **LLM 工具调用** | 真正的智能体自主规划能力 |
| **事件驱动** | 解耦通信，支持实时反馈 |
| **上下文隔离** | 工具层独立 LLM 调用，避免 Token 超限 |
| **标准化返回** | 零硬编码，易于扩展 |

### 通信机制

- **事件总线**: `asyncio.Queue` (发布/订阅模式)
- **事件类型**: 15 种（TaskCreated, ProgressUpdate, CredentialFound, TaskCompleted 等）
- **实时反馈**:
  - CLI: Rich Progress 进度条
  - Web: WebSocket 连接（实时推送）

---

## 项目结构

```
imagescan/
├── core/                    # 核心抽象类
│   ├── agent.py            # Agent 基类（325 行）
│   ├── event_bus.py        # 事件总线（387 行）
│   ├── events.py           # 事件定义（279 行）
│   ├── llm_client.py       # LLM 客户端（443 行）
│   └── orchestrator.py     # 扫描编排器（229 行）
│
├── agents/                 # Agent 实现
│   └── scan_agent.py       # ScanAgent（804 行）
│       ├── 两阶段执行（准备 + 执行）
│       ├── LLM 工具调用
│       ├── 动态决策
│       └── 上下文压缩
│
├── tools/                  # 工具注册与实现
│   ├── registry.py         # 工具注册表（200 行）
│   ├── docker_tools.py     # Docker 工具（402 行）
│   ├── tar_tools.py        # Tar 工具（831 行）
│   └── file_tools.py       # File 工具（543 行）
│
├── storage/                # 存储管理
│   └── simple_storage.py   # 内存存储管理器（372 行）
│       ├── SimpleStorageManager
│       ├── CredentialRecord
│       └── ScanStatistics
│
├── models/                 # 数据模型
│   ├── task.py             # 扫描任务模型（93 行）
│   └── credential.py       # 凭证模型（134 行）
│
├── api/                    # FastAPI 后端
│   ├── main.py             # 应用入口（135 行）
│   ├── routes/             # API 路由
│   │   ├── scan.py         # 扫描 API
│   │   ├── chat.py         # 聊天 API
│   │   └── events.py       # 事件 API
│   ├── websocket/          # WebSocket
│   │   └── manager.py      # 连接管理器
│   └── models/             # API 数据模型
│
├── cli/                    # 命令行界面
│   └── main.py             # CLI 入口（501 行）
│       ├── scan 子命令
│       ├── history 子命令
│       ├── config 子命令
│       └── verify 子命令
│
├── utils/                  # 工具函数
│   ├── config.py           # 配置管理
│   ├── logger.py           # 日志系统
│   ├── database.py         # 数据库操作
│   ├── rules.py            # 规则引擎
│   └── summary.py          # 摘要管理器
│
└── tests/                  # 测试
    ├── unit/
    └── integration/

frontend/                   # Next.js 前端
├── app/                    # Next.js App Router
│   ├── page.tsx            # 主页面
│   └── layout.tsx          # 布局
├── components/             # React 组件
│   ├── ScanInput.tsx       # 扫描输入
│   ├── ScanResults.tsx     # 结果展示
│   ├── ScanProgress.tsx    # 进度条
│   ├── EventLog.tsx        # 事件日志
│   ├── ScanHistory.tsx     # 扫描历史
│   └── ScanInterface.tsx   # 扫描界面
├── hooks/                  # React Hooks
│   └── useWebSocket.ts     # WebSocket 连接
└── types/                  # TypeScript 类型
    └── scan.ts             # 扫描类型

docs/                       # 项目文档
├── PRD.md                  # 产品需求文档
├── TECH_STACK.md           # 技术栈文档
├── BACKEND_STRUCTURE.md    # 后端结构文档
├── APP_FLOW.md             # 应用流程文档
└── IMPLEMENTATION_PLAN.md  # 实施计划文档
```

---

## 开发环境配置

### 必需软件

| 软件 | 版本 | 安装方式 |
|------|------|----------|
| Python | 3.11.8 | `pyenv install 3.11.8` |
| Node.js | 20.10.0 (LTS) | `nvm install 20.10.0` |
| Docker | 24.0.7+ | 官方安装包 |

### 环境变量

创建 `.env` 文件：

```bash
# Gemini API
GEMINI_API_KEY=your_gemini_api_key_here

# 路径配置
IMAGE_TAR_PATH=./image_tar
FILES_PATH=./files
OUTPUT_PATH=./output
DATA_PATH=./data

# 日志配置
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### 配置文件

**config.toml** (单一配置文件)：

```toml
[api]
gemini_api_key = "${GEMINI_API_KEY}"
base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
model = "gemini-2.5-flash"
timeout_seconds = 60

[filter_rules]
prefix_exclude = ["/usr", "/lib", "/bin", "/etc/ssl", "/var/lib"]
low_probability_keywords = ["node_modules", ".git", "__pycache__"]

[scan_parameters]
confidence_threshold = 0.7
max_file_size_mb = 10
max_layers = 100
max_steps = 30
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

---

## 运行应用

### CLI 命令

```bash
# 扫描镜像（支持并发）
imagescan scan nginx:latest
imagescan scan nginx:latest alpine:latest --concurrent 2
imagescan scan nginx:latest --verbose --debug

# 查看历史
imagescan history
imagescan history --limit 10 --verbose

# 配置管理
imagescan config --show
imagescan config --edit

# 验证凭证
imagescan verify <task_id>
imagescan verify <task_id> --revalidate
```

### API 服务

```bash
# 启动 FastAPI 服务
uvicorn imagescan.api.main:app --reload --port 8000

# API 文档
open http://localhost:8000/docs
```

### Web UI

```bash
cd frontend
npm install
npm run dev

# 访问
open http://localhost:3000
```

---

## 关键设计决策

### 技术选型

| 决策 | 理由 |
|------|------|
| Python 3.11 | 严格锁定，兼容性最佳 |
| 仅用 Gemini 2.5 Flash | 成本低，速度快 |
| 单一 ScanAgent | 简化架构，真正的智能体自主规划 |
| 事件驱动 | 解耦通信，异步高效 |
| SimpleStorageManager (内存) | MVP 阶段快速迭代 |

### 错误处理

**分级处理**:
- 非致命错误：跳过继续
- 致命错误：快速失败
- Agent 内部错误：隔离失败
- 所有错误：记录到 JSON 报告

### 性能要求

- 扫描速度: < 5 分钟/GB
- 内存占用: < 2GB（中等规模镜像）
- 异步处理：asyncio
- 并发扫描：支持多镜像并发

### 工具返回值标准化架构

**核心原则**: 所有工具必须返回统一的 `{success, data, summary}` 格式，消除 Agent 层的硬编码逻辑。

#### 标准返回格式

```python
# 成功情况
return {
    "success": True,
    "data": {...},           # 实际数据
    "summary": "✅ 操作成功"  # 或 ["行1", "行2"] 用于多行输出
}

# 失败情况
return {
    "success": False,
    "error": "错误原因",
    "summary": "❌ 操作失败：错误原因"
}
```

#### 架构优势

1. **零硬编码**: Agent 使用通用的 `_format_tool_result()` 方法，自动提取 `summary` 字段
2. **上下文隔离**: 工具层负责所有业务逻辑和 LLM 调用，Agent 只负责编排
3. **易于扩展**: 新工具只需返回 `summary` 字段，无需修改 Agent 代码
4. **Token 优化**: 主对话只保留摘要，详细数据存储在 Storage 中

#### 已实现的标准工具

| 工具 | 功能 | 返回值 |
|------|------|--------|
| `docker.save` | 保存镜像为 tar | `{success, data: {tar_path, size_mb}, summary}` |
| `docker.exists` | 检查镜像是否存在 | `{success, data: {exists}, summary}` |
| `docker.inspect` | 获取镜像详细信息 | `{success, data: {manifest}, summary}` |
| `docker.list_images` | 列出本地所有镜像 | `{success, data: {images}, summary}` |
| `docker.pull` | 拉取镜像 | `{success, data: {image}, summary}` |
| `tar.unpack` | 解压镜像 tar | `{success, data: {manifest, layers_count}, summary}` |
| `tar.list_layers` | 列出镜像层 | `{success, data: {layers}, summary}` |
| `tar.extract_files` | 批量提取文件 | `{success, data: {files}, summary}` |
| `tar.analyze_all_layer_files` | 分析文件名（隔离 LLM） | `{success, data: {suspicious_files}, summary: [...]}` |
| `tar.extract_files_from_layers` | 从多层批量提取 | `{success, data: {files}, summary}` |
| `file.extract_from_layer` | 从层中提取文件 | `{success, data: {file_path}, summary}` |
| `file.exists` | 检查文件是否存在 | `{success, data: {exists}, summary}` |
| `file.get_size` | 获取文件大小 | `{success, data: {size_mb}, summary}` |
| `file.analyze_contents` | 分析文件内容（隔离 LLM） | `{success, data: {credentials}, summary: [...]}` |

#### 新工具开发规范

创建新工具时，必须：

1. 返回标准格式 `{success, data, summary}`
2. 在 `summary` 字段中提供人类可读的结果摘要
3. 多行输出使用列表格式 `["行1", "行2"]`
4. 错误情况包含 `error` 字段和 `summary` 字段

```python
@registry.register("tool.name", description="...")
async def my_tool(param: str) -> Dict[str, Any]:
    try:
        # 业务逻辑
        result = await do_something(param)
        return {
            "success": True,
            "data": result,
            "summary": f"✅ 操作完成：{param}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "summary": f"❌ 操作失败：{e}"
        }
```

---

## 数据流

### 扫描流程

```
用户输入 (镜像名称)
  ↓
Orchestrator 初始化依赖
  ├─ LLMClient
  ├─ ToolRegistry
  └─ SimpleStorageManager
  ↓
创建 ScanAgent
  ↓
两阶段执行
  ├─ 准备阶段：生成扫描计划（LLM）
  └─ 执行阶段：按计划执行（最多 30 步）
      ├─ LLM 决定调用哪个工具
      ├─ 工具返回结果（标准格式）
      ├─ Agent 格式化结果为摘要
      ├─ 根据结果动态调整策略
      └─ 重复直到完成或达到最大步数
  ↓
收集结果并保存 JSON
  ↓
发布完成事件
  ↓
结果输出 (JSON + 终端 + WebSocket)
```

### 事件流

```
ScanAgent 发布事件
  ↓
EventBus 分发
  ├─ CLI 订阅者：更新进度条
  ├─ WebSocket 订阅者：推送到前端
  └─ 其他订阅者：日志、统计等
  ↓
前端实时更新
  ├─ ScanProgress：进度条
  ├─ EventLog：事件日志
  └─ ScanResults：结果展示
```

---

## 数据存储

### 当前架构（MVP 阶段）

**SimpleStorageManager**: 内存存储方案

```python
# 扫描统计
ScanStatistics:
  - total_layers: int
  - processed_layers: int
  - total_files: int
  - scanned_files: int
  - filtered_files: int
  - high_confidence: int
  - medium_confidence: int
  - low_confidence: int

# 凭证记录
CredentialRecord:
  - credential_id: str
  - task_id: str
  - cred_type: CredentialType
  - confidence: float
  - file_path: str
  - line_number: Optional[int]
  - layer_id: Optional[str]
  - context: Optional[str]
  - raw_value: Optional[str]
  - validation_status: ValidationStatus
  - verified_at: Optional[datetime]
  - metadata: Dict[str, Any]
```

### 输出格式

```
output/
└── {task_id}/
    └── result.json          # 扫描结果（完整 JSON）
        ├── task_info        # 任务信息
        ├── statistics       # 扫描统计
        ├── credentials      # 凭证列表
        └── metadata         # 元数据
```

### 扩展计划（待实现）

**阶段 2: SQLite 持久化**
- `scan_tasks` - 扫描任务
- `credentials` - 凭证记录
- `scan_layers` - 镜像层
- `scan_metadata` - 扫描元数据

**阶段 3: ChromaDB 向量检索（RAG）**
- `historical_cases` - 历史案例库
- `credential_patterns` - 凭证模式库
- `knowledge_entries` - RAG 知识库

---

## MVP 范围（最小可行产品）

### 核心功能（已实现）

1. ✅ 镜像解压
2. ✅ 智能文件筛选
3. ✅ 内容扫描
4. ✅ 结果输出
5. ✅ CLI 命令
6. ✅ Web UI（基础功能）
7. ✅ WebSocket 实时通信
8. ✅ 并发扫描

### 验收标准

- **功能可用**: 能够扫描本地 Docker 镜像并输出 JSON ✅
- **性能基准**: 扫描速度 < 5 分钟/GB ✅
- **智能体能力**: LLM 自主规划和工具调用 ✅

### 迭代路线（渐进增强）

```
✅ MVP v1.0 (CLI + 基本扫描)
  ↓
✅ MVP v2.0 (单一智能体 + 工具标准化)
  ↓
🔄 阶段 2: SQLite 持久化存储
  ↓
⏳ 阶段 3: ChromaDB 向量检索（RAG）
  ↓
⏳ 阶段 4: 完整凭证验证
  ↓
⏳ 阶段 5: 高级功能（模式学习、智能过滤）
```

---

## 用户界面

### CLI（子命令结构）

- `imagescan scan <image>` - 扫描镜像（支持并发）
- `imagescan history` - 查看历史记录
- `imagescan config` - 查看/修改配置
- `imagescan verify <task_id>` - 验证凭证

**特性**:
- Rich 进度条（实时更新）
- 彩色输出（凭证分级显示）
- 并发扫描支持
- 详细调试模式

### Web UI（轻量级控制台）

**功能范围**:
- 扫描输入（支持多镜像）
- 实时进度显示（WebSocket）
- 扫描结果展示
- 扫描历史记录
- 事件日志

**凭证详情**:
- 类型分类
- 脱敏展示
- 位置信息
- 置信度分数
- 验证状态

---

## 非目标（明确不做什么）

- ❌ 自动修复
- ❌ 漏洞扫描（CVE）
- ❌ 运行时安全
- ❌ 商业化
- ❌ 扫描运行中的容器内存

---

## 测试

### 运行测试

```bash
# 所有测试
pytest

# 单元测试
pytest tests/unit/

# 集成测试
pytest tests/integration/

# 覆盖率报告
pytest --cov=imagescan --cov-report=html
```

### 测试策略

- 使用当前主机上的真实镜像进行测试
- 目标覆盖率 > 70%

---

## 开发规范

### 代码风格

- **Python**: 遵循 PEP 8，使用 `ruff` 格式化
- **TypeScript**: 使用 `ESLint` + `Prettier`
- **注释**: 关键逻辑必须添加注释

### Git 提交规范

```
feat: 添加新功能
fix: 修复 bug
docs: 更新文档
test: 添加测试
refactor: 重构代码
```

### 分支策略

- `main` - 主分支（稳定）
- `dev` - 开发分支
- `feature/*` - 功能分支

---

## 学习资源

### 内部文档

- [PRD.md](docs/PRD.md) - 产品需求
- [TECH_STACK.md](docs/TECH_STACK.md) - 技术栈
- [BACKEND_STRUCTURE.md](docs/BACKEND_STRUCTURE.md) - 后端结构
- [APP_FLOW.md](docs/APP_FLOW.md) - 应用流程
- [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) - 实施计划

### 外部资源

- [Google Gemini API 文档](https://ai.google.dev/docs)
- [Docker 镜像规范](https://docs.docker.com/reference/container-image-spec/)
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Next.js 官方文档](https://nextjs.org/docs)

---

## 重要提示

1. **版本锁定**: 所有依赖版本已在 TECH_STACK.md 中锁定，不得随意更改
2. **配置驱动**: 使用 config.toml 管理配置，避免硬编码
3. **日志规范**: 使用结构化 JSON 日志，便于调试和监控
4. **错误处理**: 遵循分级处理策略，确保系统稳定性
5. **工具标准化**: 新工具必须返回 `{success, data, summary}` 格式
6. **上下文隔离**: 大量 LLM 调用应在工具层完成，避免污染主对话

---

## 获取帮助

- 查看当前文件了解架构设计
- 阅读 [APP_FLOW.md](docs/APP_FLOW.md) 理解流程细节
- 参考 [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) 了解实施步骤
- 检查代码注释了解具体实现

---

**Happy Coding! 🚀**
