---
type: contract
object_slug: 20260605-dynamic-workflow-skill
round: 0
status: revised
revision: 2
revised_at: 2026-06-05T00:00:00Z
revision_reason: "Executor 修订 — 修复 3 个 blocking issues + 采纳 8 个 suggestions"
dimensions:
  - structural-integrity
  - semantic-correctness
  - api-consistency
  - scheduler-behavior
  - prompt-rendering
  - error-handling
  - cross-file-coherence
  - edge-cases
---

# Contract · dynamic-workflow-skill · Round 0 (Revised)

> 本合同定义 dynamic-workflow-skill 仓库的可测试断言。每条断言有唯一 ID、维度、严重级、测试方法。
>
> **修订说明**：基于 Reviewer Round 0 挑战修订。修复 3 个 blocking issues，采纳 8 个 suggestions，新增 19 条断言。

---

## 断言表

### 维度 1: structural-integrity（SKILL.md 结构完整性）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| S-01 | SKILL.md YAML front matter 包含 `name` 和 `description` 字段 | blocking | 解析 YAML，断言两字段存在且非空 |
| S-02 | SKILL.md 包含以下一级标题（按顺序）：Positioning、抽象能力层、核心编排原语、质量模式目录、编排决策指南、执行流程、Orchestrator 责任清单、拆分文件索引、附录 A | blocking | 正则提取 `^## ` 标题，断言顺序和存在性 |
| S-03 | 拆分文件索引中列出的 7 个文件全部存在于 refs/ 或 scripts/ 目录 | blocking | 逐个检查文件存在性 |
| S-04 | SKILL.md 中所有 `refs/xxx.md` 和 `scripts/xxx.py` 链接的目标文件存在 | blocking | 提取所有 markdown 链接，检查目标文件 |

### 维度 2: semantic-correctness（抽象能力层语义正确性）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| C-01 | SKILL.md 抽象能力层定义 4 个原子能力：Spawn、Wait、Continue、Identify | blocking | 解析表格，断言恰好 4 行且名称匹配 |
| C-02 | SKILL.md 抽象能力层的 Spawn 语义为"启动全新上下文的 agent，给自足 prompt"，输入为 prompt 文本，输出为 instance_id | blocking | 解析表格行，断言语义/输入/输出字段 |
| C-03 | **[rev-1]** primitives.md 定义 6 个编排原语：spawn、waitAll、pipe、group、report、budget guard | blocking | 提取 `### ` 标题，断言恰好 6 个且名称匹配 |
| C-04 | **[rev-2·blocking-fix]** primitives.md 的 6 个原语与 SKILL.md 核心编排原语表格的 6 行一一对应（名称、签名、语义一致） | blocking | 逐行比对两个表格的原语名称和语义描述 |
| C-05 | **[rev-3·blocking-fix]** SKILL.md 抽象能力层（Spawn/Wait/Continue/Identify）是概念层，primitives.md 编排原语（spawn/waitAll/pipe/group/report/budget guard）是实现层。两者是**抽象→具体**的映射关系，不要求一一对应。spawn 映射 Spawn；waitAll 映射 Wait；pipe 构建于 Spawn+Wait 之上；Continue/Identify 无直接对应的编排原语参数表 | blocking | 人工审查映射关系文档 |
| C-06 | primitives.md Part 1 中 spawn 的参数表包含 `prompt`（required）、`opts.schema`、`opts.label`、`opts.model`、`opts.isolation`、`opts.agentType` | blocking | 解析 spawn 参数表 |
| C-07 | primitives.md Part 2 映射表中 CC 原生 API 列包含 `agent`、`parallel`、`pipeline`、`phase`、`log`、`budget.total/spent()/remaining()` | blocking | 解析映射表 |
| C-08 | **[rev-4·suggestion]** framework-adapters.md 中 opencode 的 Continue 实现（`task` + `task_id`）标注为 `[unverified]`，因为上下文保真度未经独立验证 | major | 检查 opencode Continue 行是否含 `[unverified]` 标记 |

