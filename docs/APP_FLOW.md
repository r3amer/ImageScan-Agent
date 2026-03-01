# ImageScan-Agent 应用流程文档 (APP_FLOW)

## 文档信息

- **项目名称**: ImageScan-Agent
- **文档版本**: 1.0.0
- **最后更新**: 2025-03-01
- **文档状态**: 详尽版（数据流、异常流、Agent交互、工具调用）

---

## 目录

1. [CLI 交互流程](#1-cli-交互流程)
2. [Web 界面流程](#2-web-界面流程)
3. [Agent 推理流程](#3-agent-推理流程)
4. [任务生命周期](#4-task-lifecycle)
5. [数据流详解](#5-数据流详解)
6. [异常流处理](#6-异常流处理)
7. [Agent 交互序列](#7-agent-交互序列)
8. [工具调用详解](#8-工具调用详解)

---

## 1. CLI 交互流程

### 1.1 scan 子命令流程

#### 流程图

```
用户输入: imagescan agent scan nginx:latest
  ↓
[1] 参数验证
  ├─ 镜像名称格式检查
  ├─ 镜像是否存在 (docker images)
  └─ 如果失败 → 显示错误 → 退出
  ↓
[2] 加载配置
  ├─ 读取 config.toml
  ├─ 验证 API Key
  └─ 如果失败 → 提示配置错误 → 退出
  ↓
[3] 创建扫描任务
  ├─ 生成 task_id (UUID)
  ├─ 初始化数据库记录
  └─ 返回 task_id
  ↓
[4] 启动 Agent 系统
  ├─ 初始化事件总线 (asyncio.Queue)
  ├─ 启动主 Agent
  ├─ 启动从 Agent (4 个)
  └─ 发送 TaskCreatedEvent
  ↓
[5] 实时进度显示
  ├─ 订阅进度事件
  ├─ 更新进度条 (Rich Progress)
  │   ├─ 当前层: 3/5
  │   ├─ 当前文件: 800/1250
  │   └─ 已发现凭证: 2
  └─ 每秒刷新
  ↓
[6] 等待完成
  ├─ 监听 TaskCompletedEvent
  ├─ 或 TaskFailedEvent
  └─ 或用户中断 (Ctrl+C)
  ↓
[7a] 成功完成
  ├─ 显示统计摘要
  │   ├─ 扫描时长: 125.5s
  │   ├─ 发现凭证: 25
  │   ├─ 高风险: 5
  │   └─ 报告路径: output/20250301_120000/nginx_latest/results.json
  └─ 退出 (返回码 0)
  ↓
[7b] 扫描失败
  ├─ 显示错误信息
  │   ├─ 错误类型
  │   ├─ 错误消息
  │   └─ 建议操作
  └─ 退出 (返回码 1)
```

#### 详细步骤

**步骤 1: 参数验证**

```python
# 输入
image_name = "nginx:latest"

# 验证逻辑
1. 检查格式: <image>[:<tag>]
2. 查询 Docker: docker images --format "{{.Repository}}:{{.Tag}}"
3. 如果镜像不存在
   → 错误: "Image 'nginx:latest' not found locally. Please pull it first."
   → 建议: "Run: docker pull nginx:latest"
   → 退出 (返回码 1)
```

**步骤 2: 加载配置**

```python
# 加载逻辑
1. 读取 config.toml
2. 检查必需字段:
   - api.gemini_api_key
   - filter_rules.prefix_exclude
   - scan_parameters.confidence_threshold
3. 如果缺少配置
   → 错误: "Missing required configuration: api.gemini_api_key"
   → 建议: "Set GEMINI_API_KEY environment variable or update config.toml"
   → 退出 (返回码 1)
```

**步骤 3: 创建扫描任务**

```python
# 数据库操作
task_id = str(uuid.uuid4())
INSERT INTO scan_tasks (
    task_id, image_name, status, created_at
) VALUES (
    task_id, "nginx:latest", "pending", now()
)

# 输出
print(f"Task created: {task_id}")
```

**步骤 4: 启动 Agent 系统**

```python
# 初始化
event_bus = asyncio.Queue()

# 启动 Agent
agents = [
    MasterAgent(event_bus),
    ScanExecutorAgent(event_bus),
    ValidationAgent(event_bus),
    KnowledgeRetrievalAgent(event_bus),
    ReflectionAgent(event_bus)
]

# 并发启动
for agent in agents:
    asyncio.create_task(agent.run())

# 发送启动事件
await event_bus.put(TaskCreatedEvent(
    task_id=task_id,
    image_name="nginx:latest",
    timestamp=now()
))
```

**步骤 5: 实时进度显示**

```python
# Rich 进度条
from rich.progress import Progress, BarColumn, TextColumn

progress = Progress(
    TextColumn("[bold blue]{task.description}"),
    BarColumn(),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TextColumn("Layers: {task.fields[layers]}"),
    TextColumn("Files: {task.fields[files]}"),
    TextColumn("Credentials: {task.fields[creds]}")
)

with progress as p:
    task = p.add_task("Scanning...", total=100, layers=0, files=0, creds=0)

    # 订阅进度事件
    async for event in event_bus:
        if isinstance(event, ProgressUpdateEvent):
            p.update(
                task,
                completed=event.processed_files / event.total_files * 100,
                layers=f"{event.processed_layers}/{event.total_layers}",
                files=f"{event.processed_files}/{event.total_files}",
                creds=event.credentials_found
            )
```

**步骤 6-7: 完成处理**

```python
# 成功完成
if event.status == "completed":
    print("\n✅ Scan completed successfully!")
    print(f"Duration: {event.duration_seconds}s")
    print(f"Credentials found: {event.credentials_count}")
    print(f"Report: {output_path}")
    exit(0)

# 扫描失败
if event.status == "failed":
    print(f"\n❌ Scan failed: {event.error_message}")
    exit(1)
```

### 1.2 history 子命令流程

```
用户输入: imagescan history
  ↓
[1] 查询数据库
  ├─ SELECT * FROM scan_tasks ORDER BY created_at DESC
  └─ 限制最近 20 条
  ↓
[2] 格式化输出
  ├─ 使用 Rich Table
  │   ├─ Task ID (前8位)
  │   ├─ Image Name
  │   ├─ Status (带颜色)
  │   ├─ Created At
  │   └─ Credentials
  └─ 显示表格
  ↓
[3] 交互选项
  ├─ [Enter] 退出
  ├─ [r] 刷新列表
  ├─ [d] 查看详情
  └─ [o] 打开报告
```

### 1.3 config 子命令流程

```
用户输入: imagescan config
  ↓
[1] 显示当前配置
  ├─ 读取 config.toml
  └─ 格式化输出 (TOML)
  ↓
[2] 编辑选项
  ├─ [e] 编辑配置 (打开 $EDITOR)
  ├─ [v] 验证配置
  └─ [r] 重置为默认
  ↓
[3] 保存配置
  ├─ 验证新配置
  ├─ 备份旧配置 (config.toml.bak)
  └─ 写入新配置
```

### 1.4 verify 子命令流程

```
用户输入: imagescan verify <credential_id>
  ↓
[1] 查询凭证
  ├─ SELECT * FROM credentials WHERE credential_id = ?
  └─ 如果不存在 → 错误 → 退出
  ↓
[2] 显示凭证信息
  ├─ 类型
  ├─ 位置 (文件路径 + 行号)
  ├─ 上下文 (脱敏)
  └─ 当前验证状态
  ↓
[3] 执行验证
  ├─ 静态分析
  │   ├─ 格式检查
  │   ├─ 熵值计算
  │   └─ 过期时间检查
  └─ 如果失败 → 交用户确认
  ↓
[4] 更新数据库
  ├─ UPDATE credentials SET validation_status = ?
  └─ 保存验证结果
  ↓
[5] 显示结果
  ├─ ✅ Valid 或 ❌ Invalid
  └─ 详细信息
```

---

## 2. Web 界面流程

### 2.1 页面结构

```
┌─────────────────────────────────────────────────────────┐
│  Header: ImageScan Agent                                 │
│  [Scan History] [Config]                                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Scan a New Image                                 │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │ Image: [nginx:latest          ]             │  │  │
│  │  │ Options: ☑ Verify  ☐ RAG                   │  │  │
│  │  │         [Start Scan]                       │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  Recent Scans                                            │
│  ┌───────────────────────────────────────────────────┐  │
│  │ ✓ nginx:latest  | 5 creds | 2m ago | [View]      │  │
│  │ ✓ ubuntu:22.04 | 2 creds | 1h ago | [View]      │  │
│  │ ⟳ alpine:3.18  | Scanning...                   │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 2.2 扫描触发流程

```
用户点击 [Start Scan]
  ↓
[1] 表单验证
  ├─ 镜像名称非空
  └─ 如果失败 → 显示错误提示
  ↓
[2] 发送 API 请求
  ├─ POST /api/v1/scan/tasks
  ├─ Body: { image_name: "nginx:latest", ... }
  └─ 接收 task_id
  ↓
[3] 跳转到任务详情页
  ├─ URL: /tasks/{task_id}
  └─ 显示初始状态
```

### 2.3 任务详情页流程

```
页面加载
  ↓
[1] 初始化 WebSocket
  ├─ const ws = new WebSocket(`ws://localhost:8000/ws/scan/tasks/{task_id}`)
  └─ 订阅进度更新
  ↓
[2] 初始数据加载
  ├─ GET /api/v1/scan/tasks/{task_id}
  └─ 显示当前状态
  ↓
[3] 实时进度更新 (WebSocket 消息)
  ├─ 收到 progress.update 事件
  ├─ 更新进度条
  ├─ 更新统计数字
  │   ├─ 已处理层数
  │   ├─ 已处理文件数
  │   └─ 已发现凭证数
  └─ 添加日志行
  ↓
[4] 扫描完成
  ├─ 收到 task.completed 事件
  ├─ 显示完成提示
  ├─ 展示结果摘要
  │   ├─ 总凭证数
  │   ├─ 高风险: 5
  │   ├─ 中风险: 10
  │   └─ 低风险: 10
  └─ 显示 [View Results] 按钮
  ↓
[5] 查看结果
  ├─ 点击 [View Results]
  ├─ 加载凭证列表
  │   └─ GET /api/v1/scan/tasks/{task_id}/credentials
  └─ 渲染凭证表格
      ├─ 类型 (带图标)
      ├─ 置信度 (进度条)
      ├─ 位置 (可点击)
      └─ 状态 (带颜色)
```

### 2.4 结果展示页流程

```
页面加载
  ↓
[1] 加载凭证列表
  ├─ GET /api/v1/scan/tasks/{task_id}/credentials
  │   ?limit=50&offset=0
  └─ 显示第一页
  ↓
[2] 渲染凭证卡片
  ┌─────────────────────────────────────┐
  │ 🔑 API Key                          │
  │ Confidence: ████████░░ 80%          │
  │ Location: /app/config.json:10       │
  │ Status: ✅ Valid                    │
  │ Context: AWS_ACCESS_KEY: AKIA***   │
  │                    [View Details]   │
  └─────────────────────────────────────┘
  ↓
[3] 交互操作
  ├─ 点击 [View Details]
  │   └─ 打开详情模态框
  ├─ 点击 "Location"
  │   └─ 打开文件查看器
  └─ 点击 "Status"
      └─ 可手动更新验证状态
  ↓
[4] 筛选与排序
  ├─ 按类型筛选: API Key | Password | Token
  ├─ 按置信度筛选: High | Medium | Low
  └─ 排序: 置信度 ↓ | 类型 ↑
```

### 2.5 轮询备选方案

如果 WebSocket 不可用，降级为轮询：

```javascript
// 每 2 秒轮询一次
const interval = setInterval(async () => {
    const response = await fetch(`/api/v1/scan/tasks/${taskId}`);
    const data = await response.json();

    updateProgress(data);

    if (data.status === 'completed' || data.status === 'failed') {
        clearInterval(interval);
    }
}, 2000);
```

---

## 3. Agent 推理流程

### 3.1 主 Agent 推理流程

```
接收 TaskCreatedEvent
  ↓
[1] 理解任务
  ├─ 镜像名称: nginx:latest
  ├─ 扫描选项: verify=true, rag=false
  └─ 生成任务描述
  ↓
[2] 制定计划 (调用 LLM)
  ├─ System Prompt: "你是 Docker 镜像安全扫描专家..."
  ├─ User Prompt: f"""
      任务: 扫描镜像 {image_name}
      选项: {scan_options}

      请制定扫描计划:
      1. 保存镜像为 tar
      2. 解压 tar 获取层列表
      3. 逐层分析文件名
      4. 提取可疑文件内容
      5. LLM 分析内容检测凭证
      6. 验证凭证有效性
      7. 评估置信度
      8. 生成报告
      """
  └─ LLM 返回结构化计划
  ↓
[3] 分发任务给从 Agent
  ├─ 发送 LayerExtractionRequest → ScanExecutorAgent
  ├─ 订阅 LayerExtractedEvent
  ↓
[4] 协调从 Agent
  ├─ 收到 LayerExtractedEvent
  ├─ 发送 FilenameAnalysisRequest → ScanExecutorAgent
  ├─ 订阅 FilenameAnalyzedEvent
  ├─ 收到 FilenameAnalyzedEvent
  ├─ 发送 ContentScanRequest → ScanExecutorAgent
  ├─ 订阅 CredentialFoundEvent
  ├─ 收到 CredentialFoundEvent
  ├─ 发送 ValidationRequest → ValidationAgent
  ├─ 订阅 ValidationResultEvent
  ├─ 收到 ValidationResultEvent
  ├─ 发送 ConfidenceAssessmentRequest → ReflectionAgent
  └─ 订阅 CredentialFinalizedEvent
  ↓
[5] 聚合结果
  ├─ 收集所有凭证
  ├─ 生成统计信息
  └─ 发送 TaskCompletedEvent
```

### 3.2 执行 Agent 推理流程

```
接收 LayerExtractionRequest
  ↓
[1] 保存镜像为 tar
  ├─ 工具调用: docker.save(image_name, output_path)
  ├─ 输入: image_name="nginx:latest"
  ├─ 输出: tar_file_path="./image_tar/nginx_latest.tar"
  └─ 如果失败 → 发送 LayerExtractionFailedEvent
  ↓
[2] 解压 tar 文件
  ├─ 工具调用: tar.unpack(tar_file_path, extract_path)
  ├─ 输入: tar_path, extract_path="./tmp/nginx_latest/"
  ├─ 输出: manifest.json
  └─ 如果失败 → 发送 LayerExtractionFailedEvent
  ↓
[3] 读取层列表
  ├─ 解析 manifest.json
  ├─ 提取 layer_id 数组
  ├─ 输出: ["sha256:abc...", "sha256:def..."]
  └─ 发送 LayerExtractedEvent(layers)
```

```
接收 FilenameAnalysisRequest
  ↓
[1] 获取层文件列表
  ├─ 工具调用: layer.list_files(layer_id)
  ├─ 输出: ["/usr/bin/nginx", "/app/config.json", ...]
  ↓
[2] 过滤文件
  ├─ 应用 prefix_exclude 规则
  ├─ 排除: /usr/*, /lib/*, /bin/*
  └─ 剩余: ["/app/config.json", "/.env"]
  ↓
[3] LLM 分析文件名
  ├─ System Prompt: "你是文件安全分析专家..."
  ├─ User Prompt: f"""
      文件列表: {filtered_files}

      判断哪些文件可能包含敏感凭证:
      - .env, config.json: 高风险
      - *.pem, *.key: 证书/私钥
      - *.sh, *.py: 可能硬编码密码

      返回 JSON: {{
          "high_risk": [...],
          "medium_risk": [...],
          "low_risk": [...]
      }}
      """
  └─ LLM 返回分类结果
  ↓
[4] 发送 FilenameAnalyzedEvent
  └─ 输出: {"high_risk": ["/app/config.json"], ...}
```

```
接收 ContentScanRequest
  ↓
[1] 提取文件内容
  ├─ 工具调用: layer.extract_file(layer_id, file_path)
  ├─ 输出: file_content
  └─ 如果失败 → 记录错误 → 跳过
  ↓
[2] LLM 扫描凭证
  ├─ System Prompt: "你是凭证检测专家..."
  ├─ User Prompt: f"""
      文件: {file_path}
      内容:
      {file_content}

      检测敏感凭证:
      1. API Keys (AWS, Google, GitHub)
      2. 密码
      3. Tokens (JWT, OAuth)
      4. 证书/私钥
      5. 数据库连接串

      返回 JSON: {{
          "credentials": [
              {{
                  "type": "api_key",
                  "value": "AKIAIOSFODNN7EXAMPLE",
                  "line_number": 10,
                  "context": "AWS_ACCESS_KEY: AKIA...",
                  "confidence": 0.95
              }}
          ]
      }}
      """
  └─ LLM 返回检测结果
  ↓
[3] 为每个凭证创建事件
  └─ 发送 CredentialFoundEvent(credential)
```

### 3.3 验证 Agent 推理流程

```
接收 CredentialFoundEvent
  ↓
[1] 静态分析凭证
  ├─ 工具调用: validator.static_analyze(credential)
  │   ├─ 格式检查
  │   │   └─ AWS Key: ^AKIA[0-9A-Z]{16}$
  │   ├─ 熵值计算
  │   │   └─ entropy(value) > 3.5 → 高熵
  │   └─ 过期时间检查
  │       └─ JWT: decode() → exp > now()
  ↓
[2] 判断验证结果
  ├─ 如果格式正确 && 熵值高
  │   └─ validation_status = "valid"
  ├─ 如果格式错误
  │   └─ validation_status = "invalid"
  └─ 如果不确定
      └─ validation_status = "unknown" → 交用户确认
  ↓
[3] 发送 ValidationResultEvent
  └─ 输出: {credential_id, validation_status, details}
```

### 3.4 知识检索 Agent 推理流程

```
接收 KnowledgeQueryRequest
  ↓
[1] 生成查询向量
  ├─ 工具调用: embedding_model.encode(query_text)
  └─ 输出: query_embedding (384维向量)
  ↓
[2] 查询 ChromaDB
  ├─ collection: "historical_cases"
  ├─ n_results: 5
  ├─ where: {cred_type: "api_key"}
  └─ 输出:相似案例列表
  ↓
[3] 分析相似案例
  ├─ 计算平均置信度
  ├─ 统计真阳性率
  └─ 提取常见模式
  ↓
[4] 发送 KnowledgeRetrievedEvent
  └─ 输出: {similar_cases, patterns, confidence_adjustment}
```

### 3.5 研判反思 Agent 推理流程

```
接收 ConfidenceAssessmentRequest
  ↓
[1] 汇总所有信息
  ├─ LLM 原始置信度: 0.80
  ├─ 验证结果: valid
  ├─ 知识库匹配: 3 个相似案例，平均置信度 0.85
  └─ 文件上下文: /app/config.json (配置文件)
  ↓
[2] 综合评估 (调用 LLM)
  ├─ System Prompt: "你是安全风险评估专家..."
  ├─ User Prompt: f"""
      凭证信息:
      - 类型: {cred_type}
      - 位置: {file_path}:{line_number}
      - LLM 置信度: {llm_confidence}
      - 验证结果: {validation_status}
      - 相似案例: {similar_cases}

      请综合评估:
      1. 验证结果可信度
      2. 历史案例一致性
      3. 上下文合理性

      返回最终置信度 (0-1) 和风险评估 (high/medium/low)
      """
  └─ LLM 返回评估结果
  ↓
[3] 发送 CredentialFinalizedEvent
  └─ 输出: {credential_id, final_confidence, risk_level}
```

---

## 4. 任务生命周期

### 4.1 状态转换图

```
┌──────────────┐
│   PENDING    │  ← 任务创建
└──────┬───────┘
       │ 启动 Agent
       ↓
┌──────────────┐
│   RUNNING    │  ← 扫描中
└──────┬───────┘
       │
       ├─→ COMPLETED    ← 成功完成
       │
       ├─→ FAILED       ← 扫描失败
       │
       └─→ CANCELLED    ← 用户取消
```

### 4.2 生命周期事件序列

```
1. 任务创建
   └─ TaskCreatedEvent
      ├─ task_id
      ├─ image_name
      └─ timestamp

2. 开始扫描
   └─ TaskStartedEvent
      ├─ task_id
      ├─ total_layers
      └─ total_files (预估)

3. 进度更新 (每秒多次)
   └─ ProgressUpdateEvent
      ├─ task_id
      ├─ layer_id
      ├─ file_path
      ├─ processed_layers / total_layers
      ├─ processed_files / total_files
      └─ credentials_found

4. 发现凭证 (每次发现)
   └─ CredentialFoundEvent
      ├─ credential_id
      ├─ cred_type
      ├─ confidence
      └─ file_path

5. 凭证验证 (每个凭证)
   └─ ValidationResultEvent
      ├─ credential_id
      ├─ validation_status
      └─ details

6. 任务完成
   └─ TaskCompletedEvent
      ├─ task_id
      ├─ status (completed/failed/cancelled)
      ├─ credentials_count
      ├─ duration_seconds
      └─ error_message (如果失败)
```

---

## 5. 数据流详解

### 5.1 扫描任务数据流

```
用户输入 (CLI)
  ↓
FastAPI Endpoint
  ├─ Parse Request
  ├─ Validate Input
  └─ Create Task
      ↓
  SQLite Database
  ├─ Insert scan_tasks
  ├─ Insert scan_metadata
  └─ Return task_id
      ↓
  Event Bus (asyncio.Queue)
  ├─ Publish TaskCreatedEvent
  └─ Subscribe by Agents
      ↓
  Agent Processing
  ├─ Master Agent: Plan
  ├─ Scan Executor: Execute
  ├─ Validation Agent: Verify
  ├─ Knowledge Agent: Retrieve
  └─ Reflection Agent: Assess
      ↓
  Result Storage
  ├─ Update scan_tasks (status)
  ├─ Insert credentials
  ├─ Insert scan_layers
  └─ Write results.json
      ↓
  User Notification
  ├─ CLI: Print Summary
  └─ WebSocket: Push Update
```

### 5.2 凭证检测数据流

```
文件内容
  ↓
LLM Scanner
  ├─ System Prompt (安全专家)
  ├─ User Prompt (文件内容)
  └─ Response (JSON)
      ├─ credentials: [...]
      └─ confidence: 0.80
      ↓
  Credential Object
  ├─ cred_type (从 LLM)
  ├─ confidence (从 LLM)
  ├─ file_path (已知)
  └─ context (脱敏)
      ↓
  Validation Agent
  ├─ Static Analysis
  │   ├─ Regex Match
  │   ├─ Entropy Check
  │   └─ Format Validation
  └─ validation_status
      ↓
  Knowledge Agent
  ├─ Query ChromaDB
  ├─ Retrieve Similar Cases
  └─ confidence_adjustment
      ↓
  Reflection Agent
  ├─ Aggregate Info
  ├─ Call LLM (Re-evaluate)
  └─ final_confidence
      ↓
  Database Storage
  ├─ Insert credentials
  └─ Link to scan_tasks
```

### 5.3 RAG 知识库数据流

```
新凭证发现
  ↓
向量化
  ├─ sentence-transformers
  ├─ input: file_content + context
  └─ output: embedding (384维)
      ↓
  ChromaDB Query
  ├─ collection: historical_cases
  ├─ query_embedding: [...]
  ├─ n_results: 5
  └─ where: {cred_type: "api_key"}
      ↓
  Similarity Search
  ├─ cosine_similarity
  ├─ threshold: 0.8
  └─ top_k: 5
      ↓
  Results
  ├─ similar_cases: [...]
  ├─ avg_confidence: 0.85
  └─ true_positive_rate: 0.90
      ↓
  Confidence Adjustment
  └─ new_confidence = llm_conf * (1 + adjustment)
```

---

## 6. 异常流处理

### 6.1 镜像不存在异常

```
docker.save("nginx:xxx")
  ↓
抛出 DockerImageNotFound
  ↓
[异常处理器]
  ├─ 捕获异常
  ├─ 记录错误日志
  │   └─ ERROR: Image 'nginx:xxx' not found
  ├─ 生成友好错误消息
  │   └─ "Image not found. Available images: nginx:latest, nginx:alpine"
  └─ 发送 TaskFailedEvent
      ├─ task_id
      ├─ error_code: IMAGE_NOT_FOUND
      └─ error_message: "..."
  ↓
[用户通知]
  ├─ CLI: 显示错误 + 退出 (返回码 1)
  └─ Web: 显示错误提示框
```

### 6.2 LLM 超时异常

```
LLM.call(prompt)
  ↓
60 秒超时
  ↓
[异常处理器]
  ├─ 捕获 TimeoutError
  ├─ 记录错误日志
  ├─ 生成错误消息
  │   └─ "LLM timeout after 60s"
  └─ 决策: 跳过当前文件 (非致命)
  ↓
[恢复流程]
  ├─ 标记文件: processing_failed = true
  ├─ 继续处理下一个文件
  └─ 发送 ProgressUpdateEvent (带警告)
```

### 6.3 文件提取失败异常

```
layer.extract_file(layer_id, file_path)
  ↓
抛出 ExtractionError
  ↓
[异常处理器]
  ├─ 判断严重性
  │   ├─ 单个文件: 非致命 → 跳过
  │   └─ 整个层: 致命 → 中止
  ├─ 记录错误到 errors.log
  │   └─ ERROR: Failed to extract /app/config.json
  └─ 发送 FileExtractionFailedEvent
  ↓
[恢复流程]
  ├─ 如果非致命
  │   ├─ 跳过文件
  │   └─ 继续扫描
  └─ 如果致命
      ├─ 发送 TaskFailedEvent
      └─ 中止扫描
```

### 6.4 数据库连接失败异常

```
INSERT INTO scan_tasks(...)
  ↓
抛出 DatabaseError
  ↓
[异常处理器]
  ├─ 捕获异常
  ├─ 尝试重连 (3 次)
  │   ├─ 等待 1s
  │   ├─ 等待 2s
  │   └─ 等待 4s
  └─ 如果仍失败
      ├─ 致命错误
      └─ 发送 TaskFailedEvent
  ↓
[用户通知]
  └─ "Database connection failed. Please check your configuration."
```

### 6.5 Agent 崩溃异常

```
Agent.run()
  ↓
未捕获异常
  ↓
[异常处理器]
  ├─ 捕获 Exception
  ├─ 记录完整堆栈
  ├─ 隔离 Agent (不影响其他 Agent)
  └─ 发送 AgentCrashedEvent
      ├─ agent_type
      ├─ error_message
      └─ stack_trace
  ↓
[恢复流程]
  ├─ 重启 Agent
  ├─ 恢复状态 (从事件总线)
  └─ 继续处理
```

### 6.6 用户中断 (Ctrl+C)

```
用户按 Ctrl+C
  ↓
[信号处理器]
  ├─ 捕获 SIGINT
  ├─ 设置 graceful_shutdown 标志
  └─ 等待当前任务完成
  ↓
[清理流程]
  ├─ 取消进行中的任务
  ├─ 关闭 Agent
  ├─ 关闭数据库连接
  └─ 清理临时文件
  ↓
[用户通知]
  └─ "Scan cancelled by user."
```

---

## 7. Agent 交互序列

### 7.1 完整扫描序列图

```
用户      主Agent      执行Agent      验证Agent      知识Agent      研判Agent
 │          │            │             │             │              │
 │ scan     │            │             │             │              │
 ├──────────>│            │             │             │              │
 │          │            │             │             │              │
 │          │ Plan       │             │             │              │
 │          ├──────────────────────────────────────────────────────>│
 │          │            │             │             │              │
 │          │ Extract    │             │             │              │
 │          ├───────────>│             │             │              │
 │          │            │             │             │              │
 │          │            LayerTar     │             │              │
 │          │<───────────┤             │             │              │
 │          │            │             │             │              │
 │          │ Analyze    │             │             │              │
 │          ├───────────>│             │             │              │
 │          │            │             │             │              │
 │          │            Filenames     │             │              │
 │          │<───────────┤             │             │              │
 │          │            │             │             │              │
 │          │ Scan       │             │             │              │
 │          ├───────────>│             │             │              │
 │          │            │             │             │              │
 │          │            Credential    │             │              │
 │          │<───────────┤             │             │              │
 │          │            │             │             │              │
 │          │ Validate   │             │             │              │
 │          ├─────────────────────────>│             │              │
 │          │            │             │             │              │
 │          │            │ ValidationResult│        │              │
 │          │<─────────────────────────┤             │              │
 │          │            │             │             │              │
 │          │ Query      │             │             │              │
 │          ├────────────────────────────────────────>│              │
 │          │            │             │             │              │
 │          │            │             │ Knowledge    │              │
 │          │<────────────────────────────────────────┤              │
 │          │            │             │             │              │
 │          │ Assess     │             │             │              │
 │          ├──────────────────────────────────────────────────────>│
 │          │            │             │             │              │
 │          │            │             │             │ FinalConf    │
 │          │<──────────────────────────────────────────────────────┤
 │          │            │             │             │              │
 │          │ Complete   │             │             │              │
 │<─────────┤            │             │             │              │
 │          │            │             │             │              │
```

### 7.2 并行处理序列

```
主Agent        执行Agent1        执行Agent2
  │               │                 │
  │  Task1        │                 │
  ├──────────────>│                 │
  │               │                 │
  │  Task2        │                 │
  │  ├───────────>│                 │
  │  └─────────────────────────────>│
  │               │                 │
  │               Progress1         │
  │<──────────────┤                 │
  │               │                 │
  │               │                 Progress2
  │               │<────────────────┤
  │               │                 │
  │               Result1           │
  │<──────────────┤                 │
  │               │                 │
  │               │                 Result2
  │               │<────────────────┤
  │               │                 │
  │  Aggregate    │                 │
  │  ├────────────┤                 │
  │  └─────────────────────────────┤
  │               │                 │
```

---

## 8. 工具调用详解

### 8.1 镜像操作工具

#### tool: docker.save()

```python
@tool
async def docker_save(image_name: str, output_path: str) -> str:
    """
    保存 Docker 镜像为 tar 文件

    Args:
        image_name: 镜像名称 (如 "nginx:latest")
        output_path: 输出 tar 路径

    Returns:
        tar_file_path: 保存的 tar 文件路径

    Raises:
        DockerImageNotFound: 镜像不存在
        DockerSaveError: 保存失败
    """
    client = docker.from_env()
    try:
        image = client.images.get(image_name)
        tar_path = f"{output_path}/{image_name.replace(':', '_')}.tar"
        image.save(tar_path)
        return tar_path
    except errors.ImageNotFound as e:
        raise DockerImageNotFound(str(e))
    except Exception as e:
        raise DockerSaveError(str(e))
```

**调用示例**:
```python
tar_path = await docker_save("nginx:latest", "./image_tar")
# 返回: "./image_tar/nginx_latest.tar"
```

#### tool: tar.unpack()

```python
@tool
async def tar_unpack(tar_path: str, extract_path: str) -> dict:
    """
    解压 tar 文件

    Args:
        tar_path: tar 文件路径
        extract_path: 解压目标路径

    Returns:
        manifest: manifest.json 内容
    """
    await asyncio.to_thread(
        lambda: tarfile.open(tar_path).extractall(extract_path)
    )
    manifest_path = f"{extract_path}/manifest.json"
    with open(manifest_path) as f:
        return json.load(f)
```

#### tool: layer.list_files()

```python
@tool
async def layer_list_files(layer_tar_path: str) -> List[str]:
    """
    列出层中的所有文件

    Args:
        layer_tar_path: 层 tar 文件路径

    Returns:
        files: 文件路径列表
    """
    with tarfile.open(layer_tar_path) as tar:
        return tar.getnames()
```

#### tool: layer.extract_file()

```python
@tool
async def layer_extract_file(
    layer_tar_path: str,
    file_path: str,
    output_path: str
) -> str:
    """
    从层中提取单个文件

    Args:
        layer_tar_path: 层 tar 文件路径
        file_path: 文件在层中的路径
        output_path: 输出文件路径

    Returns:
        extracted_path: 提取后的文件路径
    """
    with tarfile.open(layer_tar_path) as tar:
        member = tar.getmember(file_path)
        await asyncio.to_thread(
            lambda: tar.extract(member, output_path)
        )
        return f"{output_path}/{file_path}"
```

### 8.2 LLM 工具

#### tool: llm.analyze_filenames()

```python
@tool
async def llm_analyze_filenames(
    files: List[str],
    filter_rules: dict
) -> dict:
    """
    使用 LLM 分析文件名，识别潜在敏感文件

    Args:
        files: 文件路径列表
        filter_rules: 过滤规则

    Returns:
        classification: 文件分类结果
        {
            "high_risk": [...],
            "medium_risk": [...],
            "low_risk": [...]
        }
    """
    # 应用过滤规则
    filtered = apply_filters(files, filter_rules)

    # 构建 Prompt
    prompt = f"""
    分析以下文件列表，判断哪些可能包含敏感凭证:
    {json.dumps(filtered)}

    返回 JSON 格式分类。
    """

    # 调用 Gemini
    response = await gemini_client.chat.completions.create(
        model="gemini-2.5-flash",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        response_mime_type="application/json"
    )

    return json.loads(response.choices[0].message.content)
```

#### tool: llm.scan_content()

```python
@tool
async def llm_scan_content(
    file_path: str,
    content: str
) -> dict:
    """
    使用 LLM 扫描文件内容，检测凭证

    Args:
        file_path: 文件路径
        content: 文件内容

    Returns:
        credentials: 检测到的凭证列表
    """
    prompt = f"""
    文件: {file_path}
    内容:
    {content[:5000]}

    检测敏感凭证，返回 JSON 格式。
    """

    response = await gemini_client.chat.completions.create(
        model="gemini-2.5-flash",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        response_mime_type="application/json"
    )

    return json.loads(response.choices[0].message.content)
```

### 8.3 验证工具

#### tool: validator.static_analyze()

```python
@tool
def validator_static_analyze(credential: Credential) -> dict:
    """
    静态分析凭证

    Args:
        credential: 凭证对象

    Returns:
        validation: 验证结果
        {
            "is_valid": bool,
            "confidence": float,
            "details": {...}
        }
    """
    result = {"is_valid": False, "confidence": 0.0, "details": {}}

    # 1. 格式检查
    if credential.cred_type == "aws_key":
        pattern = r"^AKIA[0-9A-Z]{16}$"
        if re.match(pattern, credential.raw_value):
            result["is_valid"] = True
            result["confidence"] += 0.3

    # 2. 熵值计算
    entropy = calculate_entropy(credential.raw_value)
    if entropy > 3.5:
        result["confidence"] += 0.3

    # 3. 长度检查
    if len(credential.raw_value) >= 20:
        result["confidence"] += 0.2

    # 4. 上下文检查
    if "config" in credential.file_path.lower():
        result["confidence"] += 0.2

    return result
```

### 8.4 知识库工具

#### tool: knowledge.query_similar()

```python
@tool
async def knowledge_query_similar(
    query_text: str,
    collection_name: str,
    top_k: int = 5
) -> List[dict]:
    """
    查询相似历史案例

    Args:
        query_text: 查询文本
        collection_name: 集合名称
        top_k: 返回结果数

    Returns:
        results: 相似案例列表
    """
    # 生成查询向量
    embedding = embedding_model.encode(query_text)

    # 查询 ChromaDB
    collection = chromadb_client.get_collection(collection_name)
    results = collection.query(
        query_embeddings=[embedding.tolist()],
        n_results=top_k
    )

    return [
        {
            "id": r["id"],
            "document": r["document"],
            "metadata": r["metadata"],
            "distance": d
        }
        for r, d in zip(results["documents"][0], results["distances"][0])
    ]
```

### 8.5 数据库工具

#### tool: db.insert_credential()

```python
@tool
async def db_insert_credential(credential: Credential) -> str:
    """
    插入凭证到数据库

    Args:
        credential: 凭证对象

    Returns:
        credential_id: 凭证 ID
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO credentials (
                credential_id, task_id, cred_type, confidence,
                file_path, line_number, layer_id, context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                credential.credential_id,
                credential.task_id,
                credential.cred_type,
                credential.confidence,
                credential.file_path,
                credential.line_number,
                credential.layer_id,
                credential.context
            )
        )
        await db.commit()
        return credential.credential_id
```

#### tool: db.update_task_status()

```python
@tool
async def db_update_task_status(
    task_id: str,
    status: str,
    **kwargs
) -> bool:
    """
    更新任务状态

    Args:
        task_id: 任务 ID
        status: 新状态
        **kwargs: 其他更新字段

    Returns:
        success: 是否成功
    """
    async with aiosqlite.connect(DB_PATH) as db:
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
        return True
```

---

## 9. 实时通信流

### 9.1 WebSocket 消息格式

#### 客户端订阅

```javascript
// 连接 WebSocket
const ws = new WebSocket(`ws://localhost:8000/ws/scan/tasks/${taskId}`);

// 发送订阅消息
ws.send(JSON.stringify({
    type: "subscribe",
    channels: ["progress", "credentials", "status"]
}));
```

#### 服务端推送

```python
# 进度更新
await websocket.send_json({
    "type": "progress.update",
    "data": {
        "layer_id": "sha256:abc...",
        "file_path": "/app/config.json",
        "processed_layers": 3,
        "total_layers": 5,
        "processed_files": 800,
        "total_files": 1250,
        "credentials_found": 2
    }
})

# 凭证发现
await websocket.send_json({
    "type": "credential.found",
    "data": {
        "credential_id": "...",
        "cred_type": "api_key",
        "confidence": 0.95,
        "file_path": "/app/config.json",
        "line_number": 10
    }
})

# 任务完成
await websocket.send_json({
    "type": "task.completed",
    "data": {
        "task_id": "...",
        "status": "completed",
        "credentials_count": 25,
        "duration_seconds": 125.5
    }
})
```

### 9.2 轮询降级方案

```javascript
// 如果 WebSocket 连接失败，降级为轮询
let pollingInterval;

function startPolling(taskId) {
    pollingInterval = setInterval(async () => {
        const response = await fetch(`/api/v1/scan/tasks/${taskId}`);
        const data = await response.json();

        updateUI(data);

        if (data.status === 'completed' || data.status === 'failed') {
            clearInterval(pollingInterval);
        }
    }, 2000); // 每 2 秒轮询一次
}
```

---

**文档结束**
