# ImageScan-Agent 技术栈文档 (TECH_STACK)

## 文档信息

- **项目名称**: ImageScan-Agent
- **文档版本**: 1.0.0
- **最后更新**: 2025-03-01
- **文档状态**: 严格版（所有版本锁定）

---

## 1. 技术栈总览

本项目采用 Python 后端 + Next.js 前端 + 异步事件总线的架构模式。

```
┌─────────────────────────────────────────────────────────┐
│                     用户界面层                          │
├──────────────────────┬──────────────────────────────────┤
│   CLI (Typer + Rich) │   Web UI (Next.js + TypeScript)  │
└──────────────────────┴──────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                     API 网关层                          │
│                   FastAPI 0.104.1                       │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                   Agent 业务层                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ 主 Agent │  │ 执行     │  │ 验证     │  │ 研判   │  │
│  │          │  │ Agent    │  │ Agent    │  │ Agent  │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
│              事件总线: asyncio.Queue                    │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                    工具与数据层                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ LLM      │  │ SQLite   │  │ChromaDB  │  │ Docker │  │
│  │ Gemini   │  │ 3.44.0   │  │ 0.4.22   │  │ SDK    │  │
│  │ 2.5 Flash│  │          │  │          │  │ 7.0.0  │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 2. 后端技术栈

### 2.1 核心运行时

| 技术 | 版本 | 用途 | 安装命令 |
|------|------|------|----------|
| **Python** | 3.11.8 | 核心运行时 | pyenv/pyenv-win |
| **pip** | 23.3.1 | 包管理器 | 随 Python 安装 |

**强制要求**: 必须使用 Python 3.11.x，不支持 3.10 或 3.12

### 2.2 Web 框架

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **FastAPI** | 0.104.1 | Web API 框架 | `pip install fastapi==0.104.1` |
| **uvicorn** | 0.24.0 | ASGI 服务器 | `pip install uvicorn==0.24.0` |
| **pydantic** | 2.5.0 | 数据验证 | `pip install pydantic==2.5.0` |

**版本选择理由**: FastAPI 0.104.x 是当前 LTS 稳定版本

### 2.3 CLI 框架

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **Typer** | 0.9.0 | CLI 命令框架 | `pip install typer==0.9.0` |
| **Rich** | 13.7.0 | 终端美化/进度条 | `pip install rich==13.7.0` |

### 2.4 异步与并发

| 技术 | 版本 | 用途 | 备注 |
|------|------|------|------|
| **asyncio** | (内置) | 异步 IO | Python 标准库 |
| **aiofiles** | 23.2.1 | 异步文件操作 | `pip install aiofiles==23.2.1` |

### 2.5 LLM 集成

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **openai** | 1.6.1 | Gemini API 客户端 | `pip install openai==1.6.1` |
| **google-generativeai** | 0.3.2 | Gemini 官方 SDK（备选） | `pip install google-generativeai==0.3.2` |

**重要**: 仅使用 Google Gemini 2.5 Flash 模型，不使用其他 LLM

**API 端点**: `https://generativelanguage.googleapis.com/v1beta/openai/`

### 2.6 数据库

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **sqlite3** | (内置 3.44.0) | 关系型数据库 | Python 标准库 |
| **aiosqlite** | 0.19.0 | 异步 SQLite | `pip install aiosqlite==0.19.0` |

### 2.7 向量数据库 (RAG)

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **chromadb** | 0.4.22 | 向量数据库（嵌入式） | `pip install chromadb==0.4.22` |
| **sentence-transformers** | 2.2.2 | 文本向量化 | `pip install sentence-transformers==2.2.2` |

**部署模式**: 嵌入式模式（不使用独立服务）

### 2.8 Docker 集成

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **docker** | 7.0.0 | Docker SDK for Python | `pip install docker==7.0.0` |

**系统要求**: 需要访问 Docker Daemon（Unix socket 或 TCP）

### 2.9 配置管理

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **toml** | 0.10.2 | TOML 配置解析 | `pip install toml==0.10.2` |
| **python-dotenv** | 1.0.0 | 环境变量加载 | `pip install python-dotenv==1.0.0` |

**配置文件**: 单一 `config.toml` 文件

### 2.10 日志系统

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **structlog** | 23.2.0 | 结构化 JSON 日志 | `pip install structlog==23.2.0` |
| **loguru** | 0.7.2 | 日志轮转 | `pip install loguru==0.7.2` |