### 维度 3: api-consistency（跨文件 API 一致性）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| A-01 | SKILL.md 附录 A 框架适配表的抽象原语列与 primitives.md Part 2 映射表的抽象原语列一致 | blocking | 提取两个表格的原语名称列，比对集合相等 |
| A-02 | framework-adapters.md 中 CC 适配表的 6 个原语与 primitives.md Part 2 映射表一致 | blocking | 同上 |
| A-03 | framework-adapters.md 中 opencode 适配表的 6 个原语与 primitives.md Part 2 映射表一致 | blocking | 同上 |
| A-04 | framework-adapters.md 中 codex 适配表的 6 个原语与 primitives.md Part 2 映射表一致 | blocking | 同上 |
| A-05 | **[rev-5·suggestion]** SKILL.md 伪代码中的 JSON 输出字段名（`action`、`item`、`stage`、`stage_idx`、`prompt`、`round`、`summary`）与 scheduler.py `_spawn_item` 和 `_summarize` 函数的输出字段名完全一致 | blocking | 提取 SKILL.md 伪代码中的字段名，与 scheduler.py 源码比对 |
| A-06 | **[rev-6·suggestion]** refs 文件之间的交叉引用路径全部存在：patterns.md 引用 SKILL.md/primitives.md；decision-guide.md 引用 SKILL.md/primitives.md/cc-workflow-guide.md；compose-with-converge.md 引用 converge 的 refs/quality-gate.md（标注为外部依赖，不要求本地存在） | major | 提取所有 `refs/xxx.md` 引用，检查本地存在性 |

