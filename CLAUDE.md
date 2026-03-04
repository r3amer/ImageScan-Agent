# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Last Updated**: 2025-03-01
**Project Status**: 🔄 Complete Rebuild (规范文档已完成，开发待开始)

---

## 📚 项目知识库

本项目遵循严格的文档驱动开发规范。**在编写任何代码之前，请先阅读以下规范文档**：

### 必读文档（优先级顺序）

1. **[PRD.md](docs/PRD.md)** - 产品需求文档
   - 完整功能规格
   - MVP 范围（CLI + 基本扫描）
   - 验收标准（功能可用 + 性能基准）
   - 非目标（明确不做什么）
   - **重点**: 验收标准、用户故事

2. **[TECH_STACK.md](docs/TECH_STACK.md)** - 技术栈文档（严格版本锁定）
   - Python 3.11.8（严格）
   - Next.js 14.0.4 LTS
   - FastAPI 0.104.1
   - **所有依赖版本已锁定，不得随意更改**

3. **[BACKEND_STRUCTURE.md](docs/BACKEND_STRUCTURE.md)** - 后端结构文档
   - 数据模型（ScanTask、Credential、ScanLayer）
   - SQLite 数据库模式
   - ChromaDB 向量数据库模式
   - API 端点设计
   - Agent 通信协议

4. **[APP_FLOW.md](docs/APP_FLOW.md)** - 应用流程文档（最详尽）
   - CLI 交互流程（5 个子命令）
   - Web 界面流程（轻量级控制台）
   - Agent 推理流程（主从模式）
   - 任务生命周期
   - 数据流详解
   - 异常流处理
   - Agent 交互序列图
   - 工具调用详解

5. **[IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)** - 实施计划文档
   - 10 个阶段的详细构建步骤
   - 每个步骤的验收标准
   - **按此顺序逐步构建**

6. **[progress.txt](progress.txt)** - 进度跟踪文件
   - 当前开发状态
   - 已完成的功能
   - 进行中的任务
   - 下一步计划

---

## 🎯 项目概述

**项目名称**: ImageScan-Agent

**核心价值**: 智能化 + 准确性

**目标用户**: 开源社区

**项目定位**: 基于 Google Gemini 2.5 Flash LLM 的 Docker 镜像敏感凭证扫描智能体系统

---

## 🏗️ 架构设计（主从 Agent 模式）

### Agent 架构

```
主 Agent (Master Agent)
  ├── 规划与协调
  │
  ├── 从 Agent 1: ScanExecutorAgent
  │   └── 执行镜像解压、文件扫描
  │
  ├── 从 Agent 2: ValidationAgent
  │   └── 验证凭证有效性、静态分析
  │
  ├── 从 Agent 3: KnowledgeRetrievalAgent
  │   └── 查询 RAG 知识库、匹配历史模式
  │
  └── 从 Agent 4: ReflectionAgent
      └── 置信度评估、二次审核
```

### 通信机制

- **事件总线**: `asyncio.Queue`
- **事件类型**: TaskCreated、ProgressUpdate、CredentialFound、TaskCompleted
- **实时反馈**:
  - CLI: 进度条 (Rich Progress)
  - Web: 轮询 (降级方案)

---

## 📦 项目结构

```
imagescan/
├── core/               # 核心抽象类
│   ├── agent.py       # Agent 基类
│   ├── event_bus.py   # 事件总线
│   ├── events.py      # 事件定义
│   └── llm_client.py  # LLM 客户端
│
├── agents/            # Agent 实现
│   ├── master_agent.py
│   ├── executor_agent.py
│   ├── validation_agent.py
│   ├── knowledge_agent.py
│   └── reflection_agent.py
│
├── tools/             # 工具注册与实现
│   ├── registry.py    # 工具注册表
│   ├── docker_tools.py
│   ├── tar_tools.py
│   └── file_tools.py
│
├── models/            # 数据模型
│   ├── task.py
│   ├── credential.py
│   └── layer.py
│
├── api/               # FastAPI 端点
│   ├── scan.py
│   ├── credentials.py
│   └── config.py
│
├── cli/               # 命令行界面
│   └── main.py
│
├── utils/             # 工具函数
│   ├── config.py      # 配置管理
│   ├── logger.py      # 日志系统
│   └── database.py    # 数据库操作
│
└── tests/             # 测试
    ├── unit/
    └── integration/
```

---

## 🔧 开发环境配置

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

## 🚀 运行应用

### CLI 命令

