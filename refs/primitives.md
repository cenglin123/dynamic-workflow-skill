# 编排原语参考

> 本文档包含两部分：
> - **第一部分**：抽象原语参考（框架无关，用伪代码描述语义）
> - **第二部分**：Claude Code 原生 API 映射（CC 用户 -> `refs/cc-workflow-guide.md` 获取完整原生 API 参考）

---

## Part 1 · 抽象原语

### spawn(prompt, opts?) -> 输出

Spawn 一个**全新上下文**的子 agent。子 agent 看不到主对话历史——所有必要信息必须写进 `prompt`。

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `prompt` | string | 是 | 自足的 agent 指令。包含任务描述、输入数据、输出格式要求 |
| `opts.schema` | object | 否 | 输出结构约束。要求 agent 按指定格式输出。**仅 CC 支持框架层验证和自动重试**；opencode/codex 需在 prompt 中描述格式 + Orchestrator 手动解析校验（见 framework-adapters.md） |
| `opts.label` | string | 否 | 显示标签（覆盖默认的任务描述标签） |
| `opts.model` | string | 否 | 模型选择。**通常省略**——agent 继承主会话模型 |
| `opts.isolation` | string | 否 | 隔离模式。如 `"workspace"` 创建独立工作空间，仅在并行写文件冲突时使用（有磁盘开销） |
| `opts.agentType` | string | 否 | agent 类型标记。如 `"Explore"` 用于只读搜索 |

**返回值**：
- 有 `schema`（CC）：返回验证后的结构化对象（无需手动 parse）
- 无 `schema`：返回 agent 的最终文本
- 非 CC 框架：schema 行为取决于框架支持，见 `framework-adapters.md`
- agent 被跳过：返回 `null`（用 `.filter(Boolean)` 过滤）

**示例**（伪代码）：
```
// 无 schema -- 返回文本
summary = spawn("总结 src/auth/ 目录的认证流程")

// 有 schema -- 返回结构化对象
findings = spawn(
  "审查 src/routes/ 下所有 API 端点，查找缺失的权限检查",
  { schema: {
      type: "object",
      properties: {
        endpoints_checked: { type: "number" },
        findings: {
          type: "array",
          items: {
            type: "object",
            properties: {
              file: { type: "string" },
              line: { type: "number" },
              issue: { type: "string" },
              severity: { type: "string", enum: ["critical", "high", "medium", "low"] }
            },
            required: ["file", "line", "issue", "severity"]
          }
        }
      },
      required: ["endpoints_checked", "findings"]
    }
  }
)
// findings = { endpoints_checked: 42, findings: [...] }  <- 已验证的类型安全对象
```

---

### waitAll(thunks) -> 结果数组

**屏障**：并发运行所有 thunk，**等待全部完成**后返回结果数组。

**行为**：
- 所有 thunk 同时启动（受 `max_concurrency` 限制）
- 任一个 thunk 抛错解析为 `null`，不阻断其他 thunk
- 返回数组保持输入顺序

**示例**（伪代码）：
```
[auth, billing, audit] = waitAll([
  () => spawn("审查认证模块", { schema: FINDINGS_SCHEMA }),
  () => spawn("审查计费模块", { schema: FINDINGS_SCHEMA }),
  () => spawn("审查审计模块", { schema: FINDINGS_SCHEMA }),
])
// 三个全部完成后才到这一步
```

**屏障代价**：如果最快 agent 需 10s、最慢需 30s，waitAll 耗时 = 30s（最快的空等 20s）。**只在真正需要全部结果时才用。**

---

### pipe(items, ...stages) -> 结果数组

**流式多阶段**：每个 item 独立流过所有 stage，**无阶段间屏障**。

**行为**：
- Item A 的 stage 2 在 A 的 stage 1 完成后立即启动，不等 B/C 完成 stage 1
- 墙钟时间 = 最慢 single-item chain（而非 sum-of-slowest-per-stage）
- Stage 抛错将该 item 置为 `null`，跳过其剩余 stage

**Stage 回调签名**（伪代码）：
```
(prevResult, originalItem, index) => nextStageResult
```
- `prevResult`：上一 stage 的输出
- `originalItem`：原始 item（用于在后续 stage 标注，无需线程化上下文）
- `index`：item 在数组中的位置