### 维度 4: scheduler-behavior（scheduler.py 行为正确性）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| B-01 | `scheduler.py init --slug test --mode pipe --items a,b,c --stages x,y` 在 `.workflow/test/state.json` 创建正确状态文件，包含 items=["a","b","c"]、stages=["x","y"]、mode="pipe" | blocking | 执行命令，读取 JSON，断言字段 |
| B-02 | `scheduler.py dispatch --slug test` 在 pipe 模式下返回 `{"action":"spawn","item":"a","stage":"x","stage_idx":0}`（第一个 item 的第一个 stage） | blocking | init + dispatch，断言返回 |
| B-03 | `scheduler.py complete --slug test --item a --stage x --result '{"ok":true}'` 将 item a 的 status 设为 "done"，budget.spent 增加 | blocking | init → dispatch → complete → 读取 state |
| B-04 | complete 后再次 dispatch，pipe 模式返回 item a 的 stage y（`stage_idx: 1`），而非 item b 的 stage x | blocking | 完整 pipe 流程，断言 stage 推进顺序 |
| B-05 | waitall 模式下，所有 items 的同一 stage 完成后，dispatch 返回 `{"action":"barrier"}` | blocking | init waitall → dispatch 全部 → complete 全部 → dispatch → 断言 barrier |
| B-06 | barrier 后必须调用 `barrier-done` 才能继续 dispatch，否则返回 `barrier_pending_ack` 错误 | blocking | barrier 后直接 dispatch，断言错误 |
| B-07 | loop 模式下 dispatch 返回 `{"action":"spawn","item":"_finder"}` 且含 `round` 字段 | blocking | init loop → dispatch，断言 |
| B-08 | loop 模式下 complete `_finder` 后，必须调用 `loop-feedback` 才能继续 dispatch | blocking | complete finder → dispatch → 断言 loop_feedback_pending |
| B-09 | `loop-feedback --new-count 0` 使 dry_counter +1；`--new-count N`(N>0) 使 dry_counter 归零 | blocking | 多轮 loop-feedback，断言 dry_counter 变化 |
| B-10 | loop 模式 dry_counter 达到 dry_threshold 后，dispatch 返回 `{"action":"done"}` | blocking | 循环 feedback 直到阈值，断言 done |
| B-11 | budget_total 设为 1000，spend 后 dispatch 返回 `{"action":"stop","reason":"budget_exhausted"}` | blocking | init(budget=1000) → budget --spend 1000 → dispatch → 断言 stop |
| B-12 | `scheduler.py status --slug test` 返回包含 `running_count`、`pending_count`、`done_count`、`failed_count` 的 JSON | blocking | status 命令，断言字段存在 |
| B-13 | `scheduler.py budget --slug test` 返回 `{"total":...,"spent":...,"remaining":...,"allowed":...}` | blocking | budget 命令，断言字段 |
| B-14 | **[rev-7·suggestion]** `scheduler.py complete --slug test --item a --stage WRONG` 当 a 不在 stage WRONG 时，返回 `{"error":"stage_mismatch"}` 到 stderr，exit code = 1 | blocking | 执行错误命令，断言 stderr 含 stage_mismatch 且 exit code = 1 |
| B-15 | **[rev-8·suggestion]** `budget` 命令当 `spent == total` 时，`allowed` 字段语义：当前实现 `allowed = (total is None or spent <= total)` 使 `spent == total` 时 `allowed=true`，但 `_budget_allows` 使用 `spent < total`。合同要求：`budget` 命令的 `allowed` 字段与 `_budget_allows` 一致，即 `spent >= total` 时 `allowed=false` | blocking | budget --spend 使 spent==total，断言 allowed=false |
| B-16 | **[rev-9·suggestion]** `scheduler.py dispatch` 的 JSON 输出写入 stdout；错误信息写入 stderr 且为合法 JSON | blocking | 正常 dispatch 检查 stdout；错误 dispatch 检查 stderr JSON 合法性 |
| B-17 | `complete --result 'not-json'` 将 result 作为原始字符串存储（不报错） | major | complete 非 JSON result，断言 state 中存储原始字符串 |
| B-18 | `complete --retry` 将 item 状态重置为 pending 并增加 retry_count，不写入 results 数组 | blocking | retry 流程，断言状态和计数 |
| B-19 | retry 次数达到 max_retries 后，item 状态变为 "failed"，error 为 "max_retries_exceeded" | blocking | 多次 retry，断言终态 |
| B-20 | `--dir custom_dir` 参数使状态文件写入 `custom_dir/<slug>/state.json` 而非默认 `.workflow/<slug>/state.json` | blocking | init --dir tmp → 检查文件路径 |
| B-21 | **[rev-10·suggestion]** `--max-retries 0` 时，complete --retry 立即将 item 设为 "failed" | major | init(max-retries=0) → dispatch → complete --retry → 断言 failed |

### 维度 5: prompt-rendering（prompt 模板渲染）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| P-01 | **[rev-11·blocking-fix]** `--prompt-file templates.json` 中的 JSON 在 init 时加载到 state.prompt_templates | blocking | 创建模板文件 → init → 读取 state，断言 prompt_templates 字段 |
| P-02 | **[rev-12·blocking-fix]** `_render_prompt` 将模板中的 `{{item}}` 替换为当前 item 名称 | blocking | init(prompt-file) → dispatch → 检查 spawn action 的 prompt 字段含 item 名称 |
| P-03 | **[rev-13·blocking-fix]** `_render_prompt` 将 `{{stage}}` 替换为当前 stage 名称 | blocking | 同上，检查 stage 名称替换 |
| P-04 | **[rev-14·blocking-fix]** `_render_prompt` 将 `{{round}}` 替换为当前 loop 轮次（loop 模式） | blocking | init loop(prompt-file) → dispatch → 检查 prompt 含 round 数字 |
| P-05 | **[rev-15·blocking-fix]** `_render_prompt` 将 `{{domain}}` 替换为 config.context.domain 值 | blocking | init → 修改 context.domain → dispatch → 检查 prompt |
| P-06 | **[rev-16·blocking-fix]** `_render_prompt` 将 `{{seen}}` 替换为 JSON 序列化的 context.seen 数组 | blocking | init → 设置 context.seen → dispatch → 检查 prompt 含 JSON 数组 |
| P-07 | **[rev-17·blocking-fix]** `_render_prompt` 将 `{{context}}` 替换为 JSON 序列化的完整 context 对象 | blocking | init → dispatch → 检查 prompt 含完整 context JSON |
| P-08 | **[rev-18·blocking-fix]** 未匹配的 `{{variable}}` 保留在 prompt 中不做替换（不报错） | major | 模板含 `{{unknown}}` → dispatch → 检查 prompt 保留原样 |
| P-09 | **[rev-19·blocking-fix]** waitall 模式下 `_render_prompt` 将 `{{batch_idx}}` 替换为当前 batch 索引 | blocking | init waitall(prompt-file) → dispatch → 检查 prompt 含 batch_idx 数字 |

