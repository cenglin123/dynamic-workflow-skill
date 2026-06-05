#!/usr/bin/env python3
"""CLI 执行器 — 自动调用 opencode/codex 执行 agent 任务。

用法:
  python executor.py execute-step --slug <slug> [--framework <opencode|codex>]
  python executor.py run --slug <slug> [--framework <opencode|codex>]
  python executor.py status --slug <slug>
"""

import argparse
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# 添加当前目录到 path，以便 import scheduler
sys.path.insert(0, str(Path(__file__).parent))

from scheduler import load_state, save_state, get_next_action, apply_result
from adapters import get_adapter


DEFAULT_DIR = ".workflow"


def _timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_dir(slug, base_dir):
    return Path(base_dir) / slug / "logs"


def _write_log(slug, item, stage, raw_output, base_dir):
    """写入完整 CLI 输出日志。"""
    log_dir = _log_dir(slug, base_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{item}-{stage}.jsonl"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": _timestamp(),
            "event": "cli_output",
            "output": raw_output
        }, ensure_ascii=False) + "\n")


def cmd_execute_step(args):
    """处理单个 item 的单个 stage。"""
    # [Round 2 fix #2] 先读取 state，再确定 framework，再 get_adapter
    # 1. 读取状态
    state = load_state(args.slug, args.dir)

    # 2. 确定 framework（CLI 参数优先，否则从 state 回退）
    framework = args.framework or state.get("framework")
    if not framework:
        print(json.dumps({"error": "No framework specified. Use --framework or set during init."}), file=sys.stderr)
        sys.exit(1)

    # 3. health check（此时 framework 已确定，不会传 None）
    try:
        adapter = get_adapter(framework)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    if not adapter.health_check():
        print(json.dumps({"error": f"{framework} CLI not available"}), file=sys.stderr)
        sys.exit(1)

    # 4. 获取下一步 action
    try:
        action = get_next_action(state)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    if action["action"] == "done":
        print(json.dumps({"status": "done", "summary": action.get("summary")}))
        return
    if action["action"] == "stop":
        print(json.dumps({"status": "stop", "reason": action.get("reason")}))
        return
    if action["action"] != "spawn":
        print(json.dumps({"status": "wait", "reason": action.get("reason", "unknown")}))
        return

    # dry-run 模式
    if args.dry_run:
        print(json.dumps({
            "action": "dry_run",
            "item": action["item"],
            "stage": action["stage"],
            "framework": framework,
            "prompt_preview": action["prompt"][:200] + "..." if len(action["prompt"]) > 200 else action["prompt"]
        }, ensure_ascii=False))
        return

    # 5. 调用 adapter 执行
    prompt = action["prompt"]
    result = None
    for attempt in range(args.max_retries + 1):
        result = adapter.execute(
            prompt,
            workdir=args.workdir or ".",
            timeout=args.timeout,
            verbose=args.verbose
        )
        if result.success:
            break
        if attempt < args.max_retries:
            print(json.dumps({"event": "retry", "attempt": attempt + 1, "error": result.error}))

    # 6. 写日志
    _write_log(args.slug, action["item"], action["stage"], result.raw_output, args.dir)

    # 7. 应用结果（使用 scheduler.py 现有返回格式：item_status）
    try:
        if result.success:
            apply_result(
                state, action["item"], action["stage"],
                result=json.dumps({"summary": result.final_message}),
                tokens=result.tokens_used
            )
        else:
            apply_result(state, action["item"], action["stage"], result=None)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    # 8. 持久化
    save_state(state, args.dir)

    # 9. 输出结果
    output = {
        "status": "completed" if result.success else "failed",
        "item": action["item"],
        "stage": action["stage"]
    }
    if not result.success:
        output["error"] = result.error
    print(json.dumps(output, ensure_ascii=False))


def cmd_run(args):
    """全自动循环：重复 execute-step 直到 done/stop。"""
    round_count = 0
    while True:
        round_count += 1
        if args.max_rounds and round_count > args.max_rounds:
            print(json.dumps({"event": "max_rounds_reached", "rounds": round_count - 1}))
            break

        # 模拟 execute-step 的参数
        step_args = argparse.Namespace(
            slug=args.slug,
            framework=args.framework,
            dir=args.dir,
            timeout=args.timeout,
            max_retries=args.max_retries,
            verbose=args.verbose,
            dry_run=False,
            workdir=args.workdir
        )

        # 捕获输出
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        cmd_execute_step(step_args)
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        # 解析结果
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            print(output)
            break

        if args.verbose:
            print(output)

        if result.get("status") in ("done", "stop"):
            print(output)
            break
        if result.get("status") == "failed":
            print(json.dumps({"event": "item_failed", "item": result.get("item"), "stage": result.get("stage"), "error": result.get("error")}))

    print(json.dumps({"event": "run_complete", "rounds": round_count}))


def cmd_status(args):
    """显示当前状态（委托 scheduler）。"""
    from scheduler import cmd_status as scheduler_status
    scheduler_status(args)


def main():
    parser = argparse.ArgumentParser(
        prog="executor.py",
        description="CLI 执行器 — 自动调用 opencode/codex 执行 agent 任务")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="状态文件目录")
    parser.add_argument("--timeout", type=int, default=300, help="CLI 超时（秒）")
    parser.add_argument("--max-retries", type=int, default=2, help="失败重试次数")
    parser.add_argument("--verbose", action="store_true", help="实时显示 CLI 输出")
    parser.add_argument("--workdir", default=".", help="agent 工作目录")

    sub = parser.add_subparsers(dest="command", required=True)

    # execute-step
    p_step = sub.add_parser("execute-step", help="处理单个 item 的单个 stage")
    p_step.add_argument("--slug", required=True)
    p_step.add_argument("--framework", choices=["opencode", "codex"])
    p_step.add_argument("--dry-run", action="store_true", help="只显示会执行什么")

    # run
    p_run = sub.add_parser("run", help="全自动循环")
    p_run.add_argument("--slug", required=True)
    p_run.add_argument("--framework", choices=["opencode", "codex"])
    p_run.add_argument("--max-rounds", type=int, help="最大轮次")

    # status
    p_status = sub.add_parser("status", help="显示当前状态")
    p_status.add_argument("--slug", required=True)

    args = parser.parse_args()

    if args.command == "execute-step":
        cmd_execute_step(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
