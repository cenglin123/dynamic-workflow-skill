# executor.py CLI 执行器实现计划（Round 2 修订版）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 executor.py 作为 CLI 执行器，通过 scheduler.py 的 library API 自动调用 opencode/codex CLI 执行 agent 任务

**Architecture:** scheduler.py 暴露 library API（get_next_action / apply_result），executor.py 通过 Python import 调用这些 API，adapters/ 封装各框架的 CLI 调用

**Tech Stack:** Python 3.10+, subprocess, argparse, json

---

## Round 2 修订说明

> 本计划针对 Reviewer Round 1 发现的 4 个 blocking issues 进行修订：
>
> 1. **#1 scheduler.py 已实现**：`get_next_action`（L179）、`apply_result`（L193）、`--framework`（L743）、status 的 `framework` 字段（L672）均已存在。Task 1 收缩为"验证现有 API"。
> 2. **#2 executor.py framework 回退 bug**：原代码先调用 `get_adapter(framework)` 再 `load_state`，`framework` 可能为 None。修复为先 load_state → 读 framework → 再 get_adapter。
> 3. **#3 opencode.py 缺少 import sys**：`sys.stderr` 未导入。已在代码模板中添加 `import sys`。
> 4. **#4 apply_result 返回值格式**：现有实现返回 `{"item", "stage", "item_status"}`，非 plan 中的 `{"status", "item", "stage"}`。统一使用现有格式。

---

## 文件映射

| 文件 | 操作 | 职责 |
|------|------|------|
| `scripts/scheduler.py` | 验证（不修改） | 已有 `get_next_action` / `apply_result` library API + `--framework` 参数 |
| `scripts/adapters/__init__.py` | 创建 | 包初始化，导出 get_adapter 函数 |
| `scripts/adapters/base.py` | 创建 | CLIResult 数据类 + BaseAdapter 抽象基类 |
| `scripts/adapters/opencode.py` | 创建 | opencode CLI 适配器 |
| `scripts/adapters/codex.py` | 创建 | codex CLI 适配器 |
| `scripts/executor.py` | 创建 | CLI 执行器主入口 |
| `SKILL.md` | 修改 | 添加 executor.py 说明 |
| `README.md` | 修改 | 添加快速入门示例 |
| `refs/framework-adapters.md` | 修改 | 添加 CLI 调用方式 |

---

### Task 1: scheduler.py — 验证现有 library API

> **[Round 2 修订]** 原 Task 1 要求"新增" get_next_action / apply_result / --framework，但这些功能已全部实现。本 Task 收缩为验证现有 API 与 plan 设计一致。

**Files:**
- Read-only: `scripts/scheduler.py`

- [ ] **Step 1: 确认 get_next_action 签名与 plan 一致**

现有实现 `scheduler.py:179`：
```python
def get_next_action(state):
    """Pure logic: determine next action from state. Mutates state in-place."""
```
与 plan 设计一致：接受 state dict，返回 action dict。

验证返回值格式：
- `{"action": "spawn", "item": ..., "stage": ..., "stage_idx": ..., "prompt": ...}`
- `{"action": "done", "summary": ...}`
- `{"action": "stop", "reason": ...}`
- `{"action": "wait", "reason": ...}`

- [ ] **Step 2: 确认 apply_result 签名与 plan 一致**

现有实现 `scheduler.py:193`：
```python
def apply_result(state, item, stage, result=None, tokens=None, retry=False, context=None):
```
与 plan 设计一致。

**返回值格式差异**（已知，需适配）：
- 现有：`{"item": item, "stage": stage, "item_status": it["status"]}`
- plan 中曾写：`{"status": "done"/"retrying", "item": ..., "stage": ...}`

executor.py 必须使用现有格式 `item_status` 字段。

- [ ] **Step 3: 确认 --framework 参数和 status framework 字段已存在**

