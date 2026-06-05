---
name: dynamic-workflow
description: Use when orchestrating multiple subagents at scale in frameworks WITHOUT native workflow runtime (opencode, codex, etc.). NOT for simple subagent delegation — use your framework's native subagent tools for smaller tasks.
---

# Dynamic Workflow — 多智能体规模化编排

> 把编排计划写进代码，而非留在对话上下文。脚本持有循环、分支和中间结果，主对话只保留最终答案。
>
> **面向非 CC 框架**：如果你使用的 agent 框架（opencode、codex 等）没有原生多 agent 编排能力，本 SKILL 提供一套框架无关的编排模式 + CLI 调度器（`scripts/scheduler.py`）。CC 用户已有原生 Workflow 工具，无需本 SKILL。

---

## Positioning

**目标受众**：没有原生 workflow runtime 的 agent 框架（opencode、codex 等）。

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

**规模控制**：单次最多 16 并发、1000 agent 总量。详见 `refs/decision-guide.md`。

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

### 使用 executor.py（自动化）

非 CC 框架用户通过 `scripts/executor.py` 实现全自动编排。executor.py 读取 scheduler 的 dispatch 结果，自动调用 opencode/codex CLI 执行 agent 任务：

```bash
# 单步执行
executor.py execute-step --slug <slug> --framework opencode

# 全自动循环
executor.py run --slug <slug> --framework opencode
```

executor.py 通过 scheduler.py 的 library API（`get_next_action` / `apply_result`）交互，无需 subprocess 调用。

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

---

## 附录 A · 框架适配

> 完整适配指南见 `refs/framework-adapters.md`。以下为摘要映射表。

| 抽象原语 | CC 原生 API | opencode | codex |
|----------|------------|----------|-------|
| spawn | `agent(prompt, opts)` | `task` 工具 | `multi_agent_v1.spawn_agent` |
| waitAll | `parallel(thunks)` | 串行降级（task 同步阻塞） | `wait_agent` |
| pipe | `pipeline(items, ...stages)` | 串行降级 | manual dispatch loop |
| group | `phase(title)` | 无对应 | 无对应 |
| report | `log(message)` | 主对话输出 | 主对话输出 |
| budget guard | `budget.total/spent()/remaining()` | scheduler.py budget 命令 | scheduler.py budget 命令 |

> ⚠️ **opencode 核心限制**：`task` 工具是同步阻塞的——无法真正并行 spawn。waitAll/pipe 的并行语义降级为串行执行。详见 `refs/framework-adapters.md` A.2。
> ⚠️ **codex 核心限制**：`spawn_agent` 不支持 `schema`/`label`/`model`/`isolation`/`agentType` opts。schema 验证需在 prompt 中描述 + Orchestrator 手动解析。详见 `refs/framework-adapters.md` A.3。