### 维度 6: error-handling（错误处理与边界条件）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| E-01 | `init --slug test` 重复执行返回 `{"error":"already_exists"}` 到 stderr，exit code = 1 | blocking | init 两次，断言第二次失败 |
| E-02 | `dispatch --slug nonexistent` 返回 `{"error":"not_found"}` 到 stderr，exit code = 1 | blocking | dispatch 不存在的 slug，断言 |
| E-03 | `init --items "" --stages x` 返回 `{"error":"no_items"}` 到 stderr，exit code = 1 | blocking | 空 items，断言 |
| E-04 | `init --items a --stages ""` 返回 `{"error":"no_stages"}` 到 stderr，exit code = 1 | blocking | 空 stages，断言 |
| E-05 | `complete --slug test --item nonexistent --stage x` 返回 `{"error":"invalid_item"}` 到 stderr，exit code = 1 | blocking | 无效 item，断言 |
| E-06 | `complete` 一个 status 非 "running" 的 item 返回 `{"error":"protocol_violation"}` 到 stderr，exit code = 1 | blocking | 对 pending item complete，断言 |
| E-07 | `barrier-done` 在非 waitall 模式下返回 `{"error":"not_waitall_mode"}` | blocking | pipe 模式 barrier-done，断言 |
| E-08 | `barrier-done` 在无 pending barrier 时返回 `{"error":"protocol_violation"}` | blocking | 无 barrier 时 barrier-done，断言 |
| E-09 | `loop-feedback` 在非 loop 模式下返回 `{"error":"not_loop_mode"}` | blocking | pipe 模式 loop-feedback，断言 |
| E-10 | `loop-feedback` 在 finder 未完成时返回 `{"error":"protocol_violation"}` | blocking | 未 dispatch finder 时 feedback，断言 |
| E-11 | `init --prompt-file nonexistent.json` 返回 `{"error":"invalid_prompt_file"}` 到 stderr，exit code = 1 | blocking | 不存在的模板文件，断言 |
| E-12 | `init --prompt-file bad.json`（内容非合法 JSON）返回 `{"error":"invalid_prompt_file"}` | blocking | 坏 JSON 文件，断言 |
| E-13 | state.json 文件损坏（非法 JSON）时，load_state 返回 `{"error":"invalid_state"}` 到 stderr，exit code = 1 | blocking | 手动破坏 state.json → dispatch → 断言 |
| E-14 | **[rev-20·suggestion]** Windows 平台下 atomic write（tmp.replace(path)）在目标文件被锁定时返回 `{"error":"write_failed"}` 到 stderr，exit code = 1 | major | 模拟文件锁定 → save_state → 断言错误 |
| E-15 | budget_total 为 None 时，`_budget_allows` 始终返回 True | blocking | init(no budget) → 断言 dispatch 不受预算限制 |

