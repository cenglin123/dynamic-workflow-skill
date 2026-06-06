---
id: bugfix-codex-adapter-protocol
type: bugfix
title: Codex 0.137.0 CLI 协议解析与非交互执行修复
status: fixed
severity: high
scope:
  - cli
  - scheduler
modules:
  - scripts/adapters/codex.py
  - scripts/executor.py
tags:
  - codex
  - jsonl
  - utf-8
  - session
  - sandbox
symptoms:
  - Codex 最终消息被整段 JSONL 替代
  - returncode=0 但缺少 completed agent_message 时被误判为成功
  - token 预算每次回退到固定估算值
  - Windows 下 npm codex shim 无法由 Python subprocess 启动
error_signatures:
  - item.completed
  - turn.completed.usage
  - thread.started
  - FileNotFoundError WinError 2
related_files:
  - scripts/adapters/base.py
  - scripts/adapters/codex.py
  - scripts/adapters/__init__.py
  - scripts/executor.py
  - tests/fixtures/codex-0.137.0-basic.jsonl
  - tests/test_adapters.py
  - tests/test_executor.py
verification:
  level: automated
  kind: regression-test
  path: tests/test_adapters.py
  command: pytest -q
created_at: 2026-06-06
updated_at: 2026-06-06
---

# Codex 0.137.0 CLI 协议解析与非交互执行修复

## 现在的行为

修复前，adapter 按不存在的 `role=assistant/content` 格式解析 Codex JSONL，导致 scheduler 收到整段 stdout；`turn.completed.usage` 和 `thread.started.thread_id` 也未读取。外部命令没有显式 approval、sandbox、schema、ephemeral/resume 和 UTF-8 策略。Windows 环境中，Python `subprocess` 直接执行 `"codex"` 还会因 npm shim 是 `codex.CMD` 而返回 `FileNotFoundError`。

## 预期的行为

adapter 应提取最后一个 `item.completed` 中 `item.type=agent_message` 的 `item.text`，以最后一个 `turn.completed.usage` 的 `input_tokens + output_tokens` 计入预算，并把 `thread.started.thread_id` 放入 `CLIResult.metadata`。returncode 为 0 但缺少 completed agent message 时必须返回协议失败，`final_message` 为空且原始 JSONL 仅保存在 `raw_output`。命令应使用 argv 列表、顶层 `--ask-for-approval never`、可配置 sandbox、可选 schema、ephemeral 或 resume，并显式按 UTF-8 解码。

## 复现方式

实际执行 `codex-cli 0.137.0`：

```powershell
codex --version
codex exec --help
codex exec resume --help
codex --ask-for-approval never --sandbox read-only --cd . exec --ephemeral --json "Reply exactly with: 中文测试"
```

真实输出依次包含 `thread.started`、`turn.started`、`item.completed` 和 `turn.completed`。修复前运行以下 focused suite 得到预期 RED：

```powershell
$env:PYTHONUTF8='1'; pytest -q tests/test_adapters.py tests/test_executor.py
```

结果为 `7 failed, 19 passed`，失败点覆盖消息、usage、thread id、命令构造和参数校验。

Windows shim 问题另以以下测试复现：

```powershell
$env:PYTHONUTF8='1'; pytest -q tests/test_adapters.py::TestCodexAdapter::test_resolves_windows_command_shim
```

结果为 `1 failed`，实际首个 argv 为 `codex`，预期为 `shutil.which` 返回的 `codex.CMD`。

## 原因是什么

1. 测试 fixture 复制了错误假设，没有使用 Codex 0.137.0 的真实事件协议。
2. adapter 没有解析 usage 和 thread id，scheduler 因 `tokens_used=None` 回退到固定 token 估算。
3. 原生 `multi_agent_v1` 与外部 `codex exec` 的能力文档混在一起，掩盖了外部 CLI 的 schema、session 和 sandbox 能力。
4. `subprocess.run(text=True)` 依赖系统默认编码，且 stdin 未关闭。
5. Windows PowerShell 能解析 `codex.ps1`，但 Python 不会以同样方式执行 npm shim；必须解析实际 `codex.CMD` 路径。
6. 旧 fallback 把“没有 agent message”视为可接受输出，导致 returncode=0 的不完整协议流被静默写入 scheduler state。
7. 同步回归曾覆盖已验收修复：相对 workdir 同时传给 `cwd` 和 `--cd`，schema 未以 effective workdir 解析，且 `run` 可复用 session id。

## 怎么修复的

- 增加 Codex 0.137.0 JSONL fixture，跳过损坏行并保留中文文本，选择最后一个 agent message。
- 没有 completed agent message 时返回 `success=False` 和明确的 `Codex protocol error`，不再把 raw JSONL 当作成功消息。
- 解析最后一个 usage，预算只计 input 与 output，避免重复累计 cached input。
- 为 `CLIResult` 增加向后兼容的 `metadata`，保存 thread id。
- `CodexAdapter` 增加窄配置：sandbox、ephemeral、output schema、session id；adapter 策略拒绝 ephemeral 与 resume 同用，不把该策略表述为所有 CLI 版本的能力限制。
- 使用顶层 approval 参数、argv 列表、`stdin=DEVNULL`、UTF-8 解码和 `shutil.which("codex")`。
- workdir 先转为一个绝对 effective workdir，同时供 subprocess `cwd` 和 Codex `--cd` 使用；相对 schema 以此目录为基准转为绝对路径。
- executor 暴露对应 CLI 参数，输出 metadata；保持现有同步串行循环，并拒绝 `run --codex-session-id`，resume 仅用于单个 `execute-step`。
- 文档拆分 Codex 原生 agent 与外部 CLI，并修正 waitAll、容量和包装日志说明。

## 验证结果

实际运行：

```powershell
$env:PYTHONUTF8='1'; pytest -q tests/test_adapters.py tests/test_executor.py
```

结果：`27 passed in 0.15s`。

实际通过 adapter 执行一次 ephemeral 中文请求，结果为成功、最终消息 `适配器验证`、usage `12276`，并取得 thread id。随后实际创建持久 session 并 resume，同一个 thread id 依次返回 `FIRST` 和 `SECOND`。

完整回归：

```powershell
$env:PYTHONUTF8='1'; pytest -q
```

结果：`91 passed, 1 skipped in 0.86s`。

Round 2 focused 回归：

```powershell
$env:PYTHONUTF8='1'; pytest -q tests/test_adapters.py tests/test_executor.py
```

同步修复后的最终结果：`31 passed in 0.21s`。

Round 2 完整回归：

```powershell
$env:PYTHONUTF8='1'; pytest -q
```

同步修复后的最终结果：`95 passed, 1 skipped in 0.93s`。

差异格式检查：

```powershell
git diff --check
```

结果：退出码 `0`；Git 仅提示工作区未来可能进行 LF/CRLF 转换，没有 whitespace error。

## 风险和后续

- 当前 `executor.py run` 明确保持串行；scheduler 的并发配置不会使它自动并发。
- 默认 sandbox 为 `read-only`。需要修改文件时必须由 operator 显式选择 `workspace-write`；`danger-full-access` 仅适用于外部已隔离环境。
- persistent 新会话的 thread id 会随 `execute-step` 输出返回；resume 需要调用方在另一次 `execute-step` 中显式传入 `--codex-session-id`，`run` 不接受该参数组合。
- 相对 workdir 和相对 output schema 均按同一个绝对 effective workdir 解析。
- 原生 `multi_agent_v1` 的 waitAll 仍是文档化的 Orchestrator pending-set 规则，不属于本次外部 CLI executor 的代码实现范围。
