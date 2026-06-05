# 编排决策指南

> 什么时候用什么原语、什么模式、怎么组合。
>
> **代码约定**：以下用**抽象伪代码**描述。原语 `spawn` / `waitAll` / `pipe` / `group` / `report` 的语义见 `SKILL.md` 和 `refs/primitives.md`。Claude Code 用户参考 `refs/cc-workflow-guide.md` 获取原生 API 语法。

---

## 原语选择决策树

```
任务可分解为多个独立 item？
|-- 否 -> 单个 spawn() 调用
|-- 是 ->
    items 之间有数据依赖吗？
    |-- 有 -> 单个 spawn 处理，或 chain 两个 spawn
    |-- 无 ->
        需要多阶段处理吗？
        |-- 否 -> waitAll() 单阶段 fan-out
        |-- 是 ->
            stage 之间需要跨 item 上下文吗？
            |-- 否 -> pipe()  <- **默认**
            |-- 是 -> waitAll() 完成全部 -> 处理跨 item -> waitAll() 下一阶段
```

---

## Barrier 嗅觉测试

以下每个"我需要 barrier"的理由，检查是否真的需要：

| 你说 | 嗅觉 | 替代 |
|------|------|------|
| "我需要 flatten/map/filter 结果" | 纯数据变换，不需要 barrier | 在 pipe stage 内做 |
| "这两个阶段概念上分开" | 概念分离 != 同步点 | 用 `group()` 区分显示，不改变流控 |
| "代码更清晰" | 清晰 != 正确。barrier 浪费墙钟 | pipe 的代码也可以很清晰 |
| "我需要先看看全部结果再决定下一步" | **这确实是 barrier 理由**——但确认一下：真的需要全部？还是看到第一个就够了？ |
| "我要对所有发现去重" | **这是真正的 barrier 理由** | 去重需要全量 -> waitAll 打平 |
| "如果结果为 0 就跳过后续" | **这是真正的 barrier 理由** | 提前退出需要全量 -> waitAll 打平 |

### 真正需要 barrier 的场景

1. **去重**：需要对全部结果做 cross-item dedup
2. **提前退出**：0 发现 -> 跳过昂贵的验证阶段
3. **排序/优先级**：需要全量排名后只处理 top-N
4. **交叉比较**：Stage N 的 prompt 需要引用"其他发现"做比较

### 伪 barrier 场景（该用 pipe）

1. "我需要 transform 结果"——在 stage 内做
2. "概念上分阶段"——用 group() 分组
3. "好看/整齐"——不是工程理由
4. "反正都要等"——不，pipe 里快 item 不用等慢 item

---

## 质量模式选择决策树

```
任务性质？
|-- 发现/搜索类（找 bug、找漏洞、找边界情况）
|   |-- 已知上限 -> 固定次数 waitAll fan-out
|   |-- 未知上限 -> Loop-Until-Dry
|   |-- 多个搜索维度 -> Multi-Modal Sweep
|
|-- 验证/判断类（确认发现、评估方案）
|   |-- 单一失败模式 -> 对抗验证（2-3 skeptics）
|   |-- 多种失败模式 -> 多视角验证（不同透镜）
|   |-- 两者结合 -> 多视角内各加对抗
|
|-- 生成/设计类（设计方案、规划架构）
|   |-- 方案空间小 -> 单个 spawn + 对抗审查
|   |-- 方案空间大 -> 评委团（多角度起草 -> 评分 -> 合成）
|
|-- 确保完整性
    |-- 任何任务收口前 -> 完整度批评
```

---

## 预算管理决策

```
预算总额存在？
|-- 否 -> 无限制，正常编排
|-- 是 ->
    预算剩余 > 单 agent 成本 * 需要的最少 agent 数？
    |-- 是 -> 按预算动态调整并发度
    |-- 否 ->
        降级选项：
        1. 减少 skeptic 数（3->1）
        2. 缩减搜索范围
        3. 降级 L2 门控 -> L1
        4. 告知用户预算不足
```

### 并发度估算（伪代码）

```
function estimateFleet(budgetTotal, avgTokensPerAgent = 15000):
  if !budgetTotal: return 5  // 无限制，保守默认
  remaining = budgetTotal - spent
  maxAgents = floor(remaining / avgTokensPerAgent)
  return min(maxAgents, 16)  // 不超过并发上限
```

---

## 反模式

### 反模式 1：屏障成瘾

**症状**：所有 fan-out 都用 waitAll()，即使后续 stage 不需要跨 item 上下文。

**代价**：快 agent 空等慢 agent。10 个 items，最快 5s 最慢 45s -> waitAll 耗时 45s，pipe 可能 25s（pipe 内下游 work 和上游 work 重叠）。

**修正**：默认 pipe，只在满足 barrier 必要条件时回退到 waitAll。

### 反模式 2：假独立审查

**症状**：用 Continue 给同一个 agent 发"用独立视角再看一遍"。

**代价**：该 agent 保有之前上下文的锚定效应——不是真正的独立审查。

**修正**：Spawn 全新 agent。对抗审查的核心价值来自 fresh context。

### 反模式 3：无底洞循环

**症状**：Loop-Until-Dry 不带 `seen` set 去重。

**代价**：judge 拒绝的发现每轮重新出现 -> 永不收敛（每轮"发现"同样的假阳性）。

**修正**：维护 `seen` set，不仅 tracking `confirmed`。

### 反模式 4：静默降级

**症状**：预算不够了，悄悄把 3-skeptic 改成 1-skeptic，不告诉用户。

**代价**：用户以为得到了完全对抗验证的结论，实际只有单次审查。

**修正**：任何降级必须 `report()` 告知用户，并在最终报告中标注降级模式。

### 反模式 5：Schema 缺失

**症状**：spawn() 不传 schema，手工解析自然语言输出。

**代价**：脆弱的字符串匹配、解析失败、agent 输出格式漂移。

**修正**：支持 schema 的框架必传；opencode/codex 需 prompt 格式约束 + Orchestrator 手动解析/校验/重试（见 framework-adapters.md）。

### 反模式 6：巨型 prompt

**症状**：一个 spawn prompt 包含 5 个独立子任务。

**代价**：agent 在子任务间注意力分散；一个子任务失败影响全部；无法并行。

**修正**：独立子任务 = 独立 spawn() 调用。组合用 waitAll / pipe。
