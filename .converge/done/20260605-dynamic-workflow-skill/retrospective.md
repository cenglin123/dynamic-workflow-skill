---
type: retrospective
object_slug: 20260605-dynamic-workflow-skill
generated_at: 2026-06-05T00:30:00Z
---

# Retrospective · 20260605-dynamic-workflow-skill

## 1. 结束模式

**收敛达成**（严格首轮通过 D11=a）：Round 2 fresh reviewer verdict = `可执行`，零 blocking issues。

## 2. 阻断轨迹

R1=1 → R2=0，单调下降。

- R1 blocking #1：scheduler.py budget 命令 allowed 字段语义不一致（implementation 级别）
- R2：修复已验证，blocking 清零

## 3. Antipattern 巡查

| Round | 类型 | 对象 | 触发结果 |
|-------|------|------|---------|
| 无 | - | - | 未发现 antipattern |

## 4. Executor 路径依赖评估

无路径依赖问题。Executor 修复方案最小化（单行代码修改），直接对齐 `_budget_allows` 语义。

## 5. Reviewer 间 Verdict 分歧分布

| 轮次 | Verdict | 阻断数 | 归因分布 |
|------|---------|--------|---------|
| R1 | 阻断需修复 | 1 | executor_limit: 1 |
| R2 | 可执行 | 0 | - |

## 6. 降级影响评估

无降级。使用 opencode 的 `task` 工具 Spawn 独立 Reviewer/Executor。

## 7. 经验教训

**机制层面**：
- 收敛在 2 轮内完成，符合实证经验（收敛均在 2-3 轮完成）
- 合同谈判（Round 0）有效对齐了验收标准，55 条断言覆盖了 11 个维度
- Reviewer 的确定性检查（实际运行 scheduler.py CLI）发现了仅靠代码审查难以捕获的语义不一致

**对象层面**：
- dynamic-workflow-skill 仓库质量较高，前置自检 5 个设计层问题全部通过
- scheduler.py 的实现基本正确，仅 budget allowed 字段存在边界条件 bug
- 跨文件一致性良好（SKILL.md ↔ primitives.md ↔ scheduler.py ↔ refs/*.md）

## 8. 后续建议

1. **考虑扩展测试覆盖**：当前 contract 断言主要验证 happy path，可增加更多边界条件测试
2. **SKILL.md 伪代码增强**：可补充 barrier/stop/done 等非 spawn 返回路径的展示
3. **opencode Continue 验证**：framework-adapters.md 中 opencode Continue（`task` + `task_id`）标注为 `[unverified]`，建议实际验证

## 9. Round 0 合同谈判评估

| 维度 | 评估 |
|------|------|
| 是否启用 | 是 |
| contract 是否减少预期错位 | 是 — 55 条断言提供了明确的验收标准，Reviewer 直接引用 contract 断言而非自行发明标准 |
| contract_amendment 触发次数 | 0 次 |
| contract 与 plan 的同步性 | 同步 — 无 plan 修订 |

## 10. Rubrics 评估

| 维度 | 评估 |
|------|------|
| 使用的维度 | 全部 11 个维度均被使用 |
| 未使用/总高分的维度 | 无 — 所有维度最终均达到 5 分 |
| rubric_gap 触发次数 | 0 次 |
| 跨轮分数趋势 | R1: scheduler-behavior=3（其余 4-5）→ R2: 全部 5 分 |

## 11. 设计审查触发评估

**触发条件检查**：
- [x] 产物涉及 ≥ 3 个独立模块（SKILL.md、primitives.md、scheduler.py、patterns.md、decision-guide.md、framework-adapters.md、compose-with-converge.md、cc-workflow-guide.md — 共 8 个模块）
- [x] 引入新目录结构/命名约定/跨组件接口（抽象原语 → 编排原语 → 框架适配的三层架构）
- [x] 定义了新的系统边界（DW 执行层 ↔ converge 判断层的组合协议）

**结论**：满足设计审查触发条件，已在收敛后触发设计审查。

## 12. 设计审查记录

**触发来源**：收敛后自动触发（满足 ≥3 模块 + 新约定/接口 + 系统边界条件）
**审查时间**：2026-06-05T00:40:00Z
**审查结论**：7 维度中 4 个发现 concerns（一致性、完整性、可维护性、残留与冗余），3 个 clean（职责边界、可移植性、可扩展性）

**Highlights**：
1. `.workflow/` 目录文档盲区 — 建议补充文档和 .gitignore
2. prompt 模板功能未文档化 — 建议在 SKILL.md 补充使用说明
3. 抽象层到实现层映射缺失 — 建议增加映射段落

**用户决策**：待用户审阅后决定
