# 框架适配器

> 各 agent 框架对抽象能力层（Spawn / Wait / Continue / Identify）的具体实现。

---

## A.1 Claude Code（原生 Workflow Runtime）

Claude Code v2.1.154+ 内置完整的 workflow runtime。JS 脚本中的 `agent()`、`parallel()`、`pipeline()` 等均为原生 API。

| 能力 | 实现 |
|------|------|
| **Spawn** | `agent(prompt, opts)` — 原生函数 |
| **Wait** | `parallel()` 内置屏障；`pipeline()` 内置流控 |
| **Continue** | 不需要——脚本变量持有所有中间状态 |
| **Identify** | agent id 由 runtime 管理 |

### 触发

- **单次**：prompt 含 `ultracode` 或自然语言 "use a workflow"
- **会话级**：`/effort ultracode` — xhigh 推理 + 自动编排
- `disableWorkflows: true` 或 `CLAUDE_CODE_DISABLE_WORKFLOWS=1` 关闭

### 保存与复用

- `/workflows` → 选 run → `s` 保存为 `/` 命令
- `.claude/workflows/` — 项目级（git 追踪，团队共享）
- `~/.claude/workflows/` — 用户级（跨项目可用）

### 限制

- 无中途用户输入（阶段间签核需拆为独立 workflow）
- 最多 16 并发、单次 1000 agent 总量

---

## A.2 opencode

opencode 通过 `task` 工具实现 subagent。无原生 workflow runtime，需手动组合编排原语。

> ⚠️ **核心限制**：opencode 的 `task` 工具是**同步阻塞**的——调用后当前 agent 等待 subagent 完成才继续。这意味着无法真正并行 spawn 多个 agent。`waitAll` 和 `pipe` 的并行语义在 opencode 中**降级为串行执行**（功能等价，但无并行加速）。

> 💡 **批量调用并行**：虽然单个 task 调用是同步阻塞的，但在**同一个消息中发起多个 task 调用**时，它们会**并行执行**。例如：在一条消息中同时调用 task("chunk1") 和 task("chunk2")，两个子代理会并行运行，而不是串行等待。这提供了一种在 opencode 中实现并行的变通方案。

| 能力 | 实现 |
|------|------|
| **Spawn** | `task` 工具，`subagent_type: "general"`，prompt 传入自足指令。注意：opts 中的 `schema`/`label`/`model`/`isolation`/`agentType` 均无对应参数。schema 需在 prompt 中以自然语言描述输出格式 |
| **Wait** | `task` 工具是同步阻塞的——调用后直接等待结果返回，无需额外等待机制。**不存在** `run_in_background` 或异步轮询模式 |
| **Continue** | `task` 工具 + `task_id` 参数恢复同一 subagent 会话（需验证上下文保真度） |
| **Identify** | task 返回值中的 task_id |

### pipeline 手动实现（opencode 串行降级）

由于 task 是同步阻塞的，opencode 中 pipeline 降级为串行：每个 item 依次跑完所有 stage，再处理下一个 item。无并行加速。

```
对每个 item（串行）：
  1. Spawn stage1 agent(item) → 阻塞等待完成
  2. Spawn stage2 agent(stage1_result, item) → 阻塞等待完成
  3. ... 所有 stage 完成后处理下一个 item
```

> ⚠️ SKILL 中描述的 "item B stage 1 和 item A stage 2 并发" 在 opencode 中**不可行**。

### waitAll 手动实现（opencode 串行降级）

由于 task 是同步阻塞的，无法并行启动。降级为串行执行 + 收集结果：

```
results = []
对每个 item（串行）：
  1. Spawn agent(item) → 阻塞等待完成
  2. 结果追加到 results（失败则填 null）
全部执行完毕后返回 results
```

### waitAll 批量调用（opencode 并行方案）

> 💡 **实测发现**：在同一个消息中发起多个 task 调用时，它们会并行执行。

```
// 在同一条消息中调用多个 task（并行执行）
task("处理 chunk 1")
task("处理 chunk 2")
task("处理 chunk 3")
// 三个子代理并行运行，全部完成后继续
```

