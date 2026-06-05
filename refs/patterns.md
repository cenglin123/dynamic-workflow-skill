# 质量模式目录 . 代码骨架

> 每种模式包含：意图、结构、参数变体、使用时机、已知局限。
>
> **代码约定**：以下用**抽象伪代码**描述模式结构。原语 `spawn` / `waitAll` / `pipe` / `group` / `report` 的语义见 `SKILL.md` 和 `refs/primitives.md`。Claude Code 用户参考 `refs/cc-workflow-guide.md` 获取原生 API 语法（`agent` / `parallel` / `pipeline` / `phase` / `log`）。
>
> **来源标签**：
> - `[official-cc]` -- Claude Code 官方 Workflow 文档收录
> - `[community-pattern]` -- 社区验证的编排实践
> - `[experimental]` -- 本 SKILL 推导，待更多实证

---

## 1. 对抗验证 (Adversarial Verify) `[official-cc]`

**意图**：防止 plausible-but-wrong 发现通过。每个发现接受 N 个独立 skeptic 的挑战。

**核心假设**：独立审查者（看不到彼此的判断）的多数意见比单一审查者更可信。

### 代码骨架

```
VERDICT_SCHEMA = {
  type: "object",
  properties: {
    claim_id: { type: "string" },
    is_real: { type: "boolean" },
    refuted: { type: "boolean" },
    reasoning: { type: "string" }
  },
  required: ["claim_id", "is_real", "refuted", "reasoning"]
}

function adversarialVerify(claims, skepticCount = 3):
  verified = []
  for claim in claims:
    votes = waitAll(
      repeat(skepticCount, () =>
        spawn(
          `尝试反驳以下发现。如果无法确定其真实性，默认标记 refuted=true。

发现: ${claim.title}
文件: ${claim.file}:${claim.line}
描述: ${claim.description}

**反驳指南**：
- 检查静态分析是否误读了动态行为
- 检查是否有保护措施被忽略
- 检查 claim 是否依赖错误的假设`,
          { schema: VERDICT_SCHEMA, group: "对抗验证" }
        )
      )
    )
    // 存活条件：>= majority 未反驳
    survives = votes.filter(Boolean).filter(v => !v.refuted).length >= 2
    if survives: verified.push(claim)
    else: report(`发现被驳回: ${claim.title}`)
  return verified
```

### 变体

| 变体 | skeptic 数 | 适用 |
|------|-----------|------|
| 快速 | 1 | 低风险发现、初步扫描 |
| 标准 | 3 | 安全审计、代码审查 |
| 严格 | 5 | 关键安全漏洞、合规断言 |

### 局限

- skeptic 共享相同训练数据 -> 可能共享盲点
- 假阳性率低但假阴性率可能高（过度驳回）
- token 成本与 skeptic 数成正比

---

## 2. 多视角验证 (Perspective-Diverse Verify) `[community-pattern]`

**意图**：为每个验证者分配**不同的分析透镜**——当一种失败模式可能以多种方式出现时，单一透镜可能漏掉。

### 代码骨架

```
LENSES = [
  {
    key: "correctness",
    prompt: (finding) => `从**逻辑正确性**角度审查: ${finding.title}。代码是否真的做错了它声称要做的事？`
  },
  {
    key: "security",
    prompt: (finding) => `从**安全性**角度审查: ${finding.title}。是否存在可利用的攻击面？`
  },
  {
    key: "performance",
    prompt: (finding) => `从**性能**角度审查: ${finding.title}。会导致可测量的性能退化吗？`
  },
  {
    key: "reproducibility",
    prompt: (finding) => `从**可复现性**角度审查: ${finding.title}。能在标准环境下稳定触发吗？`
  }
]

function perspectiveDiverseVerify(finding, lenses = LENSES):
  verdicts = waitAll(
    lenses.map(lens => () =>
      spawn(lens.prompt(finding), {
        group: "多视角验证",
        schema: {
          type: "object",
          properties: {
            lens: { type: "string" },
            real: { type: "boolean" },
            severity: { type: "string", enum: ["critical", "high", "medium", "low", "none"] },
            reasoning: { type: "string" }
          },
          required: ["lens", "real", "severity", "reasoning"]
        }
      })
    )
  )
  // >= 2 个透镜确认 -> 接受
  confirmed = verdicts.filter(Boolean).filter(v => v.real).length >= 2
  return { finding, confirmed, verdicts }
```

