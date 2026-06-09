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

> 各框架适配见 `refs/framework-adapters.md`。通用降级策略见 `refs/framework-adapters.md` A.4。

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

### 质量门控检查清单

> **责任声明**：质量门控是**编排者的强制责任**，不是框架自动执行的功能。编排者必须在每个 stage 完成后主动执行以下检查。未执行门控等同于跳过质量保证，后果由编排者承担。

**run_quality_gate vs post_injection_verify 职责划分**：

| 函数 | 调用时机 | 检查范围 | 关注点 |
|------|----------|----------|--------|
| `run_quality_gate` | 子代理完成**后**，写入最终答案**前** | 文件存在性、非空、forbidden_patterns、内容质量 | **产出物本身**是否完整、合规 |
| `post_injection_verify` | 子代理返回**后**，门控检查**前** | evidence_template 完整性、phantom file、工具合规、术语合规 | **约束是否被遵守**（注入后验证闭环） |

**调用顺序**：`spawn → post_injection_verify → run_quality_gate → 接受/拒绝`

> `run_quality_gate` 脚本模板见 `refs/quality-gate-templates.md`。`post_injection_verify` 脚本模板见 `refs/constraint-injection.md`。

**门控 1：完整性检查（确定性验证）**

编排者必须通过**文件系统级验证**确认子代理实际完成了任务，而非依赖子代理的自我报告。

| 检查项 | 验证方法 | 判定标准 |
|--------|----------|----------|
| 文件存在性 | `os.path.exists(path)` 或 `Test-Path -LiteralPath $path` | 所有预期文件存在 |
| 文件非空 | `os.path.getsize(path) > 0` 或 `(Get-Item $path).Length -gt 0` | 文件大小 > 0 字节 |
| 文件内容 hash | `hashlib.sha256(open(path,'rb').read()).hexdigest()` | 与预期 hash 一致（可选） |
| 输出格式完整 | 子代理返回结构化 evidence（见 evidence_template） | evidence 字段齐全 |

> **为什么需要确定性验证**：子代理的自我报告不可信。Shannon 案例中 Batch 3 子代理报告"10/10 成功"，但实际 0 个文件存在于目标目录。只有文件系统级检查才能发现此类"虚假成功"。

**门控 2：一致性检查**
- [ ] 输出符合设计契约的 constraints
- [ ] 无 forbidden_tools 使用记录
- [ ] 无 forbidden_patterns 匹配的文件创建
- [ ] 无 anti_patterns 中列出的模式
- [ ] mandatory_terms 中的术语使用正确

**门控 3：质量检查**
- [ ] 输出格式正确（无语法错误、无格式破坏）
- [ ] 特殊元素保留完整（公式、标题、注释）
- [ ] 无合并错误（如 `exampleadding`、`encodedand`）

**门控动作**：
- 全部通过 → 接受结果
- 门控 1 失败 → 重新委派（同 prompt）
- 门控 2 失败 → 升级 prompt 后重新委派（见失败回退策略）
- 门控 3 失败 → 标记为 NEEDS_REVIEW，人工处理

> **门控脚本模板**：`run_quality_gate` 完整 Python 脚本（含文件存在性、forbidden_patterns、内容抽样三项检查）和内置检查项示例见 `refs/quality-gate-templates.md`。

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

### 设计契约（Design Contract）

在 spawn 子代理时，通过 prompt 注入设计契约，约束子代理的行为。设计契约是编排者传递给子代理的**不可变约束集合**。

```json
{
  "design_contract": {
    "objective": "任务目标",
    "constraints": ["约束1", "约束2"],
    "allowed_tools": ["Edit", "Read"],
    "forbidden_tools": ["Bash"],
    "forbidden_patterns": ["\\.py$", "\\.ps1$"],
    "anti_patterns": ["反模式1", "反模式2"],
    "execution_path": "推荐的执行路径",
    "mandatory_terms": {
      "术语原文": "标准译法",
      "DeepSeek V3": "DeepSeek V3（Pro 版本为 V4）"
    },
    "term_verification": "对于不确定的术语，保留原文并标记 [UNCERTAIN]",
    "evidence_template": {
      "files_written": ["path/to/file1", "path/to/file2"],
      "files_modified": ["path/to/file3"],
      "file_sizes": {"path/to/file1": 1234},
      "verification_commands": ["Test-Path -LiteralPath 'path/to/file1'"],
      "uncertainty_markers": ["line 42: [UNCERTAIN] 术语不确定"]
    }
  }
}
```

**字段说明**：
- `objective`：任务目标，子代理必须完成的核心任务
- `constraints`：不可偏离的约束列表
- `allowed_tools`：允许使用的工具列表（白名单）
- `forbidden_tools`：禁止使用的工具列表（黑名单）
- `forbidden_patterns`：禁止创建的文件模式（正则表达式）
- `anti_patterns`：需要避免的反模式
- `execution_path`：推荐的执行路径
- `mandatory_terms`：术语对照表。子代理必须使用表中的标准写法，禁止自行推断
- `term_verification`：术语不确定时的处理策略
- `evidence_template`：子代理返回结果的结构化格式。编排者通过此字段要求子代理提供确定性执行证据，而非自由文本描述

**Shannon 案例示例**：

