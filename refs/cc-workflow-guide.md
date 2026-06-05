# Claude Code Workflow API 速查

> 基于 CC v2.1.x 实测 Workflow 工具定义。随 CC 版本独立更新。
>
> ⚠️ **CC 用户已有原生 Workflow 工具，不需要本 SKILL 来使用它。** 本文档的作用是：记录抽象原语（spawn/waitAll/pipe/...）在 CC 上的参考实现——非 CC 框架的适配器开发者可通过本文档理解抽象原语的设计来源。CC 用户如需编写 workflow 脚本，可直接查阅 Claude Code 官方文档或 Workflow 工具定义。

---

## 触发方式

| 方式 | 语法 | 说明 |
|------|------|------|
| **单次** | prompt 含 `ultracode`（v2.1.160+；旧版用 `workflow`） | 触发单次 workflow 执行 |
| **自然语言** | "use a workflow" | 语义触发 |
| **会话级** | `/effort ultracode` | xhigh 推理 + 自动编排 |
| **关闭** | `disableWorkflows: true` 或 `CLAUDE_CODE_DISABLE_WORKFLOWS=1` | 禁用 workflow |

**v2.1.160 变更**：触发关键词从 `workflow` 改为 `ultracode`。旧版本用户仍可用 `workflow` 或自然语言 "use a workflow" 触发。

---

## 核心 API

### agent(prompt, opts?)

Spawn 一个**全新上下文**的子 agent。子 agent 看不到主对话历史——所有必要信息必须写进 `prompt`。

| 参数 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `prompt` | string | 是 | 自足的 agent 指令 |
| `opts.schema` | object | 否 | JSON Schema。强制结构化输出，验证失败自动重试 |
| `opts.label` | string | 否 | 显示标签（覆盖默认） |
| `opts.phase` | string | 否 | 显式指定所属阶段。pipeline/parallel 回调内建议用此字段避免阶段竞态 |
| `opts.model` | string | 否 | 模型覆盖。通常省略，继承主会话模型 |
| `opts.isolation` | `"worktree"` | 否 | 创建隔离 git worktree。昂贵（~200-500ms），仅当并行写文件会冲突时使用 |
| `opts.agentType` | string | 否 | 自定义 agent 类型，如 `"Explore"` |

**返回值**：
- 有 `schema`：返回验证后的结构化对象
- 无 `schema`：返回 agent 的最终文本
- 用户跳过 agent：返回 `null`

**示例**：
```js
// 无 schema
const text = await agent("总结 src/auth/ 的认证流程")

// 有 schema
const findings = await agent("审查 src/routes/ 的权限检查", {
  schema: {
    type: "object",
    properties: {
      endpoints_checked: { type: "number" },
      findings: { type: "array", items: { type: "object" } }
    },
    required: ["endpoints_checked", "findings"]
  }
})
```

### parallel(thunks) -> 结果数组

**屏障（Barrier）**：并发运行所有 thunk，等待**全部完成**后返回。任一 thunk 抛错解析为 `null`（不阻断其他）。返回数组保持输入顺序。

```js
const [auth, billing, audit] = await parallel([
  () => agent("审查认证模块", { schema: FINDINGS_SCHEMA }),
  () => agent("审查计费模块", { schema: FINDINGS_SCHEMA }),
  () => agent("审查审计模块", { schema: FINDINGS_SCHEMA }),
])
// 三个全部完成后才继续
```

**注意**：所有 thunk 同时启动，受 `max_concurrency`（默认 16）限制。最快的会空等最慢的——只在真正需要全部结果时才用。

### pipeline(items, stage1, stage2, ...) -> 结果数组

**流式多阶段**：每个 item 独立流过所有 stage，**无阶段间屏障**。Item A 在 stage 3 时 item B 可能还在 stage 1。

Stage 回调签名：`(prevResult, originalItem, index) => nextStageResult`

- `prevResult`：上一 stage 的输出
- `originalItem`：原始 item
- `index`：item 在数组中的位置

```js
const results = await pipeline(
  ["src/auth/", "src/billing/", "src/admin/"],
  // Stage 1
  dir => agent(`审查 ${dir} 潜在 bug`, { phase: "审查", schema: BUG_SCHEMA }),
  // Stage 2（审查完一个目录立即开始验证）
  (review, dir, i) => {
    if (!review?.bugs?.length) return { dir, bugs: [], verified: [] }
    return parallel(review.bugs.map(bug => () =>
      agent(`验证 ${dir} ${bug.file}:${bug.line} — 真实 bug？`, {
        phase: "验证", schema: VERDICT_SCHEMA
      })
    )).then(verdicts => ({ dir, bugs: review.bugs, verified: verdicts }))
  }
)
```