### 透镜选择指南

| 发现类型 | 推荐透镜 |
|----------|---------|
| 逻辑错误 | correctness + reproducibility |
| 安全漏洞 | security + correctness + reproducibility |
| 性能退化 | performance + reproducibility |
| 边界情况 | correctness + security + performance |

---

## 3. 评委团 (Judge Panel) `[community-pattern]`

**意图**：方案空间大时，从多个角度生成独立方案 -> 评分 -> 从最优合成，嫁接其他方案的优点。

### 代码骨架

```
ANGLES = [
  { key: "mvp_first", prompt: "从最快落地的 MVP 角度设计方案" },
  { key: "risk_first", prompt: "从风险最小化的角度设计方案" },
  { key: "user_first", prompt: "从用户体验最优的角度设计方案" }
]

function judgePanel(problemStatement):
  // Phase 1: 各角度起草
  drafts = waitAll(
    ANGLES.map(a => () =>
      spawn(`问题: ${problemStatement}\n\n${a.prompt}`, {
        group: "起草",
        schema: {
          type: "object",
          properties: {
            angle: { type: "string" },
            plan: { type: "string" },
            pros: { type: "array", items: { type: "string" } },
            cons: { type: "array", items: { type: "string" } }
          },
          required: ["angle", "plan", "pros", "cons"]
        }
      })
    )
  )

  // Phase 2: 并行评分
  scores = waitAll(
    drafts.filter(Boolean).map(d => () =>
      spawn(`从以下维度评分（1-10）这个方案，并给出理由：
方案: ${d.plan}
优点: ${d.pros.join(", ")}
缺点: ${d.cons.join(", ")}

评分维度: 可行性、完整性、风险、可维护性、实施速度`, {
        group: "评分",
        schema: {
          type: "object",
          properties: {
            feasibility: { type: "number" },
            completeness: { type: "number" },
            risk: { type: "number" },
            maintainability: { type: "number" },
            speed: { type: "number" },
            overall: { type: "number" },
            rationale: { type: "string" }
          },
          required: ["overall", "rationale"]
        }
      })
    )
  )

  // Phase 3: 合成 -- 从最高分方案出发，嫁接其他方案的优点
  ranked = drafts
    .map((d, i) => ({ ...d, score: scores[i]?.overall ?? 0 }))
    .sort((a, b) => b.score - a.score)

  winner = ranked[0]
  grafts = ranked.slice(1).flatMap(d => d.pros)

  synthesis = spawn(
    `以以下方案为基础，嫁接其他方案的优点：

基础方案 (${winner.angle}, 得分 ${winner.score}):
${winner.plan}

可嫁接的优点:
${grafts.map((p, i) => `${i+1}. ${p}`).join("\n")}

请输出融合后的最终方案。`, {
    group: "合成",
    schema: {
      type: "object",
      properties: {
        final_plan: { type: "string" },
        basis: { type: "string" },
        grafts_applied: { type: "array", items: { type: "string" } },
        grafts_rejected: { type: "array", items: { type: "string" } }
      },
      required: ["final_plan", "basis"]
    }
  })

  return { synthesis, ranked }
```

---

## 4. Loop-Until-Dry `[community-pattern]`

**意图**：未知规模的发现任务——持续 spawn finder 直到 K 轮连续无新发现。

**关键**：维护 `seen` set 去重（不仅 tracking `confirmed`——否则 judge 拒绝的发现每轮重复出现）。

### 代码骨架

```
function loopUntilDry(finderPrompt, { dryThreshold = 2, maxRounds = 20 } = {}):
  seen = Set()
  confirmed = []
  dry = 0
  round = 0

  while dry < dryThreshold and round < maxRounds:
    round += 1
    result = spawn(
      `${finderPrompt}\n\n已发现（不要重复）:\n${[...seen].join("\n")}`,
      { schema: BUG_SCHEMA, group: "发现" }
    )

    if !result?.bugs?.length:
      dry += 1
      report(`第 ${round} 轮：无新发现 (dry=${dry}/${dryThreshold})`)
      continue

    fresh = result.bugs.filter(b => !seen.has(key(b)))
    if !fresh.length:
      dry += 1
      continue

    dry = 0
    fresh.forEach(b => seen.add(key(b)))

    // 对抗验证每批新发现
    judged = waitAll(
      fresh.map(b => () =>
        waitAll(repeat(3, () =>
          spawn(`反驳: ${b.desc}`, { schema: VERDICT_SCHEMA })
        )).then(vs => ({
          bug: b,
          real: vs.filter(Boolean).filter(v => !v.refuted).length >= 2
        }))
      )
    )

    confirmed.extend(judged.filter(Boolean).filter(j => j.real).map(j => j.bug))
    report(`第 ${round} 轮：${fresh.length} 新发现，${confirmed.length} 累计确认`)

  return confirmed

function key(bug): return `${bug.file}:${bug.line}:${bug.checker}`
```

