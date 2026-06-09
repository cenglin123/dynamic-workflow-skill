# 子代理约束注入协议

> 本文件从 SKILL.md 拆分而来，包含约束注入的完整协议、能力边界和验证机制。

## 约束的三层结构

```
设计契约（定义层）
  ├── objective / constraints / allowed_tools / forbidden_tools
  ├── forbidden_patterns / anti_patterns / execution_path
  ├── mandatory_terms / term_verification
  └── evidence_template

注入协议（传递层）
  ├── design_constraints → 来自设计契约的不可变约束
  ├── context_brief → 精简上下文（避免信息过载）
  ├── residual_constraints → 顶层决策的残差（不可变，每步携带）
  └── propagation_rules → 字段继承规则

子代理 prompt（接收层）
  └── 从注入协议序列化为自然语言文本
```

## 注入协议模板

编排者 → 子代理的委派应包含以下信息：

```json
{
  "design_constraints": {
    "tool_regime": "Edit only",
    "methodology": "semantic paragraph merge",
    "forbidden": ["scripts", "sed", "regex-only"],
    "fallback_directive": "read more context, then retry"
  },
  "context_brief": {
    "file_path": "...",
    "line_range": "1001-2000",
    "special_elements": ["math blocks", "headers", "comments"]
  },
  "residual_constraints": {
    "tool_regime": "Edit 工具逐行修复，禁止编写任何脚本",
    "methodology": "按段落语义边界合并，非简单正则替换",
    "forbidden_actions": [
      "创建 .py / .ps1 / .sh 文件",
      "使用 Bash 执行 sed / awk / python 命令",
      "使用正则表达式批量替换"
    ],
    "fallback_directive": "如果 Edit 工具失败，扩大读取范围后重试 Edit；绝对不要切换到脚本方案"
  },
  "propagation_rules": {
    "inherit_from_parent": ["domain", "budget", "quality_mode"],
    "override_per_stage": ["acceptance_criteria", "anti_patterns"],
    "immutable": ["design_constraints", "residual_constraints"]
  }
}
```

**字段说明**：
- `design_constraints`：来自设计契约的不可变约束（工具体制、方法论、禁止项）
- `context_brief`：精简的上下文（避免信息过载）
- `residual_constraints`：顶层决策的残差约束，子代理在执行过程中每一步都应携带。与 design_constraints 的区别：design_constraints 描述"不能做什么"，residual_constraints 描述"必须怎么做"
- `propagation_rules`：字段继承规则（inherit/override/immutable）

## 传递语义

- **注入时机**：在 spawn 子代理时，将约束注入到子代理的 prompt 中
- **不可变性**：子代理不能修改或忽略 `design_constraints` 和 `residual_constraints`
- **每步携带**：子代理在执行过程中每一步都应遵守残差约束
- **优先级**：残差约束优先于子代理的自主判断
- **术语约束**：mandatory_terms 中的术语必须使用标准写法，禁止子代理自行推断

## Shannon 案例完整注入示例

注入到子代理 prompt 的文本：
```
## 不可变约束（必须遵守）
- [强制] 使用 Edit 工具逐行修复，禁止编写任何脚本
- [强制] 使用语义判断 + 精确编辑，禁止使用 sed/awk
- [强制] 遇到不确定时读取更多上下文，不要猜测

## 术语约束
- DeepSeek（不是 迪布西克）
- Claude（Anthropic 公司）
- Vibe Coding（不是 Web Coding）
- 不确定的术语保留原文并标记 [UNCERTAIN]

## 执行证据要求
完成任务后，必须返回以下信息：
- 写入/修改的文件完整路径列表
- 每个文件的字节大小
- 存在不确定性的标记（如有）
```

## Prompt 注入的能力边界与注入后验证

> **核心认知**：当前 SKILL 的约束传递完全依赖 prompt 注入（自然语言序列化），无框架级强制执行。编排者必须理解这一能力边界，并通过"注入后验证"闭环弥补。

**能力边界声明**：

| 能力 | Prompt 注入能做到 | Prompt 注入做不到 |
|------|-------------------|-------------------|
| 工具约束 | 声明"禁止使用 Bash" | **无法物理阻止**子代理调用 Bash |
| 文件约束 | 声明"禁止创建 .py 文件" | **无法阻止**子代理在文件系统创建 .py |
| 术语约束 | 声明"使用 DeepSeek 不是迪布西克" | **无法阻止**子代理使用错误术语 |
| 输出格式 | 声明 evidence_template 要求 | **无法强制**子代理按模板返回 |

**后果**：子代理可能"声称遵守约束但实际违反"（Shannon 案例 Batch 3 的虚假成功）。仅靠 prompt 注入无法消除此风险。

**注入后验证闭环（必做）**：

```
注入约束 → 子代理执行 → 子代理返回结果
                              ↓
                    编排者执行注入后验证（非可选）
                              ↓
               ┌──────────────┼──────────────┐
               ↓              ↓              ↓
         全部验证通过    部分验证失败    全部验证失败
         → 接受结果     → 升级 prompt     → 重新委派
                         重新委派         （同 prompt）
```

**验证检查项**（编排者在子代理返回后立即执行）：

```python
def post_injection_verify(subagent_output, design_contract):
    """
    注入后验证：检查子代理是否真正遵守了注入的约束。
    编排者必须在子代理返回后调用此函数。
    """
    violations = []

    # 1. 证据完整性：子代理是否按 evidence_template 返回了结构化数据
    required_keys = ["files_written", "files_modified", "file_sizes"]
    for key in required_keys:
        if key not in subagent_output:
            violations.append(f"MISSING_EVIDENCE: {key} not provided")

    # 2. 文件存在性：声称写入的文件是否实际存在
    for f in subagent_output.get("files_written", []):
        if not os.path.exists(f):
            violations.append(f"PHANTOM_FILE: {f} claimed but not found")

    # 3. 工具合规：检查子代理是否使用了 forbidden_tools
    # （需要框架支持 tool_use 日志，否则跳过）
    if "tool_usage_log" in subagent_output:
        for tool in design_contract.get("forbidden_tools", []):
            if tool in subagent_output["tool_usage_log"]:
                violations.append(f"FORBIDDEN_TOOL_USED: {tool}")

    # 4. 术语合规：检查 mandatory_terms 是否被遵守
    for f in subagent_output.get("files_written", []):
        if os.path.exists(f):
            content = open(f, 'r', encoding='utf-8').read()
            for term, standard in design_contract.get("mandatory_terms", {}).items():
                if term in content and standard not in content:
                    violations.append(f"TERM_VIOLATION: {f} uses '{term}' instead of '{standard}'")

    return {"pass": len(violations) == 0, "violations": violations}
```

**框架级验证的演进方向**（长期）：

当前 SKILL 的约束传递是 prompt 级的。未来可探索：
1. **工具级拦截**：框架在 spawn 时注入 forbidden_tools 列表，runtime 物理阻止调用
2. **文件级沙箱**：子代理只能写入指定目录，forbidden_patterns 由 runtime 过滤
3. **输出 schema 强制**：子代理返回必须符合 evidence_template 的 JSON schema，否则 runtime 拒绝

> 这些是框架能力层面的增强，超出当前 SKILL 的 scope。当前 SKILL 通过 prompt 注入 + 门控脚本的组合来逼近同等效果。