- `scheduler.py:743`：`p_init.add_argument("--framework", default=None, choices=["opencode", "codex"])`
- `scheduler.py:672`：`"framework": state.get("framework")`

均与 plan 一致，无需修改。

- [ ] **Step 4: 验证 scheduler.py CLI 可正常工作**

Run: `python scripts/scheduler.py init --slug test-api --mode pipe --items a,b --stages x,y --framework opencode`
Run: `python scripts/scheduler.py dispatch --slug test-api`
Run: `python scripts/scheduler.py complete --slug test-api --item a --stage x --result '{"ok":true}'`
Run: `python scripts/scheduler.py status --slug test-api`
Expected: 所有命令正常，status 输出包含 framework 字段

- [ ] **Step 5: 清理测试数据**

Run: `Remove-Item -Recurse -Force .workflow/test-api`

---

### Task 2: adapters/base.py — 抽象基类

**Files:**
- Create: `scripts/adapters/__init__.py`
- Create: `scripts/adapters/base.py`

- [ ] **Step 1: 创建 adapters/__init__.py**

```python
"""框架适配器包。"""

from .base import BaseAdapter, CLIResult

def get_adapter(framework: str) -> BaseAdapter:
    """获取指定框架的适配器实例。"""
    if framework == "opencode":
        from .opencode import OpenCodeAdapter
        return OpenCodeAdapter()
    elif framework == "codex":
        from .codex import CodexAdapter
        return CodexAdapter()
    else:
        raise ValueError(f"Unknown framework: {framework}")

__all__ = ["BaseAdapter", "CLIResult", "get_adapter"]
```

- [ ] **Step 2: 创建 adapters/base.py**

```python
"""框架适配器抽象基类。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CLIResult:
    """CLI 执行结果。"""
    success: bool
    final_message: str       # 提取的最终消息（存入 state.json）
    raw_output: str          # 完整输出（存入日志文件）
    error: str | None = None # 错误信息（如有）
    tokens_used: int | None = None  # token 消耗（如 CLI 提供）
    duration_seconds: float = 0.0   # 执行耗时


class BaseAdapter(ABC):
    """框架适配器抽象基类。"""

    @abstractmethod
    def execute(self, prompt: str, workdir: str = ".", timeout: int = 300, verbose: bool = False) -> CLIResult:
        """执行 agent 任务，返回结构化结果。

        Args:
            prompt: 自足的 agent 指令
            workdir: 工作目录
            timeout: 超时秒数
            verbose: 是否实时显示 CLI 输出
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """检查 CLI 是否可用。"""
        ...
```

- [ ] **Step 3: Commit**

```bash
git add scripts/adapters/
git commit -m "feat(adapters): 创建适配器包和抽象基类"
```

---

### Task 3: adapters/opencode.py — opencode 适配器

> **[Round 2 修订]** 添加了 `import sys`（blocking issue #3）。

**Files:**
- Create: `scripts/adapters/opencode.py`

- [ ] **Step 1: 创建 adapters/opencode.py**