### 参数调优

| 场景 | dryThreshold | 说明 |
|------|-------------|------|
| 快速扫描 | 1 | 一轮无新发现即停 |
| 标准审计 | 2 | 平衡完整度与成本 |
| 穷举审计 | 3 | 大型 codebase 安全审计 |

---

## 5. 多模态搜索 (Multi-Modal Sweep) `[experimental]`

**意图**：不同搜索策略覆盖不同发现面——并行 agent 各用一种策略，互补而非重叠。

### 代码骨架

```
MODALITIES = [
  {
    key: "by_module",
    prompt: (scope) => `按模块/容器结构分析 ${scope} -- 遍历每个顶层目录，审查其职责边界`
  },
  {
    key: "by_data_flow",
    prompt: (scope) => `按数据流分析 ${scope} -- 追踪关键数据从入口到持久化的路径`
  },
  {
    key: "by_entity",
    prompt: (scope) => `按实体分析 ${scope} -- 识别核心业务实体（User, Order, etc.）并检查其生命周期处理`
  },
  {
    key: "by_time",
    prompt: (scope) => `按时间线分析 ${scope} -- 关注异步操作、定时任务、事件序列中的顺序依赖`
  }
]

function multiModalSweep(scope):
  allFindings = waitAll(
    MODALITIES.map(m => () =>
      spawn(m.prompt(scope), {
        group: `搜索:${m.key}`,
        schema: FINDINGS_SCHEMA
      })
    )
  )
  // 去重后返回
  return dedupeByFileAndLine(allFindings.filter(Boolean).flatMap(r => r.findings))
```

---

## 6. 完整度批评 (Completeness Critic) `[official-cc]`

**意图**：收口前最后检查——一个 agent 专门追问 "缺了什么？"

### 代码骨架

```
function completenessCritic(taskSummary, findings, methodology):
  return spawn(
    `你是一个完整度批评者。审查以下审计/研究的结果，回答"缺了什么？"

## 任务
${taskSummary}

## 已执行的方法
${methodology}

## 已有发现
${findings.map((f, i) => `${i+1}. ${f.title} [${f.severity}]`).join("\n")}

## 批评维度
1. **遗漏的模态**：是否有搜索策略/分析角度未使用？
2. **未验证的发现**：是否有发现未经对抗验证？
3. **未读的源**：是否有相关文件/文档/子系统未被检查？
4. **边界条件**：是否遗漏了边缘情况（空输入、大文件、极值）？
5. **交互效应**：是否考虑了发现之间的组合风险？

输出你找到的所有遗漏，按严重程度分级。`, {
    group: "完整度批评",
    schema: {
      type: "object",
      properties: {
        gaps: {
          type: "array",
          items: {
            type: "object",
            properties: {
              category: { type: "string" },
              description: { type: "string" },
              severity: { type: "string", enum: ["critical", "high", "medium", "low"] },
              suggestion: { type: "string" }
            },
            required: ["category", "description", "severity"]
          }
        }
      },
      required: ["gaps"]
    }
  })
```

---

## 7. 无静默截断 (No Silent Caps) `[community-pattern]`

**不是独立模式，而是所有其他模式的约束**：任何截断必须显式声明。

```
// 坏：截断不声明
results = waitAll(items.slice(0, 20).map(...))

// 好：截断并声明
SAMPLE_SIZE = 20
if items.length > SAMPLE_SIZE:
  report(`截断：${items.length} 个 items 中只处理前 ${SAMPLE_SIZE} 个。跳过: ${items.slice(SAMPLE_SIZE).map(i => i.name).join(", ")}`)
results = waitAll(items.slice(0, SAMPLE_SIZE).map(...))
```

**所有应声明的情况**：
- Top-N 截断
- 抽样
- 跳过（因预算/时间/权限）
- 降级（L2->L1、对抗验证 skeptic 数缩减）
- 提前退出（loop-until-dry 之外的原因）
