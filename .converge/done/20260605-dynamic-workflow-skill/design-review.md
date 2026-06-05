---
type: design-review
object_slug: 20260605-dynamic-workflow-skill
generated_at: 2026-06-05T00:40:00Z
---

# Design Review · 20260605-dynamic-workflow-skill

> 单轮咨询式审查，不阻断收敛。发现报告给用户决策。

## 7 维度审查结果

### DR1: 一致性（Consistency） — concerns_found

1. **cc-workflow-guide.md 定位模糊**
   - SKILL.md 拆分文件索引描述为"参考：CC Workflow API（抽象原语以此为模板）"，但 Positioning 段落没有明确说明这层"模板"关系
   - 位置：SKILL.md:137 vs SKILL.md:14-24
   - 影响：新 agent 无法判断 cc-workflow-guide.md 是"用来抄的"还是"用来参考的"

2. **跨 SKILL 隐性耦合**
   - `refs/compose-with-converge.md` 引用 converge SKILL 的 `refs/quality-gate.md` 作为外部依赖，但 SKILL.md 没有说明这是跨 SKILL 依赖
   - 位置：SKILL.md:28, refs/compose-with-converge.md
   - 影响：如果 converge 的 quality-gate.md 路径或接口变化，本 SKILL 会静默失效

### DR2: 完整性（Completeness） — concerns_found

1. **prompt 模板功能未文档化**
   - scheduler.py 支持 `--prompt-file` 参数实现 prompt 模板渲染，但 SKILL.md 的执行流程、原语表和拆分文件索引均未提及
   - 位置：SKILL.md:88-117（执行流程段落）
   - 影响：使用者不知道 scheduler.py 支持 prompt 模板，会手动拼接 prompt 字符串

2. **`.workflow/` 目录缺失文档**
   - scheduler.py 将状态文件写入 `.workflow/<slug>/state.json`，但 SKILL.md 目录结构只展示 `.converge/`
   - 位置：SKILL.md:300-318（目录结构段落）
   - 影响：新 agent 打开工作区看到 `.workflow/` 目录时不知道它是什么

3. **缺少 .gitignore**
   - `.workflow/` 下的 state.json（含运行时状态）会被 git 跟踪，当前已残留 3 个测试目录
   - 位置：仓库根目录
   - 影响：运行时状态泄露到版本控制

### DR3: 可维护性（Maintainability） — concerns_found

1. **两条执行路径选择标准不明确**
   - SKILL.md 同时描述了 scheduler.py（推荐）和手动编排，但两条路径的适用场景、选择标准和能力差异没有明确对比
   - 位置：SKILL.md:88-117
   - 影响：新 agent 可能在不需要 scheduler.py 的场景下引入它，或在需要它的场景下跳过它

2. **抽象层到实现层映射缺失**
   - 抽象能力层（4 原子）和编排原语（6 原子）是两层概念，但 SKILL.md 中从"抽象能力层"到"核心编排原语"的过渡缺乏映射说明
   - 位置：SKILL.md:32-58
   - 影响：阅读者在 SKILL.md 中无法独立理解"4 个原子能力如何支撑 6 个编排原语"

### DR4: 职责边界（Boundary Clarity） — clean

scheduler.py 与 Orchestrator 的职责边界在 SKILL.md 伪代码中已清晰划分。scheduler 持有状态和调度逻辑，Orchestrator 退化为 thin executor。

### DR5: 残留与冗余（Residue & Redundancy） — concerns_found

1. **active/ 目录未清理**
   - `.converge/active/` 和 `.converge/done/` 包含完全相同的文件，收敛已完成但 active/ 未移除
   - 位置：`.converge/active/20260605-dynamic-workflow-skill/`
   - 影响：可能误导后续 agent 认为收敛仍在进行中

2. **测试残留**
   - `.workflow/` 下残留 3 个测试目录（b15test/、nobudget/、partial/），没有文档说明来源和处置方式
   - 位置：`.workflow/`
   - 影响：测试残留与正式状态文件混在同一目录层级

### DR6: 可移植性（Portability） — clean

SKILL.md 使用相对路径引用，scheduler.py 的 `--dir` 参数允许自定义状态目录，框架适配表覆盖了 CC/opencode/codex 三个主要平台。收敛 contract E-14 专门测试了 Windows 文件锁定场景。

### DR7: 可扩展性（Scalability） — clean

规模控制有明确文档（单次最多 16 并发、1000 agent 总量），质量模式目录和框架适配表设计为可扩展的目录结构，refs/ 拆分策略使 SKILL.md 保持精简。

## Highlights（最重要的 3 个发现）

1. **`.workflow/` 目录文档盲区**
   - 发现：`.workflow/` 目录是 scheduler.py 的运行时状态存储，但 SKILL.md 完全没有提及
   - 重要性：新 agent 打开工作区会看到一个未文档化的目录，不知道是否应该版本控制
   - 建议方向：在 SKILL.md 目录结构中补充 `.workflow/` 的说明，并添加 .gitignore

2. **prompt 模板功能未文档化**
   - 发现：scheduler.py --prompt-file 功能在 contract 中有 9 条断言覆盖，但 SKILL.md 对此功能只字未提
   - 重要性：SKILL.md 是使用者的入口文档，入口文档不提及的功能等于不存在
   - 建议方向：在执行流程或编排原语段落中补充 prompt 模板的使用说明

3. **抽象层到实现层映射缺失**
   - 发现：抽象能力层（4 原子）到编排原语（6 原子）的映射关系只存在于 converge contract 中
   - 重要性：两层架构是理解整个设计的关键，缺少映射说明会让阅读者困惑
   - 建议方向：在 SKILL.md 的抽象能力层和编排原语之间增加一个简短的映射段落