### 维度 7: quality-mode-patterns（质量模式完整性）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| Q-01 | patterns.md 定义 7 种模式：对抗验证、多视角验证、评委团、Loop-Until-Dry、多模态搜索、完整度批评、无静默截断 | blocking | 提取 `## ` 标题，断言 7 个模式名 |
| Q-02 | 每种模式的代码骨架包含至少一个 `spawn` 调用 | blocking | 提取代码块，检查 spawn 出现 |
| Q-03 | 对抗验证代码骨架中 `waitAll` 包含 `repeat(skepticCount, ...)` 调用 | blocking | 提取代码，断言结构 |
| Q-04 | **[rev-21·blocking-fix]** 评委团代码骨架的可执行逻辑行数（去除注释、空行、纯括号行）≤ 60 行 | blocking | 统计代码骨架有效行数 |
| Q-05 | Loop-Until-Dry 代码骨架包含 `seen` Set 维护和 `dry` 计数器 | blocking | 提取代码，断言变量存在 |
| Q-06 | 完整度批评代码骨架的 schema 包含 `gaps` 数组，每个 gap 有 `category`、`description`、`severity` | blocking | 提取 schema 定义，断言字段 |
| Q-07 | 无静默截断模式声明了所有应声明的情况：Top-N 截断、抽样、跳过、降级、提前退出 | blocking | 提取"所有应声明的情况"列表，断言 5 项 |
| Q-08 | **[rev-22·suggestion]** decision-guide.md 质量模式选择决策树的叶子节点覆盖所有 7 种模式：固定次数 waitAll → 多模态搜索（需映射）；Loop-Until-Dry；对抗验证；多视角验证；评委团；完整度批评 | major | 遍历决策树叶子节点，断言覆盖 |

### 维度 8: loop-mode-lifecycle（loop 模式完整生命周期）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| L-01 | **[rev-23·suggestion]** loop 模式完整生命周期：init → dispatch(_finder round 1) → complete(_finder) → loop-feedback(new=3) → dispatch(_finder round 2) → complete(_finder) → loop-feedback(new=0) → dispatch(_finder round 3) → complete(_finder) → loop-feedback(new=0) → dispatch(done) | blocking | 端到端脚本执行，断言每步返回的 action 和 round |
| L-02 | loop 模式下 _finder 的 results 和 attempts 在 loop-feedback 时被清空 | blocking | feedback 后读取 state，断言 _finder 字段 |
| L-03 | loop 模式 max_rounds 达到后 dispatch 返回 `{"action":"stop","reason":"max_rounds_reached"}` | blocking | 循环到 max_rounds，断言 stop |
| L-04 | loop 模式下 complete(_finder) 后 state.loop.feedback_pending = True | blocking | complete 后读取 state |
| L-05 | loop 模式下 _finder 的 round 字段在每次 dispatch 时递增 | blocking | 多轮 dispatch，断言 round 递增 |

### 维度 9: pipe-streaming-semantics（pipe 流式语义）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| F-01 | **[rev-24·suggestion]** pipe 模式下 item A stage 1 完成后，dispatch 立即返回 item A stage 2（即使 item B stage 1 尚未完成） | blocking | init(items=a,b; stages=x,y) → dispatch(a,x) → complete(a,x) → dispatch → 断言返回 a,y 而非 b,x |
| F-02 | pipe 模式下所有 item 完成所有 stage 后 dispatch 返回 `{"action":"done"}` | blocking | 完整 pipe 流程，断言 done |
| F-03 | pipe 模式下 running 数达到 max_concurrency 时 dispatch 返回 `{"action":"wait","reason":"concurrency_limit"}` | blocking | init(concurrency=1) → dispatch(a,x) → dispatch → 断言 wait |
| F-04 | pipe 模式下 failed 且未耗尽 retries 的 item 被重新 dispatch | blocking | complete(null) → dispatch → 断言重新 spawn |

### 维度 10: state-persistence（状态持久化）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| T-01 | state.json 的 updated_at 在每次 save 后更新 | blocking | init → 记录时间 → dispatch → 断言时间变化 |
| T-02 | state.json 使用 atomic write（先写 .tmp 再 replace），无中间态文件残留 | blocking | 检查 save_state 实现 |
| T-03 | state.json 使用 `ensure_ascii=False` 编码，支持非 ASCII 字符 | blocking | init(含中文 slug) → 读取 state，断言中文正确 |
| T-04 | `complete --tokens 500` 使 budget.spent 增加 500（而非默认 ESTIMATED_TOKENS_PER_AGENT） | blocking | complete --tokens 500 → budget → 断言 spent |

