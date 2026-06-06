---
name: dynamic-workflow
description: Use when orchestrating multiple subagents at scale in frameworks WITHOUT native workflow runtime (opencode, codex, etc.). NOT for simple subagent delegation — use your framework's native subagent tools for smaller tasks.
---

# Dynamic Workflow — 多智能体规模化编排

> 把编排计划写进代码，而非留在对话上下文。脚本持有循环、分支和中间结果，主对话只保留最终答案。
>
> **面向没有原生 workflow runtime 的执行面**：本 SKILL 提供框架无关的编排模式 + CLI 调度器（`scripts/scheduler.py`）。Codex 原生 `multi_agent_v1` 可直接映射 Spawn/Wait/Continue；外部 `codex exec` 与 opencode CLI 则由串行 `executor.py` 驱动。CC 用户已有原生 Workflow 工具，无需本 SKILL。

---

## Positioning

**目标受众**：没有原生 workflow runtime 的框架，或需要用外部 CLI + 持久化 scheduler 执行编排的用户。

| | Subagents | Skills | Agent Teams | **Workflows** |
|---|---|---|---|---|
| 谁决定下一步 | 逐轮 | 按 prompt | lead agent，逐轮 | **代码脚本** |
| 中间结果在哪 | 上下文 | 上下文 | 共享任务表 | **脚本变量 / state 文件** |
| 规模 | 每轮几个 | 同 subagent | 少量长跑 peer | **单次数十到数百** |

**核心区分**：workflow 把"计划"搬进了代码。subagent/skill/agent team 里 agent 是编排者，workflow 脚本自己持有循环/分支/中间结果。

- **适合**：codebase 级审计、大规模迁移、多源交叉验证、需要多角度起草的复杂计划
- **不适合**：单次简单委派、线性单步任务——这些用 subagent 或 skill 即可
- **可组合**：converge SKILL 可作为质量门控插入。详见 `refs/compose-with-converge.md`

---

## 抽象能力层

四个原子能力。所有编排原语构建于其上：

| 能力 | 语义 | 输入 | 输出 |
|------|------|------|------|
| **Spawn** | 启动**全新上下文**的 agent，给自足 prompt | prompt 文本 | instance_id |
| **Wait** | 等待 agent 完成，获取输出 | instance_id（或数组） | agent 输出 |
| **Continue** | 向**已有** agent 发跟进消息，保有上下文 | instance_id + 消息 | agent 回复 |
| **Identify** | 返回当前 agent 实例标识 | — | instance_id |

> 各框架适配见 `refs/framework-adapters.md`。通用降级策略见 A.4。

---

## 核心编排原语

> 以下用**抽象伪代码**描述。完整 API 参考见 `refs/primitives.md`。

| 原语 | 签名 | 语义 | 关键约束 |
|------|------|------|---------|
| **spawn** | `(prompt, opts?) -> output` | 启动全新上下文 agent。prompt 必须自足 | opts: schema/label/model/isolation/agentType（各框架支持度不同，见 framework-adapters.md） |
| **waitAll** | `(thunks) -> results[]` | 并发运行，**屏障**——等待全部完成 | 任何 thunk 失败→null，不阻断其他。滥用让快 agent 空等慢 agent |
| **pipe** | `(items, ...stages) -> results[]` | **流式多阶段**，无屏障。item A stage 2 不等 item B stage 1 | **默认原语**。stage 回调: `(prevResult, originalItem, index)` |
| **group** | `(title)` | 后续 spawn 归入此阶段 | pipe/waitAll 回调内用 opts.group 避免竞态 |
| **report** | `(msg)` | 进度消息 | — |
| **budget guard** | 预算总额/已消耗/剩余 | 硬上限——超限后 spawn 不再执行 | 无上限时视为无限 |

---

## 质量模式目录

> 详细代码骨架见 `refs/patterns.md`（抽象伪代码）。来源：`[official-cc]` / `[community-pattern]` / `[experimental]`。

| 模式 | 做什么 | 来源 |
|------|--------|------|
| **对抗验证** | 每个发现 spawn N 个 skeptics 试图反驳。≥多数反驳则杀死 | `[official-cc]` |
| **多视角验证** | 验证者分配不同透镜（正确性/安全性/性能/可复现性） | `[community-pattern]` |
| **评委团** | N 个独立方案 + 并行评分 → 从最优合成 | `[community-pattern]` |
| **Loop-Until-Dry** | 持续 spawn finder 直到 K 轮无新发现 | `[community-pattern]` |
| **多模态搜索** | 并行 agent 各用不同搜索策略 | `[experimental]` |
| **完整度批评** | 收口前追问"缺了什么？" | `[official-cc]` |
| **无静默截断** | 任何限制必须 report 说明被丢弃的内容 | `[community-pattern]` |