```python
"""opencode CLI 适配器。"""

import json
import subprocess
import sys
import time
from .base import BaseAdapter, CLIResult


class OpenCodeAdapter(BaseAdapter):
    """opencode CLI 适配器。

    命令: opencode run --format json --dir <workdir> "<prompt>"
    解析: JSON 事件流，提取 type=end 时的 content
    """

    def execute(self, prompt: str, workdir: str = ".", timeout: int = 300, verbose: bool = False) -> CLIResult:
        start_time = time.time()
        cmd = ["opencode", "run", "--format", "json", "--dir", workdir, prompt]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir
            )
            duration = time.time() - start_time

            if verbose:
                print(result.stdout)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)

            if result.returncode != 0:
                return CLIResult(
                    success=False,
                    final_message="",
                    raw_output=result.stdout + result.stderr,
                    error=f"Exit code {result.returncode}",
                    duration_seconds=duration
                )

            # 解析 JSON 事件流
            final_message = self._extract_final_message(result.stdout)
            tokens_used = self._extract_tokens(result.stdout)

            return CLIResult(
                success=True,
                final_message=final_message,
                raw_output=result.stdout,
                tokens_used=tokens_used,
                duration_seconds=duration
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return CLIResult(
                success=False,
                final_message="",
                raw_output="",
                error=f"Timeout after {timeout}s",
                duration_seconds=duration
            )
        except FileNotFoundError:
            return CLIResult(
                success=False,
                final_message="",
                raw_output="",
                error="opencode CLI not found",
                duration_seconds=0
            )

    def health_check(self) -> bool:
        try:
            result = subprocess.run(
                ["opencode", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _extract_final_message(self, output: str) -> str:
        """从 JSON 事件流中提取 type=end 时的 content。"""
        lines = output.strip().split("\n")
        for line in reversed(lines):
            try:
                event = json.loads(line)
                if event.get("type") == "end":
                    return event.get("content", "")
                if event.get("type") == "text":
                    return event.get("text", "")
            except json.JSONDecodeError:
                continue
        return output.strip()

    def _extract_tokens(self, output: str) -> int | None:
        """从 JSON 事件流中提取 token 消耗。"""
        lines = output.strip().split("\n")
        for line in reversed(lines):
            try:
                event = json.loads(line)
                if event.get("type") == "end":
                    return event.get("tokens")
            except json.JSONDecodeError:
                continue
        return None
```

- [ ] **Step 2: 验证 health_check**

Run: `python -c "from scripts.adapters.opencode import OpenCodeAdapter; a = OpenCodeAdapter(); print(a.health_check())"`
Expected: True（如果 opencode 已安装）

- [ ] **Step 3: Commit**

```bash
git add scripts/adapters/opencode.py
git commit -m "feat(adapters): 实现 opencode CLI 适配器"
```

---

### Task 4: adapters/codex.py — codex 适配器

**Files:**
- Create: `scripts/adapters/codex.py`

- [ ] **Step 1: 创建 adapters/codex.py**

```python
"""codex CLI 适配器。"""

import json
import subprocess
import sys
import time
from .base import BaseAdapter, CLIResult


class CodexAdapter(BaseAdapter):
    """codex CLI 适配器。

    命令: codex exec --json -C <workdir> "<prompt>"
    解析: JSONL，提取最后一条 role=assistant 的 content
    """

    def execute(self, prompt: str, workdir: str = ".", timeout: int = 300, verbose: bool = False) -> CLIResult:
        start_time = time.time()
        cmd = ["codex", "exec", "--json", "-C", workdir, prompt]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir
            )
            duration = time.time() - start_time

            if verbose:
                print(result.stdout)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)

            if result.returncode != 0:
                return CLIResult(
                    success=False,
                    final_message="",
                    raw_output=result.stdout + result.stderr,
                    error=f"Exit code {result.returncode}",
                    duration_seconds=duration
                )

            # 解析 JSONL
            final_message = self._extract_final_message(result.stdout)

            return CLIResult(
                success=True,
                final_message=final_message,
                raw_output=result.stdout,
                duration_seconds=duration
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return CLIResult(
                success=False,
                final_message="",
                raw_output="",
                error=f"Timeout after {timeout}s",
                duration_seconds=duration
            )
        except FileNotFoundError:
            return CLIResult(
                success=False,
                final_message="",
                raw_output="",
                error="codex CLI not found",
                duration_seconds=0
            )

    def health_check(self) -> bool:
        try:
            result = subprocess.run(
                ["codex", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _extract_final_message(self, output: str) -> str:
        """从 JSONL 中提取最后一条 role=assistant 的 content。"""
        lines = output.strip().split("\n")
        for line in reversed(lines):
            try:
                event = json.loads(line)
                if event.get("role") == "assistant":
                    content = event.get("content", "")
                    if isinstance(content, list):
                        return " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                    return str(content)
            except json.JSONDecodeError:
                continue
        return output.strip()
```

