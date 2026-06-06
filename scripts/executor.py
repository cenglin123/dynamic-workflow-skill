#!/usr/bin/env python3
"""CLI 执行器 — 自动调用 opencode/codex 执行 agent 任务。

用法:
  python executor.py execute-step --slug <slug> [--framework <opencode|codex>]
  python executor.py run --slug <slug> [--framework <opencode|codex>]
  python executor.py status --slug <slug>
"""

from __future__ import annotations

import argparse
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 添加当前目录到 path，以便 import scheduler
sys.path.insert(0, str(Path(__file__).parent))

from scheduler import load_state, save_state, get_next_action, apply_result
from adapters import get_adapter


DEFAULT_DIR = ".workflow"
CODEX_SANDBOXES = ["read-only", "workspace-write", "danger-full-access"]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_dir(slug: str, base_dir: str) -> Path:
    return Path(base_dir) / slug / "logs"


def _write_log(slug: str, item: str, stage: str, raw_output: str, base_dir: str) -> None:
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


def _codex_adapter_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "sandbox": getattr(args, "codex_sandbox", "read-only"),
        "output_schema": getattr(args, "codex_output_schema", None),
        "ephemeral": getattr(args, "codex_ephemeral", False),
        "session_id": getattr(args, "codex_session_id", None),
    }


def cmd_execute_step(args: argparse.Namespace) -> dict[str, Any]:
    """处理单个 item 的单个 stage。

    返回 dict 结果（不再调用 sys.exit），调用者可捕获返回值。
    """
    # 1. 读取状态
    state = load_state(args.slug, args.dir)

    # 2. 确定 framework（CLI 参数优先，否则从 state 回退）
    framework = args.framework or state.get("framework")
    if not framework:
        result = {"error": "No framework specified. Use --framework or set during init."}
        print(json.dumps(result), file=sys.stderr)
        return result

    # 3. health check（在 get_next_action 之前，避免 mutate state 后 health_check 失败）
    try:
        options = _codex_adapter_options(args) if framework == "codex" else {}
        adapter = get_adapter(framework, **options)
    except ValueError as e:
        result = {"error": str(e)}
        print(json.dumps(result), file=sys.stderr)
        return result

    if not adapter.health_check():
        result = {"error": f"{framework} CLI not available"}
        print(json.dumps(result), file=sys.stderr)
        return result

    # 4. dry-run 模式（在 get_next_action 之前，避免 mutate state）
    #    dry-run 只显示当前 pending 状态，不调用 get_next_action
    if args.dry_run:
        items = state.get("items", {})
        pending = [
            {"item": k, "status": v.get("status"), "stage": v.get("current_stage")}
            for k, v in items.items()
            if v.get("status") == "pending"
        ]
        result = {
            "dry_run": True,
            "framework": framework,
            "pending_items": pending,
            "next_would_be": pending[0] if pending else None
        }
        print(json.dumps(result, ensure_ascii=False))
        return result

    # 5. 获取下一步 action（health_check 已通过，可以安全 mutate state）
    try:
        action = get_next_action(state)
    except ValueError as e:
        result = {"error": str(e)}
        print(json.dumps(result), file=sys.stderr)
        return result

    # 6. 处理 done/stop/wait 状态
    if action["action"] == "done":
        result = {"status": "done", "summary": action.get("summary")}
        print(json.dumps(result))
        return result
    if action["action"] == "stop":
        result = {"status": "stop", "reason": action.get("reason")}
        print(json.dumps(result))
        return result
    if action["action"] != "spawn":
        result = {"status": "wait", "reason": action.get("reason", "unknown")}
        print(json.dumps(result))
        return result

    # 7. 调用 adapter 执行
    prompt = action["prompt"]
    exec_result = None
    for attempt in range(args.max_retries + 1):
        exec_result = adapter.execute(
            prompt,
            workdir=args.workdir or ".",
            timeout=args.timeout,
            verbose=args.verbose
        )
        if exec_result.success:
            break
        if attempt < args.max_retries:
            print(json.dumps({"event": "retry", "attempt": attempt + 1, "error": exec_result.error}))

    assert exec_result is not None, "adapter.execute never returned"

    # 8. 写日志
    _write_log(args.slug, action["item"], action["stage"], exec_result.raw_output, args.dir)

    # 9. 应用结果（使用 scheduler.py 现有返回格式：item_status）
    try:
        if exec_result.success:
            apply_result(
                state, action["item"], action["stage"],
                result=json.dumps({"summary": exec_result.final_message}),
                tokens=exec_result.tokens_used
            )
        else:
            apply_result(state, action["item"], action["stage"], result=None)
    except ValueError as e:
        out = {"error": str(e)}
        print(json.dumps(out), file=sys.stderr)
        return out

    # 10. 持久化
    save_state(state, args.dir)

    # 11. 输出结果
    output = {
        "status": "completed" if exec_result.success else "failed",
        "item": action["item"],
        "stage": action["stage"]
    }
    if exec_result.metadata:
        output["metadata"] = exec_result.metadata
    if not exec_result.success:
        output["error"] = exec_result.error
    print(json.dumps(output, ensure_ascii=False))
    return output