```bash
# 扫描镜像
imagescan scan nginx:latest

# 查看历史
imagescan history

# 配置管理
imagescan config

# 验证凭证
imagescan verify <credential_id>
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

## 🔑 关键设计决策

### 技术选型

| 决策 | 理由 |
|------|------|
| Python 3.11 | 严格锁定，兼容性最佳 |
| 仅用 Gemini 2.5 Flash | 成本低，速度快 |
| SQLite + ChromaDB | 本地持久化，嵌入式部署 |
| 主从 Agent | 高度自主，职责分离 |
| 事件总线 (asyncio.Queue) | 解耦通信，异步高效 |

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

### 工具返回值标准化架构（2025-03 更新）

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

#### 实现细节

**工具层 (tools/*.py)**:
- 每个工具包含完整的业务逻辑
- 调用 `llm_client.think()` 进行独立 LLM 分析
- 返回结构化结果，包含 `summary` 字段

**Agent 层 (agents/scan_agent.py)**:
- 通用 `_format_tool_result()` 方法处理所有工具结果
- 不再有任何硬编码的 if-elif 工具处理逻辑
- 特殊工具（如 `file.analyze_contents`）将数据存储到 Storage

**LLM 客户端层 (core/llm_client.py)**:
- 只提供通用的 `think(prompt, context, temperature)` 方法
- 不包含任何业务逻辑

#### 已实现的标准工具

| 工具 | 功能 | 返回值 |
|------|------|--------|
| `docker.save` | 保存镜像为 tar | `{success, data: {tar_path, size_mb}, summary}` |
| `docker.exists` | 检查镜像是否存在 | `{success, data: {exists}, summary}` |
| `tar.unpack` | 解压镜像 tar | `{success, data: {manifest, layers_count}, summary}` |
| `tar.analyze_all_layer_files` | 分析文件名（隔离） | `{success, data: {suspicious_files, ...}, summary: [...]}` |
| `file.analyze_contents` | 分析文件内容（隔离） | `{success, data: {credentials}, summary: [...]}` |

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

## 📊 数据流

### 扫描流程

```
用户输入 (镜像名称)
  ↓
主 Agent 接收任务
  ↓
主 Agent 制定计划（调用 LLM）
  ↓
执行 Agent
  ├─ 保存镜像为 tar
  ├─ 解压 tar 获取层列表
  ├─ 逐层分析文件名（LLM）
  ├─ 提取可疑文件内容
  └─ 扫描凭证（LLM）
  ↓
验证 Agent
  ├─ 静态分析（格式、熵值）
  └─ 有效性验证
  ↓
知识 Agent
  └─ 查询 RAG 知识库（ChromaDB）
  ↓
研判 Agent
  └─ 置信度评估（LLM）
  ↓
结果输出 (JSON + 终端)
```

---

## 🎨 用户界面

### CLI（子命令结构）

- `imagescan agent scan <image>` - 扫描镜像
- `imagescan history` - 查看历史记录
- `imagescan config` - 查看/修改配置
- `imagescan verify <credential>` - 验证凭证

### Web UI（轻量级控制台）

**功能范围**:
- 查看扫描结果
- 简单的扫描触发按钮
- 实时进度显示（轮询）

**凭证详情**:
- 类型分类
- 脱敏展示
- 位置信息
- 置信度分数

---

## 🗄️ 数据存储

### 文件系统

```
output/
└── {timestamp}/
    └── {image_name}/
        ├── results.json        # 扫描结果
        ├── metadata.json       # 元数据
        └── files/              # 提取的敏感文件
```

### SQLite 数据库

**表结构**:
- `scan_tasks` - 扫描任务
- `credentials` - 凭证记录
- `scan_layers` - 镜像层
- `scan_metadata` - 扫描元数据
- `knowledge_entries` - RAG 知识库

### ChromaDB（向量数据库）

**Collections**:
- `historical_cases` - 历史案例库
- `credential_patterns` - 凭证模式库

---

## ✅ MVP 范围（最小可行产品）

### 核心功能

1. ✅ 镜像解压
2. ✅ 智能文件筛选
3. ✅ 内容扫描
4. ✅ 结果输出

### 验收标准

- **功能可用**: 能够扫描本地 Docker 镜像并输出 JSON
- **性能基准**: 扫描速度 < 5 分钟/GB

### 迭代路线（渐进增强）

```
MVP (CLI + 基本扫描)
  ↓
Web UI (轻量级控制台)
  ↓
Agent 优化（多 Agent 协作）
  ↓
RAG 知识库（历史案例 + 凭证模式）
```

---

## 🚫 非目标（明确不做什么）

- ❌ 自动修复
- ❌ 漏洞扫描（CVE）
- ❌ 运行时安全
- ❌ 商业化
- ❌ 扫描运行中的容器内存

---

## 🧪 测试

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

## 📝 开发规范

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
- `develop` - 开发分支
- `feature/*` - 功能分支

---

## 🎓 学习资源

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

## ⚠️ 重要提示

1. **不要跳过文档**：在编写代码前，务必先阅读相关规范文档
2. **版本锁定**：所有依赖版本已在 TECH_STACK.md 中锁定，不得随意更改
3. **配置驱动**：使用 config.toml 管理配置，避免硬编码
4. **日志规范**：使用结构化 JSON 日志，便于调试和监控
5. **错误处理**：遵循分级处理策略，确保系统稳定性
6. **测试优先**：为新功能添加测试，保持覆盖率 > 70%

---

## 📞 获取帮助

- 查看 [progress.txt](progress.txt) 了解当前进度
- 阅读 [APP_FLOW.md](docs/APP_FLOW.md) 理解流程细节
- 参考 [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) 按步骤构建

---

**Happy Coding! 🚀**