### phase(title)

分组标记。后续 `agent()` 调用在进度显示中归入此阶段。

```js
phase("发现")
const bugs = await agent("扫描 bug")
phase("验证")
const verified = await parallel(bugs.map(b => () => agent(`验证: ${b.title}`)))
```

**注意**：在 `pipeline()` / `parallel()` 回调内部，建议用 `opts.phase` 显式指定阶段，避免全局 `phase()` 的竞态条件。

### log(message)

向用户发送进度消息。在进度树上方显示为叙述行。

```js
log(`${findings.length} 个发现，开始逐条验证...`)
```

### budget

Token 预算追踪对象。与 Messages API 的 token budget 共享同一预算池。

| 属性/方法 | 说明 |
|-----------|------|
| `budget.total` | 用户设定的 token 目标。无设定时为 `null` |
| `budget.spent()` | 当前已消耗 token（主循环 + workflow 共享） |
| `budget.remaining()` | `max(0, total - spent())`。无目标时返回 `Infinity` |

**硬上限**：`spent()` 达到 `total` 后，后续 `agent()` 调用直接抛错。

```js
// 预算感知的并发控制
const FLEET = budget.total
  ? Math.floor(budget.total / 100_000)
  : 5

// 预算感知的循环
while (budget.remaining() > 50_000) {
  const result = await agent("继续搜索 bug", { schema: BUG_SCHEMA })
  bugs.push(...result.bugs)
  log(`${bugs.length} 个发现，剩余 ${Math.round(budget.remaining()/1000)}k tokens`)
}
```

### args

脚本入参。用于参数化保存的 workflow。`args` 是全局变量，直接访问属性。

```js
// 调用: workflow({scriptPath}, {targetDir: "src/routes/", severity: "critical"})
const dir = args.targetDir       // "src/routes/"
const sev = args.severity        // "critical"
```

### workflow(nameOrRef, args?) -> 返回值

嵌套另一个 workflow。子 workflow 共享并发上限、abort 信号和 token 预算。

```js
// 调用保存的 workflow
const result = await workflow("deep-research", {
  question: "Node.js v20 vs v22 权限模型变化"
})

// 调用脚本文件
const review = await workflow(
  { scriptPath: ".claude/workflows/code-review.js" },
  { files: changedFiles }
)
```

**限制**：只支持一层嵌套（子 workflow 内不能再调用 workflow）。

---

## 运行时特性

### 生命周期

1. **编写脚本** -> 用户审批（可查看、编辑、或直接批准）
2. **后台执行** -> `/workflows` 实时查看阶段进度
3. **运行时操作**：
   - 暂停/恢复（同会话内，已完成 agent 返回缓存）
   - 停止单个 agent / 整个 workflow
   - 重启运行中的 agent
4. **完成** -> 结果写入主对话
5. **（可选）保存** -> `.claude/workflows/`（项目级）或 `~/.claude/workflows/`（用户级）

### 限额

| 限制 | 值 | 说明 |
|------|-----|------|
| 最大并发 agent | 16 | 受 CPU 核心数限制，超出排队 |
| 单次运行总 agent 上限 | 1000 | 防失控循环 |
| 嵌套层级 | 1 | 子 workflow 内不能再调用 workflow() |
| 中途用户输入 | 不支持 | 阶段间签核需拆为独立 workflow |

---

## 抽象能力映射表

CC 原生 API 到 SKILL.md 抽象原语的映射：

| SKILL.md 抽象原语 | CC 原生 API | 说明 |
|-------------------|-------------|------|
| `spawn(prompt, opts?)` | `agent(prompt, opts?)` | 直接映射 |
| `waitAll(thunks)` | `parallel(thunks)` | 直接映射 |
| `pipe(items, ...stages)` | `pipeline(items, ...stages)` | 直接映射 |
| `group(title)` | `phase(title)` | 直接映射 |
| `report(msg)` | `log(message)` | 直接映射 |
| `trackBudget` / budget guard | `budget.total / spent() / remaining()` | 抽象层用 budget guard 模式，CC 用具体 budget 对象 |
| 嵌套 workflow | `workflow(nameOrRef, args?)` | CC 专属，抽象层无此概念 |
| 脚本入参 | `args` 全局变量 | CC 专属，抽象层用"参数化脚本"概念描述 |
