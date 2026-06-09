# 与 Converge 的组合协议

> Dynamic Workflow = 执行层（规模化并行）；Converge = 判断层（多轮迭代收敛）。
> 两者互补：workflow 缺少中途判断和迭代收敛，converge 缺少规模化并行。组合使用补全彼此。
>
> **代码约定**：以下用**抽象伪代码**描述。原语 `spawn` / `waitAll` / `pipe` / `group` / `report` 的语义见 `SKILL.md` 和 `refs/primitives.md`。Claude Code 用户参考 `refs/cc-workflow-guide.md` 获取原生 API 语法。

---

## 定位：执行层 + 判断层

```
Dynamic Workflow 执行层
  |-- Phase 1: 理解/发现
  |-- Phase 2: 生成/修改
  |-- Phase 3: 验证/测试
  |-- Phase N: 整合
        |
        |-- [质量门控 L1] <- 零 token 成本信号检测
        |-- [质量门控 L2] <- 单轮对抗审查（按需）
        |-- [完整 Converge] <- 多轮收敛（critical_gap 时）
```

**核心原则**：workflow 负责"把事做完"，converge 负责"确保做得对"。

---

## 两级门控参考

Converge SKILL 定义了两级门控（详见 converge `refs/quality-gate.md`），可直接插入 workflow 的 group 交接处：

### L1 轻量级（零 LLM 成本）

独立 Python 脚本，接收 DW 提供的指标 JSON，输出 `pass` / `warn`。

**输入**（DW 在 group 收口时传入）：
```json
{
  "phase": "phase-2",
  "worker_consistency": { "overlap_ratio": 0.72 },
  "test_pass_rate": { "current": 0.94, "previous": 0.97 },
  "token_budget": { "phase_spent": 120000, "phase_expected": 100000 },
  "file_existence": {
    "expected_files": ["01.srt", "02.srt"],
    "actual_files": {"01.srt": {"size_bytes": 1234}, "02.srt": {"size_bytes": 0}},
    "file_timestamp_span_seconds": 0.2
  }
}
```

**阈值**（pilot，待校准）：

| 信号 | 阈值 | 标签 |
|------|------|------|
| Worker 分类重叠率 | < 0.6 | `worker_divergence` |
| 测试通过率下降 | >= 20% vs 上一阶段 | `test_decline` |
| Token 超出预算 | 超出预期 30% | `budget_overrun` |
| 文件存在性验证 | 期望产物缺失或 0 字节 | `file_existence_mismatch` |

> `file_existence` 字段需 DW 侧在 phase 收口时扫描产物目录并传入。若 DW 侧暂不支持（如纯 API pipeline 无文件系统），l1_gate.py 在字段缺失时静默跳过。`file_timestamp_span_seconds` 为可选补充字段，不独立触发 warn。

### L2 重量级（单轮对抗审查，按需）

L1 输出 `warn` 后触发。Spawn 独立 Reviewer 做一轮深度审查。

**输出**：`gate_findings`（非 blocking_issues）：
```yaml
gate_findings:
  - severity: critical_gap  # info | risk | critical_gap
    finding: "<具体风险/遗漏/矛盾>"
    evidence: "<引用 phase 产物>"
    suggestion: "<处理方向>"
```

**Orchestrator 处置路径**：
- `info` -> 记录，不阻断
- `risk` -> 记录 + 报警 + 调减后续 group 预算
- `critical_gap` -> **触发完整 converge**（Round 0 合同谈判 + 多轮收敛）

---

## DW 脚本中的门控集成