```json
{
  "design_contract": {
    "objective": "修复段落中的异常换行",
    "constraints": [
      "使用 Edit 工具逐行修复",
      "禁止编写任何脚本（Python/PowerShell/Bash）",
      "保留特殊格式元素（公式、标题、注释）",
      "遇到不确定时读取更多上下文，不要猜测"
    ],
    "allowed_tools": ["Read", "Edit"],
    "forbidden_tools": ["Bash"],
    "forbidden_patterns": ["\\.py$", "\\.ps1$", "\\.sh$"],
    "anti_patterns": ["脚本试错循环", "格式破坏"],
    "execution_path": "读取目标行 → 判断语义 → 使用 Edit 工具修改 → 验证",
    "mandatory_terms": {
      "DeepSeek": "DeepSeek（不是 迪布西克）",
      "Claude": "Claude（Anthropic 公司）",
      "Vibe Coding": "Vibe Coding（不是 Web Coding）"
    },
    "term_verification": "对于不确定的术语，保留原文并标记 [UNCERTAIN]",
    "evidence_template": {
      "files_written": ["output/chunk1_corrected.md"],
      "files_modified": ["output/chunk1.md"],
      "file_sizes": {"output/chunk1_corrected.md": 4567},
      "verification_commands": ["Test-Path -LiteralPath 'output/chunk1_corrected.md'"],
      "uncertainty_markers": []
    }
  }
}
```

### 子代理约束注入（摘要）

> 设计契约是**唯一的约束定义源**，约束传递协议和残差约束是其注入方式。约束注入是 prompt 级的，编排者必须通过注入后验证闭环弥补能力边界。

**核心要点**：
- **三层结构**：设计契约（定义层）→ 注入协议（传递层）→ 子代理 prompt（接收层）
- **注入协议字段**：`design_constraints`（不可变约束）、`context_brief`（精简上下文）、`residual_constraints`（残差约束，每步携带）、`propagation_rules`（继承规则）
- **能力边界**：prompt 注入无法物理阻止子代理违反约束，编排者必须在子代理返回后执行 `post_injection_verify`

> 完整协议、注入模板、Shannon 案例示例、`post_injection_verify` 脚本和能力边界表见 `refs/constraint-injection.md`。

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

### 手动编排（摘要）

手动编排是合法路径，适用于 opencode 框架或不想依赖 scheduler.py 的场景。

**四步法**：解析任务确定模式 → 执行原语（pipe/waitAll/loop）→ 中间结果存 scratch 文件 → 最终答案写入主对话。

> 完整 opencode 框架示例（Shannon 案例 waitAll 流程、设计契约注入、门控脚本、关键约束表）见 `refs/manual-orchestration.md`。

---

## Orchestrator 责任清单

1. **prompt 自足性** — 每个 Spawn 的 prompt 包含全部上下文
2. **原语选择** — 默认 pipe，只在满足 barrier 必要条件时用 waitAll
3. **质量模式匹配** — 按任务特征选择对抗验证/评委团/Loop-Until-Dry 等
4. **预算追踪** — 有上限时动态扩缩；耗尽前降级
5. **静默截断声明** — 任何截断必须 report
6. **独立上下文保证** — 对抗验证必须用 fresh context agent
7. **异常处理** — agent 失败不阻断整体（null），但记录并评估影响

### 失败回退策略

当子代理执行失败或偏离约束时，按以下策略处理：

**偏离检测机制**：
- 门控 2 失败（一致性检查）→ 判定为"偏离约束"
- 门控 1 失败（完整性检查）→ 判定为"执行失败"

**升级 Prompt 策略**（L1-L4 四级递进）：

| 等级 | 触发条件 | 升级动作 |
|------|----------|----------|
| L1 | 首次偏离 | 在 prompt 中增加 "IMPORTANT:" 前缀，强化约束描述 |
| L2 | L1 后再次偏离 | 缩减 allowed_tools 列表，移除非必要工具 |
| L3 | L2 后再次偏离 | 增加 forbidden_patterns，禁止更多文件类型 |
| L4 | L3 后再次偏离 | 最小化 prompt，仅保留核心约束和任务描述 |

**Shannon 案例升级 Prompt 示例**：

**L1（首次偏离）**：
```
IMPORTANT: 你必须使用 Edit 工具逐行修复，禁止编写任何脚本。
如果 Edit 工具失败，读取更多上下文后再尝试，不要切换到其他方案。
```

**L2（L1 后再次偏离）**：
```
CRITICAL: 你只能使用 Read 和 Edit 工具。Bash 工具已被禁用。
如果 Edit 工具连续失败 2 次，标记该行为 NEEDS_REVIEW 并继续下一行。
```

**L3（L2 后再次偏离）**：
```
STOP: 你被禁止创建任何文件。只允许修改现有文件。
如果不确定如何修复，标记为 NEEDS_REVIEW，不要猜测。
```

**L4（L3 后再次偏离）**：
```
任务：修复段落换行。
工具：Edit only。
禁止：脚本、Bash、创建文件。
失败处理：标记 NEEDS_REVIEW。
```

**最大重试次数**：同一天内最多升级 4 次（L1→L2→L3→L4），超过后标记为不可恢复，report 失败原因。

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
| 门控脚本模板（run_quality_gate + 内置检查项） | `refs/quality-gate-templates.md` |
| 约束注入协议（三层结构 + post_injection_verify） | `refs/constraint-injection.md` |
| 手动编排示例（四步法 + Shannon 案例） | `refs/manual-orchestration.md` |
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
