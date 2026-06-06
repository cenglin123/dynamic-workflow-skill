# converge SKILL 设计反馈报告

> **反馈来源**：dynamic-workflow-skill 仓库的 converge 流程实践
> **反馈日期**：2026-06-06
> **反馈人**：opencode agent

---

## 问题描述

在使用 converge SKILL 审查 workflow 约束改进计划时，发现 Reviewer 无法追溯原始问题报告，导致审计模型无法掌握完整信息链。

### 现象

1. **原问题报告**：`C:\Project\TEMP\shannon_communication_markdown_formula_content\.workflow\issue-report.md`
2. **收敛过程**：Reviewers 审查了计划文件，但没有读取原问题报告
3. **结果**：审计模型无法追溯问题根源，只能看到计划文件本身

### 根因

converge SKILL 的 reviewer-prompt.md 要求 Reviewer 读取：
1. plan 文件
2. attempts.md
3. converge SKILL
4. contract.md（如果有）

**但没有要求读取原始问题报告或相关背景材料**。

---

## 影响评估

| 维度 | 影响 |
|------|------|
| **审计完整性** | 审计模型无法追溯问题根源，只能审查计划文件本身 |
| **收敛质量** | Reviewer 缺少原始问题上下文，可能遗漏关键约束 |
| **信息链断裂** | 从问题报告 → 计划 → 收敛记录的信息链不完整 |
| **可追溯性** | 无法验证计划是否真正解决了原始问题 |

---

## 改进建议

### 建议 1: 在 reviewer-prompt.md 中添加"参考材料"章节

```markdown
## 参考材料（可选）

若存在以下材料，Orchestrator 应在 prompt 中提供路径：
- 原始问题报告
- 需求文档
- 用户反馈
- 相关讨论记录
- 设计规格

Reviewer 应在审查时参考这些材料，确保理解完整上下文。
```

### 建议 2: 在 _orchestrator-state.md 中记录原报告地址

```markdown
## Reference Materials

- **原问题报告**：<路径>
- **需求文档**：<路径>
- **设计规格**：<路径>
```

### 建议 3: 在 round-N.md 中强制记录参考材料

```markdown
## 参考材料

- **原问题报告**：<路径>
- **计划文件**：<路径>
- **contract.md**：<路径>（如有）
```

### 建议 4: 在 retrospective.md 中添加问题溯源章节

```markdown
## 问题溯源

### 原始问题
- **问题来源**：<路径>
- **问题摘要**：<一句话描述>
- **影响范围**：<受影响的模块/功能>

### 收敛结果
- **是否解决原始问题**：是/否/部分
- **解决方式**：<一句话描述>
- **遗留问题**：<如有>
```

---

## 实施建议

### 优先级

| 建议 | 优先级 | 工作量 | 说明 |
|------|--------|--------|------|
| 建议 1 | P0 | 0.5 天 | 在 reviewer-prompt.md 中添加参考材料章节 |
| 建议 2 | P0 | 0.5 天 | 在 _orchestrator-state.md 中记录原报告地址 |
| 建议 3 | P1 | 0.5 天 | 在 round-N.md 中强制记录参考材料 |
| 建议 4 | P1 | 0.5 天 | 在 retrospective.md 中添加问题溯源章节 |

### 实施位置

| 文件 | 修改内容 |
|------|----------|
| `refs/reviewer-prompt.md` | 添加"参考材料"章节 |
| `refs/state-schema.md` | 在 _orchestrator-state.md 格式中添加 Reference Materials |
| `refs/state-schema.md` | 在 round-N.md 格式中添加参考材料章节 |
| `refs/state-schema.md` | 在 retrospective.md 格式中添加问题溯源章节 |

---

## 总结

**核心问题**：converge SKILL 没有要求在收敛过程中传递原始材料（问题报告、需求文档等），导致信息链断裂。

**改进方向**：在 reviewer-prompt.md 和 state-schema.md 中添加"参考材料"相关章节，确保 Reviewer 和审计模型能够追溯完整信息链。

**预期收益**：
1. 审计模型可以追溯问题根源
2. Reviewer 可以理解完整上下文
3. 收敛记录包含完整信息链
4. 可追溯性得到保障