**使用场景**：
- 将大文件拆分为多个 chunk，并行扫描/处理
- 多个独立模块的并行分析
- 对抗验证中多个 skeptic 的并行审查

**容量策略**：
- 批量 task 的有效容量属于当前 opencode runtime，不从 Claude Code 的 16/1000 限制外推
- 由 operator 根据版本和环境设置批大小；超过有效容量时分批，批内并行、批间串行
- scheduler 的 `max_concurrency` 只是调度上限，不证明 task executor 实际并行

**错误处理策略**：
- Orchestrator 应尽量收集所有已启动 task；runtime 是否会在单项失败时取消同批任务必须按版本验证
- 在抽象层归一化时，失败项记为 `null`，成功项保留输出，并恢复输入顺序
- 收集完毕后 Orchestrator 决定重试策略：可重试失败项、降级处理、或标记为缺失继续推进
- 每个 task 内部应自行处理可恢复错误；不可恢复错误由 task 抛出，由 Orchestrator 记录并评估影响

**其他注意事项**：
- 每个 task 调用必须是自足的（包含完整上下文）
- 结果在所有 task 完成后统一收集
- 批量调用中各 task 之间无法通信或共享状态

### executor.py 自动化调用

executor.py 通过 `opencode run --format json` 调用 opencode CLI：

> opencode adapter 通过命令行传递 prompt，受限于约 8000 字符的命令行长度上限。超长 prompt 将返回错误。

```bash
executor.py execute-step --slug <slug> --framework opencode
```

完整输出存储在 `.workflow/<slug>/logs/<item>-<stage>.jsonl`。

### 降级

- **Continue 不可用** → inner loop 由 Orchestrator 自身逐条验收（标注 `inner_loop: orchestrator_self`）
- **并行不可用**（默认）→ 所有 spawn 串行执行。通过 `scheduler.py` 的 `--mode pipe` 管理状态，Orchestrator 在单线程循环中调用 task。
- **schema 不可用** → 在 prompt 中描述输出格式要求，Orchestrator 手动解析和验证

### Prompt 内嵌循环（opencode 特有加速）

opencode 无 `/goal` 命令时，可在 `task` prompt 中直接写入循环指令：

```
重复以下步骤直到所有测试通过：
1. 运行 npm test
2. 如果有失败，修改代码修复第一个失败的测试
3. 再次运行 npm test
```

**注意**：此方式 subagent 内部无法 Spawn 独立 Reviewer——缺乏对抗式保证。retrospective 中标注 `inner_loop: prompt_embedded`。

---

## A.3 Codex

Codex 有两个不同的执行面，不能把能力合并描述：

1. **原生 `multi_agent_v1`**：当前 Codex 会话内的多 agent 工具，负责真正的 Spawn / Wait / Continue。
2. **外部 `codex exec` CLI**：由 `scripts/executor.py` 启动独立非交互进程，支持 schema、session 和 sandbox；当前 executor 循环是串行的。

### A.3.1 原生 multi_agent_v1

优先探测 `multi_agent_v1`。

> ⚠️ **API 差异**：`multi_agent_v1.spawn_agent` 当前暴露的参数为 `message`/`items`/`fork_context`，**不支持** `schema`/`label`/`model`/`isolation`/`agentType` 等 opts。原生路径的 schema 验证需在 prompt 中描述输出格式 + Orchestrator 手动解析/校验/重试。

| 能力 | 实现 |
|------|------|
| **Spawn** | `multi_agent_v1.spawn_agent`。参数：`message`（prompt 文本）、`items`、`fork_context`。**不支持** `schema`/`label`/`model`/`isolation`/`agentType` |
| **Wait** | `multi_agent_v1.wait_agent(targets=[...])`；多个 target 时返回最先进入 final status 的目标，不是 wait-all 屏障 |
| **Continue** | `multi_agent_v1.send_input(target=<agent_id>)` |
| **Resume** | `multi_agent_v1.resume_agent(id=<agent_id>)`；已关闭实例继续前必须先恢复 |
| **Close** | `multi_agent_v1.close_agent(target=<agent_id>)`；完成后必须关闭，避免悬挂 agent |
| **Identify** | Spawn 返回 agent_id。Orchestrator 需维护 agent_id → item 的外部映射表（scheduler 当前不追踪 agent_id） |