- [ ] **Step 2: 验证 health_check**

Run: `python -c "from scripts.adapters.codex import CodexAdapter; a = CodexAdapter(); print(a.health_check())"`
Expected: True（如果 codex 已安装）

- [ ] **Step 3: Commit**

```bash
git add scripts/adapters/codex.py
git commit -m "feat(adapters): 实现 codex CLI 适配器"
```

---

### Task 5: executor.py — CLI 执行器主入口

> **[Round 2 修订]** 修复 blocking issue #2：cmd_execute_step 中 framework 回退逻辑 bug。原代码先用 `args.framework`（可能为 None）调用 `get_adapter` 做 health check，才从 state 回退读取 framework。修复为先 `load_state` → 读取 framework → 再 `get_adapter` + health_check。
>
> 修复 blocking issue #4：apply_result 返回值使用现有格式 `item_status` 字段。

**Files:**
- Create: `scripts/executor.py`

- [ ] **Step 1: 创建 executor.py 主入口**

```python
#!/usr/bin/env python3
"""CLI 执行器 — 自动调用 opencode/codex 执行 agent 任务。

用法:
  python executor.py execute-step --slug <slug> [--framework <opencode|codex>]
  python executor.py run --slug <slug> [--framework <opencode|codex>]
  python executor.py status --slug <slug>
"""

import argparse
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# 添加当前目录到 path，以便 import scheduler
sys.path.insert(0, str(Path(__file__).parent))

from scheduler import load_state, save_state, get_next_action, apply_result
from adapters import get_adapter


DEFAULT_DIR = ".workflow"


def _timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_dir(slug, base_dir):
    return Path(base_dir) / slug / "logs"


def _write_log(slug, item, stage, raw_output, base_dir):
    """写入完整 CLI 输出日志。"""
    log_dir = _log_dir(slug, base_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{item}-{stage}.jsonl"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": _timestamp(),
            "event": "cli_output",
            "output": raw_output
        }, ensure_ascii=False) + "\n")


def cmd_execute_step(args):
    """处理单个 item 的单个 stage。"""
    # [Round 2 fix #2] 先读取 state，再确定 framework，再 get_adapter
    # 1. 读取状态
    state = load_state(args.slug, args.dir)

    # 2. 确定 framework（CLI 参数优先，否则从 state 回退）
    framework = args.framework or state.get("framework")
    if not framework:
        print(json.dumps({"error": "No framework specified. Use --framework or set during init."}), file=sys.stderr)
        sys.exit(1)

    # 3. health check（此时 framework 已确定，不会传 None）
    try:
        adapter = get_adapter(framework)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    if not adapter.health_check():
        print(json.dumps({"error": f"{framework} CLI not available"}), file=sys.stderr)
        sys.exit(1)

    # 4. 获取下一步 action
    try:
        action = get_next_action(state)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    if action["action"] == "done":
        print(json.dumps({"status": "done", "summary": action.get("summary")}))
        return
    if action["action"] == "stop":
        print(json.dumps({"status": "stop", "reason": action.get("reason")}))
        return
    if action["action"] != "spawn":
        print(json.dumps({"status": "wait", "reason": action.get("reason", "unknown")}))
        return

    # dry-run 模式
    if args.dry_run:
        print(json.dumps({
            "action": "dry_run",
            "item": action["item"],
            "stage": action["stage"],
            "framework": framework,
            "prompt_preview": action["prompt"][:200] + "..." if len(action["prompt"]) > 200 else action["prompt"]
        }, ensure_ascii=False))
        return

    # 5. 调用 adapter 执行
    prompt = action["prompt"]
    result = None
    for attempt in range(args.max_retries + 1):
        result = adapter.execute(
            prompt,
            workdir=args.workdir or ".",
            timeout=args.timeout,
            verbose=args.verbose
        )
        if result.success:
            break
        if attempt < args.max_retries:
            print(json.dumps({"event": "retry", "attempt": attempt + 1, "error": result.error}))

    # 6. 写日志
    _write_log(args.slug, action["item"], action["stage"], result.raw_output, args.dir)

    # 7. 应用结果（使用 scheduler.py 现有返回格式：item_status）
    try:
        if result.success:
            apply_result(
                state, action["item"], action["stage"],
                result=json.dumps({"summary": result.final_message}),
                tokens=result.tokens_used
            )
        else:
            apply_result(state, action["item"], action["stage"], result=None)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    # 8. 持久化
    save_state(state, args.dir)

    # 9. 输出结果
    output = {
        "status": "completed" if result.success else "failed",
        "item": action["item"],
        "stage": action["stage"]
    }
    if not result.success:
        output["error"] = result.error
    print(json.dumps(output, ensure_ascii=False))


def cmd_run(args):
    """全自动循环：重复 execute-step 直到 done/stop。"""
    round_count = 0
    while True:
        round_count += 1
        if args.max_rounds and round_count > args.max_rounds:
            print(json.dumps({"event": "max_rounds_reached", "rounds": round_count - 1}))
            break

        # 模拟 execute-step 的参数
        step_args = argparse.Namespace(
            slug=args.slug,
            framework=args.framework,
            dir=args.dir,
            timeout=args.timeout,
            max_retries=args.max_retries,
            verbose=args.verbose,
            dry_run=False,
            workdir=args.workdir
        )

        # 捕获输出
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cmd_execute_step(step_args)
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        # 解析结果
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            print(output)
            break

        if args.verbose:
            print(output)

        if result.get("status") in ("done", "stop"):
            print(output)
            break
        if result.get("status") == "failed":
            print(json.dumps({"event": "item_failed", "item": result.get("item"), "stage": result.get("stage"), "error": result.get("error")}))

    print(json.dumps({"event": "run_complete", "rounds": round_count}))


def cmd_status(args):
    """显示当前状态（委托 scheduler）。"""
    from scheduler import cmd_status as scheduler_status
    scheduler_status(args)


def main():
    parser = argparse.ArgumentParser(
        prog="executor.py",
        description="CLI 执行器 — 自动调用 opencode/codex 执行 agent 任务")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="状态文件目录")
    parser.add_argument("--timeout", type=int, default=300, help="CLI 超时（秒）")
    parser.add_argument("--max-retries", type=int, default=2, help="失败重试次数")
    parser.add_argument("--verbose", action="store_true", help="实时显示 CLI 输出")
    parser.add_argument("--workdir", default=".", help="agent 工作目录")

    sub = parser.add_subparsers(dest="command", required=True)

    # execute-step
    p_step = sub.add_parser("execute-step", help="处理单个 item 的单个 stage")
    p_step.add_argument("--slug", required=True)
    p_step.add_argument("--framework", choices=["opencode", "codex"])
    p_step.add_argument("--dry-run", action="store_true", help="只显示会执行什么")

    # run
    p_run = sub.add_parser("run", help="全自动循环")
    p_run.add_argument("--slug", required=True)
    p_run.add_argument("--framework", choices=["opencode", "codex"])
    p_run.add_argument("--max-rounds", type=int, help="最大轮次")

    # status
    p_status = sub.add_parser("status", help="显示当前状态")
    p_status.add_argument("--slug", required=True)

    args = parser.parse_args()

    if args.command == "execute-step":
        cmd_execute_step(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证 --help**

Run: `python scripts/executor.py --help`
Run: `python scripts/executor.py execute-step --help`
Expected: 显示正确的帮助信息

- [ ] **Step 3: Commit**

```bash
git add scripts/executor.py
git commit -m "feat: 新增 executor.py CLI 执行器"
```

---

### Task 6: 端到端验证

**Files:**
- None（只验证）

- [ ] **Step 1: 初始化 workflow（带 framework）**

Run: `python scripts/scheduler.py init --slug e2e-test --mode pipe --items a,b --stages x,y --framework opencode`
Expected: state.json 包含 framework 字段

- [ ] **Step 2: dry-run 验证**

Run: `python scripts/executor.py execute-step --slug e2e-test --dry-run`
Expected: 显示 action、item、stage、framework 信息

- [ ] **Step 3: 真实执行（如果 opencode 可用）**

Run: `python scripts/executor.py execute-step --slug e2e-test --verbose`
Expected: 调用 opencode CLI，state 更新

- [ ] **Step 4: 验证日志文件**

Run: `ls .workflow/e2e-test/logs/`
Expected: 存在 a-x.jsonl 日志文件

- [ ] **Step 5: 清理测试数据**

Run: `Remove-Item -Recurse -Force .workflow/e2e-test`

- [ ] **Step 6: Commit 验证结果**

```bash
git status
git commit -m "test: executor.py 端到端验证通过" --allow-empty
```

---

### Task 7: 更新文档

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `refs/framework-adapters.md`

- [ ] **Step 1: 更新 SKILL.md 执行流程段落**

在 "### 使用 scheduler.py（推荐）" 之后添加：

```markdown
### 使用 executor.py（自动化）