**示例**（伪代码）：
```
results = pipe(
  ["src/auth/", "src/billing/", "src/admin/"],  // items
  // Stage 1: 审查
  dir => spawn(`审查 ${dir} 下所有文件的潜在 bug`, {
    group: "审查",
    schema: BUG_SCHEMA
  }),
  // Stage 2: 验证（审查完一个目录立即开始验证，不等其他目录）
  (review, dir, i) => {
    if (!review?.bugs?.length) return { dir, bugs: [], verified: [] }
    return waitAll(review.bugs.map(bug => () =>
      spawn(`验证 ${dir} 中 ${bug.file}:${bug.line} 的 "${bug.desc}" -- 真实 bug 还是假阳性？`, {
        group: "验证",
        schema: VERDICT_SCHEMA
      })
    )).then(verdicts => ({ dir, bugs: review.bugs, verified: verdicts }))
  }
)
// auth 的验证可能和 billing 的审查同时进行
```

---

### group(title)

分组标记。后续 `spawn()` 调用在进度显示中归入此阶段。

```
group("发现")
bugs = spawn("扫描 bug")
group("验证")
verified = waitAll(bugs.map(b => () => spawn(`验证: ${b.title}`)))
```

**在 pipe/waitAll 回调内部**：用 `opts.group` 显式指定阶段，避免全局 `group()` 的竞态条件。

---

### report(message)

向用户发送进度消息。在进度树上方显示为叙述行。

```
report(`${findings.length} 个发现，开始逐条验证...`)
```

---

### budget guard（预算感知）

Token / 调用次数预算追踪。通过预算守卫模式在编排逻辑中动态调整：

| 概念 | 说明 |
|------|------|
| 预算总额 | 用户或系统设定的资源上限。无设定时视为无限制 |
| 已消耗 | 当前已使用的资源量 |
| 剩余 | `max(0, 总额 - 已消耗)`。无上限时视为无限 |

**硬上限**：已消耗达到总额后，后续 `spawn()` 调用不再执行。

**预算感知的扩缩**（伪代码）：
```
// 每 100k token 预算分配一个并发
FLEET = budget.total
  ? floor(budget.total / 100_000)
  : 5

// 动态循环，在预算内持续搜索
while (budget.total && budget.remaining > 50_000) {
  result = spawn("继续搜索 bug", { schema: BUG_SCHEMA })
  bugs.extend(result.bugs)
  report(`${bugs.length} 个发现，剩余 ${round(budget.remaining/1000)}k tokens`)
}
```

---

### 参数化脚本

脚本入参。用于参数化保存的 workflow。

```
// workflow 被调用时传入:
// { targetDir: "src/api/", minSeverity: "high" }

targetDir = args.targetDir         // "src/api/"
minSeverity = args.minSeverity     // "high"

results = spawn(
  `审查 ${targetDir} 目录，只报告 ${minSeverity} 及以上级别的发现`,
  { schema: FINDINGS_SCHEMA }
)
```

---

## Part 2 · Claude Code 原生 API 映射

> **CC 用户**：完整原生 API 参考见 `refs/cc-workflow-guide.md`。以下为抽象原语与 CC 原生 API 的快速映射表。

### 映射表

| 抽象原语 | CC 原生 API | 说明 |
|----------|------------|------|
| `spawn(prompt, opts?)` | `agent(prompt, opts?)` | CC 的 opts 支持 `schema`、`label`、`phase`、`model`、`isolation: "worktree"`、`agentType` |
| `waitAll(thunks)` | `parallel(thunks)` | 屏障语义，全部完成后返回 |
| `pipe(items, ...stages)` | `pipeline(items, ...stages)` | Stage 回调签名 `(prevResult, originalItem, index)` |
| `group(title)` | `phase(title)` | 后续 agent 在进度显示中归入此阶段 |
| `report(msg)` | `log(message)` | 进度树上方显示叙述行 |
| `budget guard` | `budget.total` / `budget.spent()` / `budget.remaining()` | 硬上限，超限后 `agent()` 抛错 |
| 参数化脚本 | `args` 全局变量 | JSON 值，直接访问属性 |
| 嵌套 workflow | `workflow(nameOrRef, args?)` | **CC 专属**。限一层嵌套。抽象层无对应概念 |

### 触发方式

- **v2.1.160+**：prompt 含 `ultracode` 关键词，或自然语言 "use a workflow"
- **旧版本**：prompt 含 `workflow` 关键词
- **会话级**：`/effort ultracode`

### CC runtime 特性

- 脚本执行前需用户审批
- 运行时支持暂停/恢复/停止/重启
- 最多 16 并发、单次 1000 agent 总量
- 无中途用户输入（阶段间签核需拆为独立 workflow）

> 完整详情（含生命周期、保存复用、嵌套限制）见 `refs/cc-workflow-guide.md`。