**日志格式**: JSON 结构化日志

### 2.11 测试框架

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **pytest** | 7.4.3 | 测试框架 | `pip install pytest==7.4.3` |
| **pytest-asyncio** | 0.21.1 | 异步测试 | `pip install pytest-asyncio==0.21.1` |
| **pytest-cov** | 4.1.0 | 覆盖率报告 | `pip install pytest-cov==4.1.0` |
| **pytest-mock** | 3.12.0 | Mock 工具 | `pip install pytest-mock==3.12.0` |

### 2.12 工具库

| 技术 | 版本 | 用途 | pip 命令 |
|------|------|------|----------|
| **httpx** | 0.25.2 | 异步 HTTP 客户端 | `pip install httpx==0.25.2` |
| **pyyaml** | 6.0.1 | YAML 解析 | `pip install pyyaml==6.0.1` |
| **python-dateutil** | 2.8.2 | 日期处理 | `pip install python-dateutil==2.8.2` |

---

## 3. 前端技术栈

### 3.1 核心框架

| 技术 | 版本 | 用途 | 安装命令 |
|------|------|------|----------|
| **Node.js** | 18.20.4 | JavaScript 运行时 | nvm install 18.20.4 |
| **npm** | 10.2.4 | 包管理器 | 随 Node.js 安装 |
| **Next.js** | 14.0.4 (LTS) | React 框架 | `npx create-next-app@14.0.4` |
| **React** | 18.2.0 | UI 库 | 随 Next.js 安装 |
| **TypeScript** | 5.3.3 | 类型系统 | 随 Next.js 安装 |

**强制要求**: 必须使用 Next.js 14.x LTS 版本

### 3.2 UI 组件库

| 技术 | 版本 | 用途 | 安装命令 |
|------|------|------|----------|
| **Tailwind CSS** | 3.3.6 | CSS 框架 | `npm install tailwindcss@3.3.6` |
| **shadcn/ui** | latest | 组件库 | 使用 shadcn CLI |
| **lucide-react** | 0.294.0 | 图标库 | `npm install lucide-react@0.294.0` |

### 3.3 状态管理

| 技术 | 版本 | 用途 | 安装命令 |
|------|------|------|----------|
| **Zustand** | 4.4.7 | 轻量状态管理 | `npm install zustand@4.4.7` |
| **React Query** | 5.12.1 | 服务端状态 | `npm install @tanstack/react-query@5.12.1` |

### 3.4 HTTP 客户端

| 技术 | 版本 | 用途 | 安装命令 |
|------|------|------|----------|
| **axios** | 1.6.2 | HTTP 客户端 | `npm install axios@1.6.2` |

---

## 4. 开发工具

### 4.1 Python 开发工具

| 技术 | 版本 | 用途 | 安装命令 |
|------|------|------|----------|
| **ruff** | 0.1.8 | Linter & Formatter | `pip install ruff==0.1.8` |
| **mypy** | 1.7.1 | 类型检查 | `pip install mypy==1.7.1` |
| **black** | 23.12.0 | 代码格式化 | `pip install black==23.12.0` |
| **pre-commit** | 3.6.0 | Git hooks | `pip install pre-commit==3.6.0` |

### 4.2 Node.js 开发工具

| 技术 | 版本 | 用途 | 安装命令 |
|------|------|------|----------|
| **ESLint** | 8.55.0 | Linter | `npm install eslint@8.55.0` |
| **Prettier** | 3.1.1 | Formatter | `npm install prettier@3.1.1` |

### 4.3 容器化

| 技术 | 版本 | 用途 |
|------|------|------|
| **Docker** | 24.0.7 | 容器运行时 |
| **Docker Compose** | 2.23.0 | 多容器编排 |

---

## 5. 依赖清单

### 5.1 Python 完整依赖列表

创建 `requirements.txt`:

```txt
# Web 框架
fastapi==0.104.1
uvicorn==0.24.0
pydantic==2.5.0

# CLI 框架
typer==0.9.0
rich==13.7.0

# 异步
aiofiles==23.2.1
aiosqlite==0.19.0

# LLM
openai==1.6.1

# 数据库
chromadb==0.4.22
sentence-transformers==2.2.2

# Docker
docker==7.0.0

# 配置
toml==0.10.2
python-dotenv==1.0.0

# 日志
structlog==23.2.0
loguru==0.7.2

# 测试
pytest==7.4.3
pytest-asyncio==0.21.1
pytest-cov==4.1.0
pytest-mock==3.12.0

# 工具
httpx==0.25.2
pyyaml==6.0.1
python-dateutil==2.8.2
```

