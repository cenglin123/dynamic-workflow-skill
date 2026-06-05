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

### executor.py 自动化调用

executor.py 通过 `opencode run --format json` 调用 opencode CLI：

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

## A.3 codex (OpenAI Codex CLI)

优先探测 `multi_agent_v1`。

> ⚠️ **API 差异**：`multi_agent_v1.spawn_agent` 当前暴露的参数为 `message`/`items`/`fork_context`，**不支持** `schema`/`label`/`model`/`isolation`/`agentType` 等 opts。schema 验证需在 prompt 中描述输出格式 + Orchestrator 手动解析/校验/重试。

| 能力 | 实现 |
|------|------|
| **Spawn** | `multi_agent_v1.spawn_agent`。参数：`message`（prompt 文本）、`items`、`fork_context`。**不支持** `schema`/`label`/`model`/`isolation`/`agentType` |
| **Wait** | `multi_agent_v1.wait_agent(targets=[...])` |
| **Continue** | `multi_agent_v1.send_input(target=<agent_id>)` |
| **Close** | `multi_agent_v1.close_agent(target=<agent_id>)`；完成后必须关闭，避免悬挂 agent |
| **Identify** | Spawn 返回 agent_id。Orchestrator 需维护 agent_id → item 的外部映射表（scheduler 当前不追踪 agent_id） |

### Codex 专属约束

1. **显式授权**：只有用户明确请求 subagent/delegation/workflow 时才 spawn agent。避免 `pipeline`/`fan-out` 等关键词在普通任务中误触发
2. **不默认嵌套**：层级编排优先 Orchestrator 集中调度
3. **文件可见性保守**：不假设 agent A 的修改对 B 自动可见。Executor 返回时列 changed paths/diff
4. **模型继承优先**：不设置 model override 除非用户明确指定
5. **关闭已完成 agent**：完成后调 Close；失败时在 state 中记录。scheduler 当前不追踪 agent 生命周期——Orchestrator 需在 dispatch 和 complete 之间维护 agent_id 映射
6. **tool_search 探测**：首次使用前用 `tool_search` 验证 `multi_agent_v1` 是否可用

### 降级

`multi_agent_v1` 不可用时按 A.4 通用降级策略。

---

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
