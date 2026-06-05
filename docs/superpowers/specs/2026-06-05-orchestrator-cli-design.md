---
type: design-spec
title: executor.py — CLI 执行器
created: 2026-06-05
revised: 2026-06-05
status: approved
revision: 2
---

# executor.py — CLI 执行器设计

> 让 workflow 可以通过 CLI 自动调用 opencode 和 codex，无需手动 dispatch → spawn → complete 循环。

## 背景

当前 scheduler.py 是纯状态机——只返回 `{"action": "spawn", ...}` 让 Executor 去执行。用户需要手动调用框架的 API/CLI 来完成 agent 任务。这限制了 workflow 的自动化程度。

本设计新增 `executor.py` 作为 CLI 执行器，通过 scheduler.py 的 **library API**（`get_next_action` / `apply_result`）读取调度结果，调用 opencode/codex CLI 执行 agent 任务，并将结果写回 scheduler。

> **命名说明**：文件名用 `executor` 而非 `orchestrator`，避免与 converge SKILL 中的 Orchestrator 角色混淆。本文件是 thin executor——只负责"执行"，不负责"编排决策"（决策由 scheduler.py 完成）。

## 架构

```
executor.py (执行循环)
    │
    ├── scheduler.py library API（Python import，非 subprocess）
    │   ├── load_state(slug, dir) → state dict
    │   ├── get_next_action(state) → action dict（mutates state）
    │   ├── apply_result(state, item, stage, ...) → result dict（mutates state）
    │   └── save_state(state, dir)
    │
    ├── adapters/opencode.py 或 adapters/codex.py (调用 CLI)
    │
    └── .workflow/<slug>/logs/ (写入完整日志)
```

### scheduler.py library API

scheduler.py 同时暴露 CLI 和 library API 两种接口：

| 函数 | 用途 | 副作用 |
|------|------|--------|
| `load_state(slug, dir)` | 读取 state.json | 无 |
| `save_state(state, dir)` | 原子写入 state.json | 写文件 |
| `get_next_action(state)` | 获取下一步 action | **mutates state**（标记 item 为 running） |
| `apply_result(state, item, stage, result, tokens, retry, context)` | 应用执行结果 | **mutates state**（更新 item 状态、预算） |

**关键约束**：`get_next_action` 和 `apply_result` 都 mutate state in-place，调用方必须负责 `save_state`。executor.py 的调用模式：

```python
state = load_state(slug, dir)
action = get_next_action(state)   # state 被修改（item → running）
# ... 执行 ...
apply_result(state, item, stage, result=...)  # state 被修改（item → done/failed）
save_state(state, dir)            # 持久化
```

## 目录结构

```
scripts/
├── scheduler.py          # 现有：纯状态机 + library API（新增 get_next_action / apply_result）
├── executor.py           # 新增：CLI 执行器主入口（原 orchestrator.py）
└── adapters/             # 新增：框架适配器
    ├── __init__.py
    ├── base.py           # 抽象基类
    ├── opencode.py       # opencode CLI 适配
    └── codex.py          # codex CLI 适配

.workflow/
└── <slug>/
    ├── state.json        # scheduler 状态（新增 framework 字段）
    └── logs/             # 新增：完整 CLI 输出日志
        ├── <item>-<stage>.jsonl
        └── ...
```

## CLI 接口

### 核心命令

```bash
# 处理单个 item 的单个 stage（完整循环：health check → dispatch → execute → retry → log → complete）
executor.py execute-step --slug <slug> --framework <opencode|codex>

# 返回示例：
{"status":"completed","item":"a","stage":"x","result":{...}}
```

> **命令命名**：`execute-step` 而非 `dispatch`，因为它执行的是完整循环（health check → dispatch → execute → retry → log → complete），不仅仅是"派发"。

### 调试模式

```bash
# 只显示会执行什么，不实际调用 CLI
executor.py execute-step --slug <slug> --framework <opencode|codex> --dry-run
```

### 全自动循环

```bash
# 重复 execute-step 直到 done/stop
executor.py run --slug <slug> --framework <opencode|codex>

# 限制最大轮次
executor.py run --slug <slug> --framework <opencode|codex> --max-rounds 10
```

### 状态查询

```bash
# 委托给 scheduler.py status
executor.py status --slug <slug>
```

### 全局选项

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--dir` | `.workflow` | 状态文件目录 |
| `--timeout` | `300` | CLI 超时（秒） |
| `--max-retries` | `2` | 失败重试次数 |
| `--verbose` | `false` | 实时显示 CLI 输出 |

## framework 标记

`scheduler.py init` 接受 `--framework` 参数，写入 `state.json` 的顶层 `framework` 字段：

```bash
python scheduler.py init --slug my-workflow --mode pipe \
  --items a,b,c --stages x,y --framework opencode
```

state.json 中：
```json
{
  "slug": "my-workflow",
  "mode": "pipe",
  "framework": "opencode",
  ...
}
```

`status` 命令也会返回 `framework` 字段。executor.py 的 `execute-step` 命令不再需要 `--framework`（从 state.json 读取），但 CLI 仍接受 `--framework` 作为 override。

## Adapter 接口

### 数据类

```python
@dataclass
class CLIResult:
    success: bool
    final_message: str       # 提取的最终消息（存入 state.json）
    raw_output: str          # 完整输出（存入日志文件）
    error: str | None        # 错误信息（如有）
    tokens_used: int | None  # token 消耗（如 CLI 提供）
    duration_seconds: float  # 执行耗时