def cmd_run(args: argparse.Namespace) -> None:
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
            workdir=args.workdir,
            codex_sandbox=getattr(args, "codex_sandbox", "read-only"),
            codex_output_schema=getattr(args, "codex_output_schema", None),
            codex_ephemeral=getattr(args, "codex_ephemeral", False),
            codex_session_id=getattr(args, "codex_session_id", None),
        )

        # 捕获输出
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        ret = cmd_execute_step(step_args)
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        # 优先使用返回值，回退到 stdout 解析
        if ret and isinstance(ret, dict):
            result = ret
        else:
            try:
                result = json.loads(output) if output.strip() else {}
            except json.JSONDecodeError:
                print(output)
                break

        if args.verbose:
            print(output)

        if result.get("error"):
            print(json.dumps({"event": "step_error", "error": result["error"]}))
            break
        if result.get("status") in ("done", "stop"):
            print(json.dumps(result))
            break
        if result.get("status") == "failed":
            print(json.dumps({"event": "item_failed", "item": result.get("item"), "stage": result.get("stage"), "error": result.get("error")}))

    print(json.dumps({"event": "run_complete", "rounds": round_count}))


def cmd_status(args: argparse.Namespace) -> None:
    """显示当前状态（委托 scheduler）。"""
    from scheduler import cmd_status as scheduler_status
    scheduler_status(args)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="executor.py",
        description="CLI 执行器 — 自动调用 opencode/codex 执行 agent 任务")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="状态文件目录")
    parser.add_argument("--timeout", type=int, default=300, help="CLI 超时（秒）")
    parser.add_argument("--max-retries", type=int, default=2, help="失败重试次数")
    parser.add_argument("--verbose", action="store_true", help="实时显示 CLI 输出")
    parser.add_argument("--workdir", default=".", help="agent 工作目录")
    parser.add_argument(
        "--codex-sandbox",
        choices=CODEX_SANDBOXES,
        default="read-only",
        help="Codex sandbox（默认 read-only）",
    )
    parser.add_argument("--codex-output-schema", help="Codex 最终输出 JSON Schema 文件")
    parser.add_argument(
        "--codex-ephemeral",
        action="store_true",
        help="Codex 一次性会话，不持久化 session",
    )
    parser.add_argument(
        "--codex-session-id",
        help="恢复指定 Codex thread/session；不能与 --codex-ephemeral 同用",
    )

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
    if args.codex_ephemeral and args.codex_session_id:
        parser.error("codex ephemeral mode cannot resume a session")
    if args.command == "run" and args.codex_session_id:
        parser.error("codex session resume is only supported with execute-step")

    if args.command == "execute-step":
        cmd_execute_step(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
