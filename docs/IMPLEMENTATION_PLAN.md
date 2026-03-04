# ImageScan-Agent 实施计划文档 (IMPLEMENTATION_PLAN)

## 文档信息

- **项目名称**: ImageScan-Agent
- **文档版本**: 2.0.0 (ScanAgent重构版)
- **最后更新**: 2025-03-02
- **文档状态**: 详细版（4阶段实施计划）
- **上一版本**: 1.0.0 (主从Agent架构)

---

## 📋 目录

1. [重构总览](#重构总览)
2. [架构变更说明](#架构变更说明)
3. [阶段 1: 规则引擎与配置](#阶段-1-规则引擎与配置)
4. [阶段 2: LLM解析器与摘要管理](#阶段-2-llm解析器与摘要管理)
5. [阶段 3: ScanAgent实现](#阶段-3-scanagent实现)
6. [阶段 4: 集成与测试](#阶段-4-集成与测试)
7. [验收标准总结](#验收标准总结)

---

## 🔄 重构总览

### 为什么需要重构？

**当前问题（v1.0）**：
- 现有"主从Agent"系统实际上是伪Agent，智能体成熟度仅8%
- LLM被动调用，不主动选择工具
- 固定流程，无动态规划和决策能力
- 多Agent串行调用，非真正协作

**重构目标（v2.0）**：
- 实现单一智能体（ScanAgent）
- LLM具备工具调用能力（手动解析函数调用字符串）
- 动态规划，根据中间结果调整策略
- 智能体成熟度提升至40%+

### 核心设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| **Agent数量** | 单Agent (ScanAgent) | 简化架构，降低复杂度 |
| **规划方式** | 动态规划 | 执行过程中根据结果调整策略 |
| **LLM调用** | 手动解析函数调用字符串 | 不依赖Function Calling，更可控 |
| **解析方式** | AST解析 | 安全、可靠 |
| **错误处理** | 反馈重试 | LLM自我纠正 |
| **上下文管理** | 规则生成摘要 | 减少Token消耗 |
| **规则引擎** | 路径过滤 + 扩展名黑名单 | 快速筛选，减少LLM调用 |
| **扫描流程** | 完整流程 | 框架固定 + LLM决策 |
| **LLM决策点** | 多次 | 文件筛选、凭证评估、异常处理 |
| **进度事件** | 关键节点反馈 | 扫描开始、层完成、凭证发现、扫描完成 |

### 扫描流程设计

```
用户输入 (镜像名称)
  ↓
[框架固定] Docker操作：docker.save, docker.pull, docker.inspect
  ↓
[框架固定] Tar解压：tar.unpack, tar.list_layers
  ↓
[框架固定] 文件列表：file.list_layer_files
  ↓
[规则引擎] 路径过滤 + 扩展名黑名单
  ↓
[LLM决策1] 文件筛选：批量分析过滤后的文件，决定哪些需要扫描
  ↓
[框架固定] 内容扫描：对选定文件调用content_scanner (逐个扫描)
  ↓
[LLM决策2] 凭证评估：批量评估发现的凭证，判断真实性
  ↓
[LLM决策3] 异常处理：凭证验证失败时，决定保留/丢弃
  ↓
[框架固定] 结果输出：生成报告
```

---

## 🏗️ 架构变更说明

### ✅ 保留的部分（无需修改）

- **工具层** (`imagescan/tools/`)
  - `registry.py` - 工具注册表
  - `docker_tools.py` - Docker工具
  - `tar_tools.py` - Tar工具
  - `file_tools.py` - 文件操作工具

- **数据层** (`imagescan/models/`, `imagescan/utils/database.py`)
  - `task.py` - ScanTask模型
  - `credential.py` - Credential模型
  - `layer.py` - ScanLayer模型
  - `metadata.py` - ScanMetadata模型
  - `database.py` - 数据库操作

- **事件系统** (`imagescan/core/events.py`, `event_bus.py`)
  - 保留但优化：历史大小1000→500，移除DEBUG事件

### ❌ 删除的部分

- `agents/master_agent.py`
- `agents/executor_agent.py`
- `agents/validation_agent.py`
- `agents/reflection_agent.py`
- `agents/knowledge_agent.py`
- `tests/unit/test_*_agent.py` (所有Agent测试)

- `core/agent.py` - 保留基类，供ScanAgent继承

### 🆕 新建的部分

- `imagescan/agents/scan_agent.py` - 单一智能体
- `imagescan/utils/rules.py` - 规则引擎
- `imagescan/core/llm_parser.py` - LLM函数调用字符串解析器
- `imagescan/utils/summary.py` - 摘要管理器
- `imagescan/core/content_scanner.py` (重构) - 保留读取功能，移除LLM调用

### 🔧 重构的部分

- `imagescan/core/filename_analyzer.py` - 移除LLM调用，改为规则过滤
- `imagescan/core/content_scanner.py` - 完全重写，只保留文件读取功能
- `config.toml` - 添加新配置项

---

## 阶段 1: 规则引擎与配置

**目标**：实现规则引擎，更新配置系统


### 步骤

#### 1.1 规则引擎实现

**新建文件**: `imagescan/utils/rules.py`

```python
from typing import List
import os

class RuleEngine:
    """规则引擎 - 路径和扩展名过滤"""

    def __init__(self, config):
        self.prefix_exclude = config.filter_rules.prefix_exclude
        self.extension_blacklist = config.filter_rules.extension_blacklist

    def filter_files(self, files: List[str]) -> List[str]:
        """
        应用规则过滤文件列表

        Args:
            files: 文件路径列表

        Returns:
            filtered_files: 过滤后的文件列表
        """
        filtered = []

        for file_path in files:
            # 1. 路径前缀过滤
            if self._match_prefix_exclude(file_path):
                continue

            # 2. 扩展名黑名单过滤
            if self._match_extension_blacklist(file_path):
                continue

            filtered.append(file_path)

        return filtered

    def _match_prefix_exclude(self, file_path: str) -> bool:
        """检查是否匹配前缀排除规则"""
        for prefix in self.prefix_exclude:
            if file_path.startswith(prefix):
                return True
        return False

    def _match_extension_blacklist(self, file_path: str) -> bool:
        """检查是否匹配扩展名黑名单"""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in self.extension_blacklist
```

**验收标准**：
- [ ] 规则引擎可正确过滤文件路径
- [ ] 前缀排除规则正常工作
- [ ] 扩展名黑名单正常工作

#### 1.2 配置文件更新

**文件**: `config.toml`

**新增配置项**：

```toml
[filter_rules]
# 现有配置
prefix_exclude = ["/usr", "/lib", "/bin", "/etc/ssl", "/var/lib"]
low_probability_keywords = ["node_modules", ".git", "__pycache__"]

# 新增：扩展名黑名单
extension_blacklist = [
    ".png", ".jpg", ".jpeg", ".gif", ".ico",  # 图片
    ".mp4", ".mp3", ".wav",  # 媒体
    ".zip", ".tar", ".gz", ".bz2",  # 压缩包
    ".so", ".dll", ".exe",  # 二进制
]

[llm]
# Token限制（分级）
filename_analysis_tokens = 1000
credential_evaluation_tokens = 2000
exception_handling_tokens = 500

# 超时配置
timeout_seconds = 60

# 摘要阈值
summary_token_threshold = 10000
```

**验收标准**：
- [ ] 配置文件包含所有新配置项
- [ ] 配置可正确加载

#### 1.3 重构filename_analyzer

**文件**: `imagescan/core/filename_analyzer.py`

**变更**：
- 移除LLM调用逻辑
- 改为调用规则引擎
- 保持接口不变

```python
class FilenameAnalyzer:
    """文件名分析器 - 使用规则引擎过滤"""

    def __init__(self, rule_engine: RuleEngine):
        self.rule_engine = rule_engine

    def analyze(self, files: List[str]) -> dict:
        """
        分析文件名（使用规则引擎）

        Args:
            files: 文件路径列表

        Returns:
            分类结果
        """
        filtered = self.rule_engine.filter_files(files)

        return {
            "filtered_files": filtered,
            "excluded_count": len(files) - len(filtered),
            "total_count": len(files)
        }
```

**验收标准**：
- [ ] filename_analyzer不再调用LLM
- [ ] 使用规则引擎过滤文件
- [ ] 接口保持兼容

---

## 阶段 2: LLM解析器与摘要管理

**目标**：实现LLM函数调用字符串解析器和摘要管理器


### 步骤

#### 2.1 LLM函数调用字符串解析器

**新建文件**: `imagescan/core/llm_parser.py`

```python
import ast
from typing import Dict, Any, Optional, List

class LLMFunctionCallParser:
    """LLM函数调用字符串解析器"""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def parse(self, llm_output: str) -> Dict[str, Any]:
        """
        解析LLM输出的函数调用字符串

        Args:
            llm_output: LLM输出文本，如 docker_save("nginx:latest", "./output.tar")

        Returns:
            {function_name: str, args: Dict}

        Raises:
            ParseError: 解析失败
        """
        call_str = self._extract_call_string(llm_output)
        if not call_str:
            raise ParseError("No function call found")

        try:
            tree = ast.parse(call_str, mode='eval')
            call = tree.body

            if not isinstance(call, ast.Call):
                raise ParseError("Not a function call")

            func_name = self._get_function_name(call)
            args = self._parse_arguments(call)

            return {"function_name": func_name, "args": args}
        except (SyntaxError, ValueError) as e:
            raise ParseError(f"Parse error: {e}")

    def _extract_call_string(self, llm_output: str) -> Optional[str]:
        """从LLM输出中提取函数调用字符串"""
        lines = llm_output.strip().split('\n')
        for line in lines:
            line = line.strip()
            if '(' in line and ')' in line:
                return line
        return None

    def _get_function_name(self, call: ast.Call) -> str:
        """获取函数名"""
        if isinstance(call.func, ast.Name):
            return call.func.id
        elif isinstance(call.func, ast.Attribute):
            return call.func.attr
        raise ParseError("Unsupported function type")

    def _parse_arguments(self, call: ast.Call) -> Dict[str, Any]:
        """解析函数参数"""
        args = []
        for arg in call.args:
            args.append(self._parse_value(arg))

        kwargs = {}
        for keyword in call.keywords:
            if keyword.arg:
                kwargs[keyword.arg] = self._parse_value(keyword.value)

        return {"args": args, "kwargs": kwargs}

    def _parse_value(self, node) -> Any:
        """解析AST节点为Python值"""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Str):
            return node.s
        elif isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.List):
            return [self._parse_value(e) for e in node.elts]
        raise ParseError(f"Unsupported value type: {type(node)}")


class ParseError(Exception):
    """解析错误"""
    pass
```

**验收标准**：
- [ ] 可解析 `docker_save("nginx", "./out")`
- [ ] 可解析多参数函数调用
- [ ] 解析失败抛出ParseError
- [ ] AST解析安全

#### 2.2 摘要管理器

**新建文件**: `imagescan/utils/summary.py`

```python
from typing import List, Dict
from datetime import datetime
import json

class SummaryManager:
    """摘要管理器 - 规则生成摘要"""

    def __init__(self, token_threshold: int = 10000):
        self.token_threshold = token_threshold
        self.conversation_history: List[Dict] = []

    def add_message(self, role: str, content: str):
        """添加对话消息"""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })

    def should_summarize(self) -> bool:
        """判断是否需要生成摘要"""
        total_chars = sum(len(msg["content"]) for msg in self.conversation_history)
        estimated_tokens = total_chars / 4
        return estimated_tokens > self.token_threshold

    def summarize(self) -> str:
        """生成摘要"""
        parts = []

        # 工具调用统计
        tool_calls = self._extract_tool_calls()
        parts.append(f"工具调用: {len(tool_calls)}次")
        if tool_calls:
            parts.append("使用工具: " + ", ".join(set(tool_calls)))

        # 凭证统计
        creds = self._extract_credentials_count()
        parts.append(f"发现凭证: {creds}个")

        # 错误统计
        errors = self._extract_errors()
        if errors:
            parts.append(f"错误: {len(errors)}个")

        parts.append(f"对话轮次: {len(self.conversation_history)}")

        return "\n".join(parts)

    def get_context(self) -> List[Dict]:
        """获取用于LLM调用的上下文"""
        if self.should_summarize():
            summary = self.summarize()
            return [
                {"role": "system", "content": f"对话摘要:\n{summary}"},
                *self.conversation_history[-5:]
            ]
        return self.conversation_history

    def _extract_tool_calls(self) -> List[str]:
        """提取工具调用"""
        calls = []
        for msg in self.conversation_history:
            if msg["role"] == "tool":
                try:
                    data = json.loads(msg["content"])
                    if "tool" in data:
                        calls.append(data["tool"])
                except:
                    pass
        return calls

    def _extract_credentials_count(self) -> int:
        """提取凭证数量"""
        count = 0
        for msg in self.conversation_history:
            if "credential" in msg["content"].lower():
                count += msg["content"].count("credential")
        return count

    def _extract_errors(self) -> List[str]:
        """提取错误"""
        return [msg["content"] for msg in self.conversation_history if msg["role"] == "error"]
```

**验收标准**：
- [ ] 追踪对话历史
- [ ] 超过阈值时触发摘要
- [ ] 摘要包含关键信息
- [ ] get_context返回正确上下文

#### 2.3 重构content_scanner

**文件**: `imagescan/core/content_scanner.py`

**变更**：移除LLM调用，只保留文件读取

```python
import aiofiles
import os

class ContentScanner:
    """内容扫描器 - 只负责读取文件"""

    async def read_file(self, file_path: str, max_size: int = 1024 * 1024) -> Optional[str]:
        """读取文件内容"""
        if os.path.getsize(file_path) > max_size:
            return None

        try:
            async with aiofiles.open(file_path, 'r') as f:
                return await f.read()
        except Exception as e:
            logger.error("Read failed", path=file_path, error=str(e))
            return None

    async def read_binary_file(self, file_path: str, max_size: int = 1024 * 1024) -> Optional[bytes]:
        """读取二进制文件"""
        if os.path.getsize(file_path) > max_size:
            return None

        try:
            async with aiofiles.open(file_path, 'rb') as f:
                return await f.read()
        except Exception as e:
            logger.error("Read binary failed", path=file_path, error=str(e))
            return None
```

**验收标准**：
- [ ] content_scanner不再调用LLM
- [ ] 正确读取文本/二进制文件
- [ ] 文件大小限制正常工作

---

## 阶段 3: ScanAgent实现

**目标**：实现单一智能体ScanAgent


### 核心设计

**新建文件**: `imagescan/agents/scan_agent.py`

```python
class ScanAgent(Agent):
    """
    扫描智能体 - 单一智能体实现

    职责：
    1. 执行扫描流程（框架固定部分 + LLM决策部分）
    2. 多次LLM决策：文件筛选、凭证评估、异常处理
    3. 工具调用：手动解析函数调用字符串
    """

    def __init__(self, event_bus, llm_client, tool_registry, rule_engine,
                 summary_manager, content_scanner, task_id, image_name, config):
        super().__init__(event_bus, "scan_agent")
        self.llm = llm_client
        self.tools = tool_registry
        self.rule_engine = rule_engine
        self.summary = summary_manager
        self.scanner = content_scanner
        self.task_id = task_id
        self.image_name = image_name
        self.config = config
        self.parser = LLMFunctionCallParser()
        self.credentials = []

    async def run(self):
        """运行扫描智能体"""
        # 1. 框架：Docker操作
        await self._docker_operations()

        # 2. 框架：Tar解压
        layers = await self._tar_extraction()

        # 3. 框架：文件列表
        all_files = await self._collect_all_files(layers)

        # 4. 规则引擎：过滤
        filtered_files = self.rule_engine.filter_files(all_files)

        # 5. LLM决策1：文件筛选
        files_to_scan = await self._llm_filename_decision(filtered_files)

        # 6. 框架：内容扫描
        scan_results = await self._scan_files(files_to_scan, layers)

        # 7. LLM决策2：凭证评估
        validated_credentials = await self._llm_credential_evaluation(scan_results)

        # 8. LLM决策3：异常处理
        final_credentials = await self._llm_exception_handling(validated_credentials)

        # 9. 框架：保存结果
        await self._save_results(final_credentials)

        # 10. 发布完成事件
        await self._publish_completion()
```

**System Prompt模板**：

```python
# 文件筛选System Prompt
FILENAME_SYSTEM_PROMPT = """
你是Docker镜像文件安全分析专家。

你可以使用以下工具：
- file.extract_from_layer(layer_path, file_path, output_path)
- file.read_content(file_path)

决策标准：
- .env, .config, config.json: 高优先级
- *.pem, *.key, *.cert: 高优先级
- __pycache__, node_modules: 低优先级

输出格式：函数调用字符串
file.extract_from_layer("layer_tar", "/app/config.json", "./output")
"""

# 内容扫描System Prompt
CONTENT_SYSTEM_PROMPT = """
你是凭证检测专家。

检测目标：
1. API Keys (AWS, Google, GitHub)
2. 密码
3. Tokens (JWT, OAuth)
4. 证书/私钥

返回JSON：
{"credentials": [{"type": "api_key", "value": "...", "confidence": 0.95}]}
"""

# 凭证评估System Prompt
EVALUATION_SYSTEM_PROMPT = """
你是安全评估专家。

评估标准：
- 格式正确
- 熵值足够
- 上下文支持
- 非测试数据

返回JSON：
{"validated_credentials": [{"credential_id": "...", "is_valid": true}]}
"""
```

**验收标准**：
- [ ] ScanAgent执行完整流程
- [ ] 3个LLM决策点正常工作
- [ ] 工具调用正常
- [ ] 事件正确发布
- [ ] 结果正确保存

---

## 阶段 4: 集成与测试

**目标**：集成所有组件，端到端测试


### 步骤

#### 4.1 CLI集成

**文件**: `imagescan/cli/main.py`

```python
@app.command()
def scan(image_name: str = typer.Argument(...)):
    """扫描 Docker 镜像"""

    # 加载配置
    config = Config.load()

    # 初始化组件
    event_bus = EventBus()
    db = Database(config.storage.database_path)
    await db.init()

    tool_registry = registry
    rule_engine = RuleEngine(config)
    summary_manager = SummaryManager(config.llm.summary_token_threshold)
    content_scanner = ContentScanner()
    llm_client = LLMClient(config)

    # 创建任务
    task = ScanTask(image_name=image_name, image_id="")
    task_id = await db.insert_task(task)

    # 创建ScanAgent
    scan_agent = ScanAgent(
        event_bus=event_bus,
        llm_client=llm_client,
        tool_registry=tool_registry,
        rule_engine=rule_engine,
        summary_manager=summary_manager,
        content_scanner=content_scanner,
        task_id=task_id,
        image_name=image_name,
        config=config
    )

    # 订阅进度事件
    event_bus.subscribe("task.started", lambda e: console.print("🚀 Started"))
    event_bus.subscribe("layer.completed", lambda e: console.print(f"✅ Layer: {e.layer_id}"))
    event_bus.subscribe("credential.found", lambda e: console.print(f"🔑 Found: {e.credential.get('type')}"))
    event_bus.subscribe("task.completed", lambda e: console.print(f"✅ Done! Found {e.credentials_count} credentials"))

    # 运行
    await scan_agent.run()
```

#### 4.2 事件系统优化

**文件**: `imagescan/core/event_bus.py`

```python
class EventBus:
    def __init__(self, max_history=500):  # 默认500
        self.queue = asyncio.Queue()
        self.subscribers = {}
        self.max_history = max_history
        self.history = []

    async def publish(self, event: BaseModel):
        """发布事件"""
        await self.queue.put(event)

        # 记录历史（非DEBUG事件）
        if not event.event_type.startswith("debug"):
            self.history.append(event)
            if len(self.history) > self.max_history:
                self.history.pop(0)
```

#### 4.3 端到端测试

**测试镜像**: `20.205.173.138:5000/ql_csdl_giao_thong/ql_csdl_giao_thong_be:a69a2e00`

**验收**：
- [ ] 扫描成功完成
- [ ] 发现至少1个凭证
- [ ] 置信度>0.5
- [ ] 性能<5分钟/GB

#### 4.4 文档更新

更新以下文档：
- `CLAUDE.md` - 项目指南
- `docs/AGENT_ENHANCEMENT_PLAN.md` - 标记已完成
- `progress.txt` - 更新进度

---

## 验收标准总结

### 阶段 1 验收

- [ ] 规则引擎正确过滤文件
- [ ] config.toml包含新配置
- [ ] filename_analyzer不调用LLM

### 阶段 2 验收

- [ ] LLM解析器解析函数调用
- [ ] 摘要管理器生成摘要
- [ ] content_scanner不调用LLM

### 阶段 3 验收

- [ ] ScanAgent执行完整流程
- [ ] LLM决策点工作正常
- [ ] 工具调用正常

### 阶段 4 验收

- [ ] CLI命令正常
- [ ] 端到端测试通过
- [ ] 性能达标
- [ ] 文档已更新

---

## 附录

### 文件变更清单

**新建**：
- `imagescan/utils/rules.py`
- `imagescan/core/llm_parser.py`
- `imagescan/utils/summary.py`
- `imagescan/agents/scan_agent.py`

**删除**：
- `imagescan/agents/master_agent.py`
- `imagescan/agents/executor_agent.py`
- `imagescan/agents/validation_agent.py`
- `imagescan/agents/reflection_agent.py`
- `imagescan/agents/knowledge_agent.py`
- `tests/unit/test_*_agent.py`

**重构**：
- `imagescan/core/filename_analyzer.py`
- `imagescan/core/content_scanner.py`
- `imagescan/core/event_bus.py`
- `config.toml`
- `imagescan/cli/main.py`

**保留**：
- `imagescan/tools/`
- `imagescan/models/`
- `imagescan/utils/database.py`
- `imagescan/utils/config.py`
- `imagescan/utils/logger.py`
- `imagescan/core/events.py`
- `imagescan/core/llm_client.py`


**文档版本**: 2.0.0
**最后更新**: 2025-03-02
**作者**: Claude (基于用户29轮问答的决策)