```

### 抽象基类

```python
class BaseAdapter(ABC):
    @abstractmethod
    def execute(self, prompt: str, workdir: str = ".") -> CLIResult:
        """执行 agent 任务，返回结构化结果"""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """检查 CLI 是否可用"""
        ...
```

### opencode 适配器

```python
# 命令: opencode run --format json --dir <workdir> "<prompt>"
# 解析: JSON 事件流，提取 type=end 时的 content
```

### codex 适配器

```python
# 命令: codex exec --json -C <workdir> "<prompt>"
# 解析: JSONL，提取最后一条 role=assistant 的 content
```

## 核心流程

```python
import sys
sys.path.insert(0, str(Path(__file__).parent))
from scheduler import load_state, save_state, get_next_action, apply_result

def execute_step(slug, framework, options):
    # 1. health check
    adapter = get_adapter(framework)
    if not adapter.health_check():
        return {"error": f"{framework} CLI not available"}

    # 2. 读取 scheduler 状态（library API）
    state = load_state(slug, options.dir)

    # 3. 获取下一步 action（library API — mutates state）
    try:
        action = get_next_action(state)
    except ValueError as e:
        return {"error": str(e)}

    if action["action"] == "done":
        return {"status": "done"}
    if action["action"] == "stop":
        return {"status": "stop", "reason": action.get("reason")}
    if action["action"] != "spawn":
        return {"status": "wait", "reason": action}

    # 4. 调用 adapter 执行
    prompt = action["prompt"]  # scheduler 已渲染模板
    for attempt in range(options.max_retries + 1):
        result = adapter.execute(prompt, workdir=options.workdir)
        if result.success:
            break
        if attempt < options.max_retries:
            log(f"Retry {attempt + 1}/{options.max_retries}")

    # 5. 写日志
    write_log(slug, action["item"], action["stage"], result.raw_output)

    # 6. 应用结果（library API — mutates state）
    try:
        if result.success:
            apply_result(state, action["item"], action["stage"],
                         result=json.dumps({"summary": result.final_message}),
                         tokens=result.tokens_used)
        else:
            apply_result(state, action["item"], action["stage"], result=None)
    except ValueError as e:
        return {"error": str(e)}

    # 7. 持久化（library API — caller 负责 save）
    save_state(state, options.dir)

    return {
        "status": "completed" if result.success else "failed",
        "item": action["item"],
        "stage": action["stage"]
    }
```

## 日志格式

```jsonl
// .workflow/<slug>/logs/<item>-<stage>.jsonl
{"timestamp":"...","event":"start","item":"a","stage":"x","framework":"opencode"}
{"timestamp":"...","event":"cli_output","line":"..."}
{"timestamp":"...","event":"cli_output","line":"..."}
{"timestamp":"...","event":"end","success":true,"duration":12.3,"tokens":1500}
```

## 错误处理

| 场景 | 处理 |
|------|------|
| CLI 不存在 | health_check 失败，快速报错 |
| CLI 超时 | subprocess.TimeoutExpired → 标记失败，重试 |
| CLI crash | exit code ≠ 0 → 标记失败，重试 |
| 输出解析失败 | JSON 解析异常 → 标记失败，重试 |
| 重试耗尽 | 记录最终错误，apply_result 传 None result |
| scheduler 状态异常 | 直接报错，不重试 |

## 对现有文件的影响

- **scheduler.py**：新增 `get_next_action` / `apply_result` library API + `--framework` 参数 + `framework` 字段
- **SKILL.md**：需更新，添加 executor.py 的说明
- **refs/framework-adapters.md**：需更新，添加 CLI 调用方式
- **README.md**：需更新，添加快速入门示例

## 验收标准

1. `executor.py execute-step --slug test --dry-run` 显示会执行的命令
2. `executor.py execute-step --slug test` 自动完成 dispatch → CLI → complete 循环
3. `executor.py run --slug test` 全自动执行直到 done
4. 日志文件 `.workflow/<slug>/logs/` 包含完整 CLI 输出
5. CLI 失败时自动重试（最多 max-retries 次）
6. health_check 在 CLI 不可用时快速报错
7. `state.json` 包含 `framework` 字段（通过 `scheduler.py init --framework` 设置）
8. `from scheduler import get_next_action, apply_result` 可正常 import 且逻辑与 CLI 一致

## 修订历史

| 版本 | 变更 |
|------|------|
| v1 | 初始设计，orchestrator.py 通过 subprocess 调用 scheduler CLI |
| v2 | **Issue #1**：scheduler.py 新增 library API（`get_next_action` / `apply_result`），executor 通过 import 调用而非 subprocess<br>**Issue #2**：重命名 orchestrator.py → executor.py，避免与 converge Orchestrator 角色冲突<br>**Issue #3**：`scheduler.py init` 新增 `--framework` 参数，写入 state.json<br>**Issue #4**：executor 的 `dispatch` 命令重命名为 `execute-step`，反映完整循环职责 |