#### 原生 waitAll 正确实现

`wait_agent(targets=[...])` 是 wait-any。抽象 `waitAll` 必须由 Orchestrator 显式实现：

```
ordered_ids = spawn 后按输入顺序得到的 agent_id[]
pending = set(ordered_ids)
results_by_id = {}

while pending:
  response = wait_agent(targets=list(pending))
  statuses = response 中的 agent_id -> status map
  if statuses 为空:
    若本轮超时：按 operator 策略重试 pending，或将剩余项记为 null 并报告截断
    若未标记超时：记录空 status map 协议异常，再重试或终止
    continue 或 break
  for (id, status) in statuses:
    if id 不在 pending 或 status 尚未 final:
      continue
    results_by_id[id] = 终态成功 ? 最终输出 : null
    pending.remove(id)

results = [results_by_id.get(id, null) for id in ordered_ids]
```

- 单个 agent 失败、取消或返回不可用终态时记为 `null`，继续等待其他 pending agent
- `wait_agent` 一次可能在 status map 中返回多个终态；必须遍历全部终态并逐个从 pending 移除
- 非终态或不属于 pending 的 status 不得提前收集；最终按 `ordered_ids` 恢复原始输入顺序
- 空 status map 或 wait 超时不能伪装成全部完成；应重试仍 pending 的集合，或按 operator 策略将剩余项记为 `null` 并报告截断
- 只有确认该实例不再 Continue 时才 `close_agent`
- 若实例已经关闭但需要继续，必须 `resume_agent(id=...)`，再 `send_input(target=...)`，最后重新进入 wait 循环

### Codex 专属约束

1. **显式授权**：只有用户明确请求 subagent/delegation/workflow 时才 spawn agent。避免 `pipeline`/`fan-out` 等关键词在普通任务中误触发
2. **不默认嵌套**：层级编排优先 Orchestrator 集中调度
3. **文件可见性保守**：不假设 agent A 的修改对 B 自动可见。Executor 返回时列 changed paths/diff
4. **模型继承优先**：不设置 model override 除非用户明确指定
5. **生命周期后关闭**：仅在角色确定结束、不会再 Continue 时调 Close；失败时在 state 中记录。scheduler 当前不追踪 agent 生命周期——Orchestrator 需在 dispatch 和 complete 之间维护 agent_id 映射
6. **tool_search 探测**：首次使用前用 `tool_search` 验证 `multi_agent_v1` 是否可用
7. **容量探测**：`agents.max_threads` 默认 6，可由配置调整。该值是原生 agent runtime 的线程容量，不是外部 CLI executor 的并行度，也不存在可外推的 Codex 1000-agent 总量上限

> **barrier 后 failed items 处理策略**：当 `fail_fast=false` 时，failed items 在 barrier 后被推进至下一 stage（stage_idx +1）、状态重置为 pending、retry_count 清零、error 清除。这允许下一 stage 的 executor 重新尝试这些 items。如需保留失败记录，编排者应在 barrier 前读取各 item 的 error/retry_count。

### A.3.2 外部 codex exec CLI

`multi_agent_v1` 不可用不意味着必须降级为 `orchestrator_self`。需要持久化 scheduler 或独立进程执行时，可使用 `scripts/executor.py --framework codex`：

| 能力 | 外部 CLI 行为 |
|------|--------------|
| **新会话** | `codex --ask-for-approval never ... exec --json <prompt>` |
| **一次性会话** | 加 `--ephemeral`，不持久化 session；本 adapter 策略禁止与 resume 同用 |
| **结构化输出** | `--output-schema <schema.json>` |
| **会话标识** | 从 `thread.started.thread_id` 提取，写入 `CLIResult.metadata.thread_id` |
| **续接会话** | `codex ... exec resume --json <thread_id> <prompt>` |
| **sandbox** | operator 显式选择 `read-only` / `workspace-write` / `danger-full-access`；默认 `read-only` |
| **approval** | 非交互执行固定使用顶层 `--ask-for-approval never`，命令失败直接返回 agent，不等待人工输入 |