---

## 编排决策指南

> 详细决策树和反模式见 `refs/decision-guide.md`。

**原语选择第一原则：pipe 是默认值。** 无屏障理由就用 pipe。Barrier（waitAll）只在需要跨 item 去重、提前退出、交叉比较时使用。

**规模控制**：容量属于具体 runtime，而不是抽象原语。Claude Code Workflow 为 16 并发 / 单次 1000 agent；Codex 原生 agent 的 `agents.max_threads` 默认 6、可配置；scheduler 的 `--concurrency` 只是 operator 配置的调度上限。当前 `executor.py` 每轮同步执行一个 CLI 调用，实际为串行，不会因 scheduler 上限大于 1 而并行。详见 `refs/decision-guide.md`。

---

## 执行流程

### 使用 scheduler.py（推荐）

非 CC 框架用户通过 `scripts/scheduler.py` 实现代码驱动编排。Orchestrator 退化为 thin executor：

```
while True:
    action = scheduler("dispatch")
    if action == "done": break
    if action == "stop": report(action.reason); break
    if action == "spawn":
        result = spawn(prompt=action.prompt)
        scheduler("complete", item, stage, result)
        if loop_mode:
            new_count = semantic_dedup(result)  # Orchestrator 唯一保留的 LLM 判断
            scheduler("loop-feedback", new_count, context)
    if action == "barrier":
        scheduler("barrier-done")  # 纯 ack，scheduler 内部已完成 barrier 处理
```

scheduler 支持三种模式（`--mode pipe|waitall|loop`），自主判定 barrier 时机、stage 推进和终止条件。详见 `scheduler.py --help`。

### Prompt 模板（可选）

scheduler.py 支持 `--prompt-file` 参数加载 JSON 格式的 prompt 模板。模板支持以下变量：

| 变量 | 说明 | 示例 |
|------|------|------|
| `{{item}}` | 当前 item 名称 | `src/auth/` |
| `{{stage}}` | 当前 stage 名称 | `review` |
| `{{batch_idx}}` | 当前 batch 索引（waitall 模式） | `0` |
| `{{round}}` | 当前轮次（loop 模式） | `1` |
| `{{domain}}` | 领域（config.context.domain） | `security` |
| `{{seen}}` | 已见内容 JSON 数组（loop 模式） | `["item1", "item2"]` |
| `{{context}}` | 完整 context JSON 对象 | `{"domain": "..."}` |

使用示例：

```bash
# 创建模板文件
echo '{"pipe": "审查 {{item}} 的 {{stage}} 阶段"}' > templates.json

# 初始化 workflow 时传入模板
python scripts/scheduler.py init --slug my-workflow --mode pipe \
  --items src/auth/,src/api/ --stages review,verify \
  --prompt-file templates.json
```

### 使用 executor.py（自动化）

非 CC 框架用户通过 `scripts/executor.py` 实现全自动编排。executor.py 读取 scheduler 的 dispatch 结果，自动调用 opencode/codex CLI 执行 agent 任务：

```bash
# 单步执行
executor.py execute-step --slug <slug> --framework opencode

# 全自动循环
executor.py run --slug <slug> --framework opencode
```

executor.py 通过 scheduler.py 的 library API（`get_next_action` / `apply_result`）交互，无需 subprocess 调用。

> `executor.py` 自身当前是**串行执行器**：`run` 循环一次 dispatch 一个 action，等待对应 CLI 完成并写回后才进入下一轮。scheduler 的 `max_concurrency` 可约束其他执行器，但不代表这个实现具备并发能力。
> Codex session resume 仅允许用于单个 `execute-step`；`run` 跨多个 item/stage，禁止传 `--codex-session-id`，以保持每个逻辑 Spawn 的 fresh context。相对 workdir 和 output schema 都以同一个绝对 effective workdir 解析。

### 手动编排（不依赖 scheduler）

1. 解析任务 → 确定编排模式（pipe / waitAll / loop）
2. pipe: item-by-item 推进 stage，无屏障；waitAll: 批量 Spawn + Wait；loop: Spawn → 收集 → 判定
3. 中间结果存 scratch 文件，不进主对话
4. 最终答案写入主对话