```
// === 质量门控配置 ===
GATE_CONFIG = {
  l1_interval: 1,           // 每 N 个 group 触发 L1
  l2_mode: "signal",        // always | signal | off
  max_token_share: 0.15,    // 门控预算占比
}

GATE_BUDGET = budget.total
  ? budget.total * GATE_CONFIG.max_token_share
  : Infinity

function qualityGate(phaseName, metrics):
  // L1: 信号检测（零 LLM 成本）
  l1Result = runL1Script(metrics)
  report(`门控 L1 [${phaseName}]: ${l1Result}`)

  if l1Result == "pass": return { passed: true, level: "L1" }

  // L2: 按需单轮审查
  if GATE_CONFIG.l2_mode == "off":
    report(`门控 L1 warn，但 L2 已关闭`)
    return { passed: true, level: "L1", warning: l1Result }

  if budget.remaining < GATE_BUDGET * 0.3:
    report(`门控预算不足 (剩余 ${round(budget.remaining/1000)}k)，跳过 L2`)
    return { passed: true, level: "L1", warning: l1Result, l2_skipped: "budget" }

  findings = spawn(
    `独立审查阶段 ${phaseName} 的产物。关注方向性风险、遗漏假设、矛盾信号。
审查对象: ${metrics.phase_summary}`, {
    group: "质量门控",
    schema: GATE_FINDINGS_SCHEMA
  })

  // 按 severity 处置
  for f in findings.gate_findings:
    if f.severity == "critical_gap":
      report(`关键缺口: ${f.finding}`)
      // -> 触发完整 converge（后续 group 插入收敛循环）
    else if f.severity == "risk":
      report(`风险: ${f.finding}`)

  return { passed: true, level: "L2", findings }

// === 主 pipe 中插入门控 ===
group("审查")
reviewResults = waitAll(REVIEW_TASKS.map(t => () => spawn(t.prompt, { schema: FINDINGS_SCHEMA })))

// Group 交接点 -> 门控
gateResult = qualityGate("审查", {
  phase_summary: summarizePhase(reviewResults),
  worker_consistency: calcConsistency(reviewResults),
  test_pass_rate: getTestMetrics(),
  token_budget: { phase_spent: phaseTokenCount, phase_expected: expectedPhaseTokens },
  file_existence: scanOutputDir(expectedFiles, outputDir)  // 新增：文件存在性扫描
})

if gateResult.findings?.some(f => f.severity == "critical_gap"):
  // 插入 converge 循环（Spawn Reviewer -> Executor -> 多轮迭代）
  report("触发完整 converge 审查...")
  // converge 循环由 converge SKILL 的 Orchestrator 管理

group("修复")
// continue to next phase...
```

---

## 预算统筹

```
门控预算池 = 总预算 * gate_max_token_share（默认 15%）
门控消耗不计入主 workflow 的 agent 配额
```

---

## 什么场景下用哪种组合

| 场景 | 组合 | 说明 |
|------|------|------|
| 大型 codebase 迁移 | DW pipe + converge L1 每 group | 规模由 DW 覆盖，质量由 L1 信号检测 |
| 安全审计 | DW multi-modal sweep + converge L2 按需 | 发现由 DW 多模态覆盖，关键发现触发 L2 单轮审查 |
| 关键基础设施变更 | DW + 完整 converge（Round 0-1+） | 高风险场景，需要完整收敛循环 |
| 快速功能开发 | DW 单独 | 低风险，DW pipe 自带对抗验证足够 |
| 研究/分析报告 | DW judge panel + converge completeness critic | 多角度生成 + 完整度检查 |

---

## 与 converge 的分工边界

| 维度 | Dynamic Workflow | Converge |
|------|-----------------|----------|
| **做什么** | 规模化执行（fan-out、pipe、并行） | 迭代判断（多轮审查、收敛） |
| **审查深度** | 单次 A/B 对比 / claim 投票 | 多轮逐次独立 Reviewer |
| **迭代** | 无（一次性 fan-out + 收口） | outer/inner loop 分离 |
| **振荡检测** | 无 | Type O/R/F/S |
| **验收标准** | 脚本预设 / 测试套件 | 合同谈判（Reviewer 挑战后定） |
| **用户输入** | 无中途输入（硬限制） | 收敛后用户外部输入触发修订 |
| **中间结果** | 脚本变量（不进上下文） | .converge/ 文件系统 |

**不重复造轮子**：DW 的对抗验证是单次 A/B + claim 投票，适合"快速筛查"。converge 的多轮收敛适合"深度验证"。两者不互相替代——选哪个取决于风险级别。