### 5.2 Node.js 完整依赖列表

创建 `package.json`:

```json
{
  "name": "imagescan-agent-ui",
  "version": "1.0.0",
  "private": true,
  "dependencies": {
    "next": "14.0.4",
    "react": "18.2.0",
    "react-dom": "18.2.0",
    "typescript": "5.3.3",
    "tailwindcss": "3.3.6",
    "lucide-react": "0.294.0",
    "zustand": "4.4.7",
    "@tanstack/react-query": "5.12.1",
    "axios": "1.6.2"
  },
  "devDependencies": {
    "eslint": "8.55.0",
    "prettier": "3.1.1"
  }
}
```

---

## 6. 版本锁定策略

### 6.1 Python 版本锁定

**生产环境**:
- 使用 `requirements.txt` 精确锁定版本
- 格式: `package==version`

**开发环境**:
- 使用 `requirements-dev.txt` 包含开发工具
- 格式: `package==version`

### 6.2 Node.js 版本锁定

**生产环境**:
- 使用 `package-lock.json` 自动锁定
- npm 自动生成并维护

**开发环境**:
- 使用 `.nvmrc` 锁定 Node.js 版本
- 内容: `20.10.0`

---

## 7. 系统要求

### 7.1 开发环境

| 组件 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Ubuntu 22.04 / macOS 13+ / WSL2 | Ubuntu 22.04 LTS |
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 10 GB 可用空间 | 20 GB+ SSD |

### 7.2 运行时环境

| 组件 | 版本要求 |
|------|----------|
| Python | 3.11.8 (严格) |
| Node.js | 18.20.4 |
| Docker | 24.0.7+ |

---

## 8. 兼容性矩阵

### 8.1 操作系统兼容性

| OS | 支持版本 | 备注 |
|----|----------|------|
| Ubuntu | 22.04, 23.10 | 主要支持 |
| macOS | 13+ (Ventura+) | 需要 Docker Desktop |
| Windows | 11 + WSL2 | 不支持原生 Windows |

### 8.2 Python 版本兼容性

| Python 版本 | 兼容性 | 备注 |
|-------------|--------|------|
| 3.10 | ❌ 不支持 | 已弃用 |
| 3.11 | ✅ 支持 | **目标版本** |
| 3.12 | ❌ 不支持 | 尚未测试 |

### 8.3 Docker 版本兼容性

| Docker 版本 | 兼容性 | 备注 |
|-------------|--------|------|
| 20.10.x | ⚠️ 有限支持 | 建议升级 |
| 23.0.x | ✅ 支持 | |
| 24.0.x | ✅ 支持 | **推荐** |

---

## 9. 升级策略

### 9.1 依赖升级周期

- **安全补丁**: 立即升级
- **Bug 修复**: 每月评估
- **主版本升级**: 每季度评估

### 9.2 版本锁定原则

**绝不自动升级**以下依赖:
- Python 3.11.x (锁死)
- Next.js 14.x (仅升级 LTS 小版本)
- FastAPI 0.104.x (测试后升级)

---

## 10. 故障排除

### 10.1 常见依赖问题

| 问题 | 解决方案 |
|------|----------|
| `chromadb` 安装失败 | 使用 `pip install chromadb --no-cache-dir` |
| `sentence-transformers` 下载慢 | 使用国内镜像源 |
| Docker 权限错误 | 将用户添加到 `docker` 组 |

### 10.2 版本冲突解决

```bash
# 检查依赖冲突
pip check

# 强制重新安装
pip install --force-reinstall package==version

# 使用虚拟环境隔离
python -m venv venv
source venv/bin/activate  # Linux/macOS
```

---

## 附录 A: 快速安装脚本

### A.1 Python 环境安装

```bash
#!/bin/bash
# install_python.sh

# 安装 Python 3.11.8
pyenv install 3.11.8
pyenv local 3.11.8

# 升级 pip
pip install --upgrade pip==23.3.1

# 安装依赖
pip install -r requirements.txt
```

### A.2 Node.js 环境安装

```bash
#!/bin/bash
# install_nodejs.sh

# 安装 Node.js 18.20.4
nvm install 18.20.4
nvm use 18.20.4

# 安装依赖
cd frontend && npm install
```

---

**文档结束**