非 CC 框架用户通过 `scripts/executor.py` 实现全自动编排。executor.py 读取 scheduler 的 dispatch 结果，自动调用 opencode/codex CLI 执行 agent 任务：

```bash
# 单步执行
executor.py execute-step --slug <slug> --framework opencode

# 全自动循环
executor.py run --slug <slug> --framework opencode
```

executor.py 通过 scheduler.py 的 library API（`get_next_action` / `apply_result`）交互，无需 subprocess 调用。
```

- [ ] **Step 2: 更新 SKILL.md 拆分文件索引**

添加：
```markdown
| CLI 执行器（自动调用 opencode/codex） | `scripts/executor.py` |
| 框架适配器 | `scripts/adapters/` |
```

- [ ] **Step 3: 更新 README.md**

在 "### 什么时候用" 之后添加：

```markdown
### 快速开始（自动化执行）

```bash
# 1. 初始化 workflow
python scripts/scheduler.py init --slug my-workflow --mode pipe \
  --items src/auth/,src/api/ --stages review,verify --framework opencode

# 2. 全自动执行
python scripts/executor.py run --slug my-workflow
```
```

- [ ] **Step 4: 更新 refs/framework-adapters.md**

在 A.2 opencode 部分添加：

```markdown
### executor.py 自动化调用

executor.py 通过 `opencode run --format json` 调用 opencode CLI：

```bash
executor.py execute-step --slug <slug> --framework opencode
```

完整输出存储在 `.workflow/<slug>/logs/<item>-<stage>.jsonl`。
```

- [ ] **Step 5: Commit**

```bash
git add SKILL.md README.md refs/framework-adapters.md
git commit -m "docs: 添加 executor.py 使用说明"
```

---

### Task 8: 最终清理

- [ ] **Step 1: 运行 scheduler.py 确认无回归**

Run: `python scripts/scheduler.py --help`
Run: `python scripts/scheduler.py init --slug final-test --mode pipe --items a --stages x`
Run: `python scripts/scheduler.py dispatch --slug final-test`
Run: `python scripts/scheduler.py complete --slug final-test --item a --stage x --result '{"ok":true}'`
Run: `python scripts/scheduler.py status --slug final-test`
Expected: 所有命令正常

- [ ] **Step 2: 清理测试数据**

Run: `Remove-Item -Recurse -Force .workflow/final-test`

- [ ] **Step 3: 最终 Commit**

```bash
git add -A
git commit -m "feat: executor.py CLI 执行器完成（opencode/codex 自动化调用）"
```
