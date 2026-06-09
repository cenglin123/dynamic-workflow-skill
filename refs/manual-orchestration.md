# 手动编排示例

> 本文件从 SKILL.md 拆分而来，包含不依赖 scheduler 的手动编排完整流程。

## 四步法

手动编排是合法路径，适用于 opencode 框架或不想依赖 scheduler.py 的场景。编排者必须严格遵循以下四步法：

1. **解析任务 → 确定编排模式**（pipe / waitAll / loop）
2. **执行原语**：pipe = item-by-item 推进 stage，无屏障；waitAll = 批量 Spawn + Wait；loop = Spawn → 收集 → 判定
3. **中间结果存 scratch 文件**，不进主对话（子代理返回的 evidence 写入 scratch 文件）
4. **最终答案写入主对话**

## opencode 框架完整示例

以下展示一个 waitAll 模式的手动编排流程（Shannon 案例：并行修复 4 个 chunk 的段落换行）。

### Step 1：解析任务，确定编排模式

```
任务：修复 4 个 markdown 文件的段落异常换行
模式：waitAll（4 个 chunk 相互独立，可并行）
Stage：fix-wrapping
```

### Step 2：构造设计契约 + 注入约束

```json
{
  "design_contract": {
    "objective": "修复段落中的异常换行",
    "constraints": [
      "使用 Edit 工具逐行修复，禁止编写任何脚本",
      "按段落语义边界合并，非简单正则替换",
      "保留特殊格式元素（公式 $$、标题 #、注释 <!-- -->）",
      "遇到不确定时读取上下文而非猜测"
    ],
    "allowed_tools": ["Read", "Edit"],
    "forbidden_tools": ["Bash"],
    "forbidden_patterns": ["\\.py$", "\\.ps1$", "\\.sh$"],
    "anti_patterns": ["脚本试错循环", "格式破坏", "合并错误"],
    "execution_path": "读取目标行 → 判断语义边界 → 使用 Edit 工具合并 → 验证格式",
    "mandatory_terms": {
      "DeepSeek": "DeepSeek",
      "Claude": "Claude（Anthropic 公司）"
    },
    "term_verification": "不确定术语保留原文并标记 [UNCERTAIN]",
    "evidence_template": {
      "files_written": [],
      "files_modified": [],
      "file_sizes": {},
      "verification_commands": [],
      "uncertainty_markers": []
    }
  }
}
```

### Step 3：同消息批量并行 Spawn（waitAll）

在 opencode 中，将所有 task 调用放在同一条消息中，框架会并行执行：

```
请同时执行以下 4 个任务（不要串行，一次性全部发出）：

Task 1: 修复 chunk1.md 的段落换行
  - 文件：output/chunk1.md
  - [注入设计契约的自然语言序列化]

Task 2: 修复 chunk2.md 的段落换行
  - 文件：output/chunk2.md
  - [注入设计契约的自然语言序列化]

Task 3: 修复 chunk3.md 的段落换行
  - 文件：output/chunk3.md
  - [注入设计契约的自然语言序列化]

Task 4: 修复 chunk4.md 的段落换行
  - 文件：output/chunk4.md
  - [注入设计契约的自然语言序列化]
```

### Step 4：Barrier — 等待所有结果并执行门控

所有子代理返回后，编排者**必须**执行质量门控（非可选）：

```python
# 编排者执行门控检查（伪代码）
expected_files = [
    "output/chunk1_corrected.md",
    "output/chunk2_corrected.md",
    "output/chunk3_corrected.md",
    "output/chunk4_corrected.md",
]
gate_result = run_quality_gate("output/", expected_files, design_contract)

if not gate_result["pass"]:
    # 门控 1 失败 → 重新委派
    # 门控 2 失败 → 升级 prompt 后重新委派
    # 门控 3 失败 → 标记 NEEDS_REVIEW
    for failure in gate_result["failures"]:
        print(f"FAIL: {failure}")
```

### Step 5：写入最终答案

门控全部通过后，将最终结果写入主对话。

## 关键约束

| 步骤 | 必须做 | 禁止做 |
|------|--------|--------|
| Step 1 | 明确选择 pipe/waitAll/loop | 模糊地"先试试看" |
| Step 2 | 完整注入设计契约 | 只描述"做什么"不约束"怎么做" |
| Step 3 | 同消息批量发出所有 task | 逐个串行 spawn（丧失并行收益） |
| Step 4 | 文件系统级门控检查 | 依赖子代理自我报告 |
| Step 5 | 门控通过后才写入最终答案 | 门控前就声称完成 |