命令构造使用 argv 列表，不经 shell 拼接；subprocess stdin 关闭，stdout/stderr 明确按 UTF-8 解码。外部 JSONL 中：

- 最终文本来自最后一个 `item.completed` 且 `item.type=agent_message` 的 `item.text`
- token 来自最后一个 `turn.completed.usage`，预算记 `input_tokens + output_tokens`。`input_tokens` 已包含 `cached_input_tokens`，不重复累加
- 损坏 JSON 行跳过；returncode=0 但没有 completed agent message 时返回协议失败，`final_message=""`，原始 stdout 仅保留在 `raw_output`

> `ephemeral + resume` 的禁止是本 adapter 为保持清晰会话语义而实施的校验策略，不声明所有 Codex CLI 版本都缺乏该组合能力。

当前 `executor.py run` 每轮同步执行一个 `codex exec` 并立即 complete，因此实际始终串行。scheduler 的 `max_concurrency` 是 operator 配置的调度上限，不会让该循环自动并发。

`--codex-session-id` 只允许用于 `execute-step`，因为它只代表一个逻辑 Spawn 的单次续接。`run` 会跨多个 item/stage 调度，禁止传 session id，避免把本应 fresh-context 的多个 Spawn 合并进同一 thread。

工作目录先规范化为绝对路径，同一个绝对路径同时用于 subprocess `cwd` 和 Codex `--cd`，避免相对路径被解析两次。相对 `--codex-output-schema` 路径以该有效工作目录为基准解析，并以绝对路径传给 Codex。

日志 `.workflow/<slug>/logs/<item>-<stage>.jsonl` 每次调用追加一个包装 JSON 事件，完整原始 stdout 位于 `output` 字段；它不是逐行复制的 Codex 原始事件流。

### A.3.3 降级选择

- 原生工具可用且需要会话内并行：使用 `multi_agent_v1`
- 原生工具不可用但 `codex exec` 可用：使用外部 CLI；接受当前串行执行语义
- 两者都不可用：按 A.4 通用降级策略

## A.4 通用降级策略

框架完全不支持 Spawn/Wait 时：

| 能力 | 降级实现 | 代价 |
|------|---------|------|
| **Spawn** | Orchestrator 自身模拟子 agent 角色 | 无独立上下文、自审偏差 |
| **Wait** | 无并发——所有"并行"变串行 | 墙钟时间 = sum(所有 agent) 而非 max(单个) |
| **Continue** | 每轮写完整 context summary 给下一轮 | 信息压缩损失 |
| **Identify** | 手动命名/编号 | 无运行时隔离保证 |

### 降级标注

所有降级必须在最终报告中标注：
- `agent_backend: orchestrator_self` — 审查者不是独立 agent
- `concurrency: serial` — 无法并行
- `inner_loop: orchestrator_self` — 验收无独立 reviewer

> ⚠️ 降级模式下的结论可信度显著降低。对抗验证和独立审查的核心假设（fresh context）被破坏。仅用于轻量任务或框架过渡期。

---

## A.5 适配新框架

四个问题完成适配：

1. **Spawn**：如何启动带全新上下文和自足 prompt 的 agent？返回什么标识符？
2. **Wait**：如何等待 agent 完成并获取输出？支持批量等待吗？
3. **Continue**：能向已有 agent 发跟进消息且保有上下文吗？消息格式是什么？
4. **Identify**：如何引用 agent 实例？标识符在后续调用中如何使用？

完成四个问题的映射后，即可按本 SKILL 的模式（parallel/pipeline/loop + 质量模式）手动编排。

### 能力矩阵模板

| 框架 | Spawn | Wait | Continue | Identify | 备注 |
|------|-------|------|----------|----------|------|
| Claude Code | `agent()` | `parallel()` 内置 | 不需要 | runtime 管理 | 原生 workflow |
| opencode | `task` | blocking（同步等待） | `task` + task_id | task_id | 手动编排 |
| codex | `spawn_agent` | `wait_agent` | `send_input` | agent_id | multi_agent_v1 |
| （新框架） | ? | ? | ? | ? | 待适配 |
