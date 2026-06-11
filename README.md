# Dynamic Workflow -- 多智能体规模化编排

> 把编排计划写进代码。脚本持有循环、分支和中间结果，主对话只保留最终答案。

## 快速入门

### 这是什么

Dynamic Workflow 是一套面向**没有原生 workflow runtime 的执行面**的多智能体编排模式 + CLI 调度器。它可配合 opencode、Codex 原生 `multi_agent_v1`，也可通过串行 `executor.py` 调用外部 `codex exec`。从 Claude Code 的 Workflow 工具中蒸馏而来，通过抽象原语 + `scripts/scheduler.py` 实现代码驱动的编排决策。

### 核心价值

- **规模化**：用持久化状态管理数十到数百次 agent 调用；实际并行度取决于 runtime，当前外部 CLI executor 为串行
- **可复用**：编排逻辑保存在脚本中，同模式可重复执行
- **质量内建**：对抗验证、多视角审查、完整性批评等模式确保输出可信
- **上下文隔离**：中间结果存在脚本变量/文件，不占用主对话上下文

### 什么时候用

- Codebase 级审计 / 大规模迁移（数百文件）
- 多源交叉验证研究
- 需要从多个角度独立起草的复杂计划
- 任何需要"独立审查彼此发现"的质量场景

### 快速开始（自动化执行）

```bash
# 1. 初始化 workflow
python scripts/scheduler.py init --slug my-workflow --mode pipe \
  --items src/auth/,src/api/ --stages review,verify --framework opencode

# 2. 全自动执行
python scripts/executor.py run --slug my-workflow
```

### 什么时候不用

- 单次简单委派（用 subagent）
- 线性单步任务（直接在主对话完成）
- 日常小修小补

### 文件导航

| 文件 | 内容 |
|------|------|
| `SKILL.md` | 主文档：定位、抽象原语、模式、决策、框架适配 |
| `refs/primitives.md` | 抽象原语参考 + CC API 映射入口 |
| `refs/cc-workflow-guide.md` | 参考：CC Workflow API（抽象原语以此为参考实现） |
| `refs/patterns.md` | 7 种质量模式的代码骨架和变体（抽象伪代码） |
| `refs/decision-guide.md` | 原语选择决策树、barrier 嗅觉测试、反模式 |
| `refs/framework-adapters.md` | Claude Code / opencode / codex / 通用降级 |
| `refs/compose-with-converge.md` | 与 converge SKILL 组合的质量门控协议 |
| `refs/constraint-injection.md` | 约束注入协议（三层结构 + post_injection_verify） |
| `refs/quality-gate-templates.md` | 门控脚本模板（run_quality_gate + 内置检查项） |
| `refs/manual-orchestration.md` | 手动编排示例（四步法 + Shannon 案例） |
| `scripts/scheduler.py` | **编排调度器 CLI**（非 CC 框架的代码驱动编排） |
| `scripts/executor.py` | **CLI 执行器**（自动调用 opencode/codex） |
| `scripts/adapters/` | 框架适配器（opencode、codex） |

### 四个原子能力

任何框架只要提供以下四个能力，就能实现所有编排模式：

1. **Spawn** -- 启动全新上下文的 agent，给自足 prompt
2. **Wait** -- 等待 agent 完成并获取输出
3. **Continue** -- 向已有 agent 发跟进消息，保有上下文
4. **Identify** -- 返回当前 agent 实例标识，用于引用和追踪

具体框架的映射见 `SKILL.md` 附录 A 和 `refs/framework-adapters.md`。

> ⚠️ **opencode 用户**：`task` 工具是同步阻塞的——无法真正并行 spawn。waitAll/pipe 降级为串行执行。
> ⚠️ **Codex 用户**：原生 `spawn_agent` 不支持 schema opts；外部 `codex exec` 支持 `--output-schema`、session resume、ephemeral 和 sandbox。两种执行面不能混为一谈，详见 `refs/framework-adapters.md`。

### Pilot 经验

1. **pipe 是默认选择**：barrier 只在真正需要跨 item 上下文时才加
2. **对抗验证有效但昂贵**：3 skeptics = 4x token。高风险用 3，低风险用 1-2
3. **Loop-Until-Dry 需要 seen set**：不仅 check confirmed，还要 tracking seen（去重池）
4. **fresh context 不可替代**：对抗审查的核心价值来自"看不到历史对话"
5. **completeness critic 往往找出最关键的遗漏**