---

## Orchestrator 责任清单

1. **prompt 自足性** — 每个 Spawn 的 prompt 包含全部上下文
2. **原语选择** — 默认 pipe，只在满足 barrier 必要条件时用 waitAll
3. **质量模式匹配** — 按任务特征选择对抗验证/评委团/Loop-Until-Dry 等
4. **预算追踪** — 有上限时动态扩缩；耗尽前降级
5. **静默截断声明** — 任何截断必须 report
6. **独立上下文保证** — 对抗验证必须用 fresh context agent
7. **异常处理** — agent 失败不阻断整体（null），但记录并评估影响
8. **完成度自检** — 收口前运行完整度批评

---

## 拆分文件索引

| 需求 | 文件 |
|------|------|
| 抽象原语完整 API 参考 + CC 映射表 | `refs/primitives.md` |
| 参考：CC Workflow API（抽象原语以此为模板） | `refs/cc-workflow-guide.md` |
| 质量模式代码骨架、参数变体 | `refs/patterns.md` |
| 编排决策树、barrier 嗅觉测试、反模式 | `refs/decision-guide.md` |
| 各框架 Spawn/Wait/Continue 能力映射 | `refs/framework-adapters.md` |
| 与 converge SKILL 质量门控组合协议 | `refs/compose-with-converge.md` |
| 编排调度器 CLI（非 CC 框架的执行引擎） | `scripts/scheduler.py` |
| CLI 执行器（自动调用 opencode/codex） | `scripts/executor.py` |
| 框架适配器 | `scripts/adapters/` |

### 运行时目录

`.workflow/` 是 scheduler.py 的运行时状态存储目录，已被 .gitignore 排除：

```
.workflow/
└── <slug>/
    ├── state.json        # workflow 状态（items、stages、budget 等）
    └── logs/             # executor.py 的包装日志（每次调用保存完整 CLI stdout）
        ├── <item>-<stage>.jsonl
        └── ...
```

- `state.json`：scheduler.py 的持久化状态，包含 workflow 配置、item 状态、预算等
- `logs/`：executor.py 每次调用追加一个 `cli_output` 包装事件；该事件的 `output` 字段保存完整原始 stdout。文件并不是逐行展开后的原始 Codex JSONL

---

## 附录 A · 框架适配

> 完整适配指南见 `refs/framework-adapters.md`。以下为摘要映射表。

| 抽象原语 | CC 原生 API | opencode | codex |
|----------|------------|----------|-------|
| spawn | `agent(prompt, opts)` | `task` 工具 | 原生：`multi_agent_v1.spawn_agent`；外部：`codex exec` |
| waitAll | `parallel(thunks)` | 串行降级（task 同步阻塞） | 原生：pending-set 循环调用 `wait_agent`；外部 executor：串行收集 |
| pipe | `pipeline(items, ...stages)` | 串行降级 | manual dispatch loop |
| group | `phase(title)` | 无对应 | 无对应 |
| report | `log(message)` | 主对话输出 | 主对话输出 |
| budget guard | `budget.total/spent()/remaining()` | scheduler.py budget 命令 | scheduler.py budget 命令 |

> ⚠️ **opencode 核心限制**：单个 `task` 工具调用是同步阻塞的——调用后当前 agent 必须等待该 subagent 完成才能继续，无法在执行过程中动态 spawn 新的并行 agent。因此 waitAll/pipe 的**动态并行语义**在 opencode 中降级为串行执行。详见 `refs/framework-adapters.md` A.2。
> 💡 **opencode 并行方案**：虽然单个 task 是阻塞的，但在**同一条消息中同时发起多个 task 调用**时，opencode 会**并行执行**它们。这提供了一种静态批量并行方案：预先确定所有子任务，一次性发出多个 task 调用，全部完成后继续。具体容量和失败语义取决于当前 opencode runtime，应探测或由 operator 配置。详见 `refs/framework-adapters.md` A.2 "waitAll 批量调用"。
> ⚠️ **Codex 两个执行面不可混用**：原生 `multi_agent_v1.spawn_agent` 不支持 schema 等 opts；外部 `codex exec` 支持 `--output-schema`、持久 session/resume、`--ephemeral` 和 sandbox。详见 `refs/framework-adapters.md` A.3。