### 维度 11: cross-file-coherence（跨文件一致性）

| ID | 断言 | 严重级 | 测试方法 |
|----|------|--------|---------|
| X-01 | SKILL.md 执行流程伪代码中的命令（`dispatch`、`complete`、`barrier-done`、`loop-feedback`）与 scheduler.py 的子命令一致 | blocking | 提取伪代码命令名，比对 argparse 子命令 |
| X-02 | SKILL.md 附录 A 表格中 opencode 的 Spawn 实现描述为 `task` 工具，与 framework-adapters.md 一致 | blocking | 比对两处描述 |
| X-03 | SKILL.md 附录 A 表格中 codex 的 Spawn 实现描述为 `multi_agent_v1.spawn_agent`，与 framework-adapters.md 一致 | blocking | 比对两处描述 |
| X-04 | compose-with-converge.md 中引用的 converge SKILL 路径（`refs/quality-gate.md`）标注为外部依赖 | major | 检查文件中是否说明外部依赖 |
| X-05 | decision-guide.md 中反模式 6（巨型 prompt）的修正建议与 primitives.md 中 spawn 的 prompt 自足性约束一致 | major | 比对两处描述 |
| X-06 | **[rev-25·suggestion]** scheduler.py 输出的 JSON 字段名与 SKILL.md 执行流程伪代码中引用的字段名一致：`action`（spawn/done/stop/wait/barrier）、`item`、`stage`、`prompt`、`round`、`reason`、`summary` | blocking | 提取 scheduler.py 所有 json.dumps 的 key 集合，与 SKILL.md 伪代码比对 |

---

## 修订记录

| 修订 | 断言 ID | 变更 | 原因 |
|------|---------|------|------|
| rev-1 | C-01 | 明确 SKILL.md 抽象能力层为 4 个概念 | 与 primitives.md 的 6 个编排原语区分 |
| rev-2 | C-04 | 新增：primitives.md 6 原语与 SKILL.md 表格一一对应 | **Blocking fix #1**：原断言 #9 错误对齐 |
| rev-3 | C-05 | 新增：明确抽象层→实现层映射关系不要求一一对应 | **Blocking fix #1**：纠正 Continue/Identify 对齐错误 |
| rev-4 | C-08 | 新增：opencode Continue 标注 `[unverified]` | Suggestion #4 |
| rev-5 | A-05 | 新增：SKILL.md 伪代码与 scheduler.py 字段名一致性 | Suggestion #14 |
| rev-6 | A-06 | 新增：refs 文件交叉引用路径存在性检查 | Suggestion #15 |
| rev-7 | B-14 | 新增：stage_mismatch 错误返回 exit code = 1 | Suggestion #5 |
| rev-8 | B-15 | 新增：budget allowed 语义修正 | Suggestion #6 |
| rev-9 | B-16 | 新增：stdout/stderr JSON 合法性验证 | Suggestion #9 |
| rev-10 | B-21 | 新增：max-retries=0 边界测试 | Suggestion #13 |
| rev-11~19 | P-01~P-09 | 新增 9 条 prompt 模板渲染断言 | **Blocking fix #3**：完全覆盖 _render_prompt |
| rev-20 | E-14 | 新增：Windows 文件锁定错误处理 | Suggestion #8 |
| rev-21 | Q-04 | 新增：评委团行数限制放宽至 60 行 | **Blocking fix #2**：40 行过严 |
| rev-22 | Q-08 | 新增：决策树叶子节点覆盖检查 | Suggestion #11 |
| rev-23 | L-01~L-05 | 新增 5 条 loop 生命周期断言 | Suggestion #10 |
| rev-24 | F-01 | 新增：pipe 中间状态断言 | Suggestion #7 |
| rev-25 | X-06 | 新增：scheduler.py 输出字段名一致性检查 | Suggestion #14 |
