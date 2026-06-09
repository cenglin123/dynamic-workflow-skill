# 质量门控脚本模板

> 本文件从 SKILL.md 拆分而来，包含门控脚本模板和内置检查项示例。

## run_quality_gate 脚本模板

编排者可直接复用：

```python
import os, re, json

def run_quality_gate(output_dir, expected_files, design_contract):
    """
    编排者在子代理完成后调用此脚本。
    返回 {"pass": bool, "failures": [...]}
    """
    results = {"pass": True, "failures": []}

    # 门控 1：确定性验证 — 文件存在性与非空
    for f in expected_files:
        path = os.path.join(output_dir, f)
        if not os.path.exists(path):
            results["failures"].append(f"MISSING: {f}")
            results["pass"] = False
        elif os.path.getsize(path) == 0:
            results["failures"].append(f"EMPTY: {f}")
            results["pass"] = False

    # 门控 2：一致性检查 — forbidden_patterns
    for pattern in design_contract.get("forbidden_patterns", []):
        for f in os.listdir(output_dir):
            if re.search(pattern, f):
                results["failures"].append(f"FORBIDDEN_FILE: {f} matches {pattern}")
                results["pass"] = False

    # 门控 3：质量检查 — 内容抽样
    for f in expected_files[:3]:  # 抽样前 3 个
        path = os.path.join(output_dir, f)
        if os.path.exists(path):
            content = open(path, 'r', encoding='utf-8').read()
            if re.search(r'[a-z]{3,}[A-Z][a-z]{3,}', content):
                results["failures"].append(f"MERGE_ERROR: {f} contains camelCase merge artifact")
                results["pass"] = False

    return results
```

## 内置检查项示例

基于 Shannon 案例：

- 脚本残留：检查结果中是否包含 "script"、".py"、".ps1"、".sh"
- 合并错误：检查结果中是否包含 `[a-z]{3,}[A-Z][a-z]{3,}` 模式
- 格式破坏：检查结果中是否丢失了 `$$`（公式）或 `#`（标题）
