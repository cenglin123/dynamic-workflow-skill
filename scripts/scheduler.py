#!/usr/bin/env python3
"""编排决策状态机 — Dynamic Workflow SKILL 可选辅助工具。

非 CC 框架用户（opencode/codex）没有原生 workflow runtime。
scheduler.py 将编排决策（下一步 spawn 什么、何时 barrier、何时推进 stage）
从 Orchestrator 的自然语言推理转移到代码中，使 Orchestrator 退化为 thin executor。

CLI 用法:
  python scheduler.py init --slug <slug> --mode pipe|waitall|loop ...
  python scheduler.py dispatch --slug <slug>
  python scheduler.py complete --slug <slug> --item <id> --stage <name> --result '<json>'
  python scheduler.py barrier-done --slug <slug>
  python scheduler.py loop-feedback --slug <slug> --new-count <N>
  python scheduler.py status --slug <slug>
  python scheduler.py budget --slug <slug> [--spend <tokens>]

Library API (importable):
  from scheduler import load_state, save_state, get_next_action, apply_result
  state = load_state(slug, dir)
  action = get_next_action(state)       # mutates state, returns action dict
  result = apply_result(state, item, stage, result=..., tokens=...)  # mutates state
  save_state(state, dir)                # caller persists
"""

from __future__ import annotations

# ==== imports ====

import argparse
import json
import re
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ==== constants ====

DEFAULT_DIR = ".workflow"
ESTIMATED_TOKENS_PER_AGENT = 15000


class StateError(Exception):
    """Raised by load_state/save_state on I/O or data errors."""

    def __init__(self, error_dict: dict[str, Any]) -> None:
        self.error_dict = error_dict
        super().__init__(json.dumps(error_dict))


# ==== state i/o ====

def _state_path(slug: str, directory: str) -> Path:
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        raise StateError({"error": "invalid_slug", "detail": f"slug '{slug}' contains invalid characters"})
    return Path(directory) / slug / "state.json"


def load_state(slug: str, directory: str = DEFAULT_DIR) -> dict[str, Any]:
    path = _state_path(slug, directory)
    if not path.exists():
        raise StateError({"error": "not_found", "slug": slug})
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise StateError({"error": "invalid_state", "detail": str(e)})
    REQUIRED = {"slug", "mode", "config", "items", "budget", "phase"}
    if not REQUIRED.issubset(state.keys()):
        missing = REQUIRED - state.keys()
        raise StateError({"error": "invalid_state", "detail": f"missing keys: {missing}"})
    return state


def save_state(state: dict[str, Any], directory: str = DEFAULT_DIR) -> None:
    path = _state_path(state["slug"], directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        raise StateError({"error": "write_failed", "detail": str(e)})


def _load_or_exit(slug: str, directory: str) -> dict[str, Any]:
    try:
        return load_state(slug, directory)
    except StateError as e:
        print(json.dumps(e.error_dict), file=sys.stderr)
        sys.exit(1)


def _save_or_exit(state: dict[str, Any], directory: str) -> None:
    try:
        save_state(state, directory)
    except StateError as e:
        print(json.dumps(e.error_dict), file=sys.stderr)
        sys.exit(1)


# ==== helpers ====

def _item_key(item_id: str, stage_idx: int) -> str:
    return f"{item_id}@{stage_idx}"


def _budget_allows(state: dict[str, Any]) -> bool:
    """Check if budget hard cap allows another spawn."""
    total = state["config"]["budget_total"]
    if total is None:
        return True
    return state["budget"]["spent"] < total


def _render_prompt(
    template: str,
    state: dict[str, Any],
    item: str | None = None,
    stage: str | None = None,
    batch_idx: int | None = None,
) -> str:
    ctx = state.get("config", {}).get("context", {})
    placeholders = {
        "domain": str(ctx.get("domain", "")),
        "seen": json.dumps(ctx.get("seen", []), ensure_ascii=False),
        "context": json.dumps(ctx, ensure_ascii=False),
        "round": str(state.get("loop", {}).get("round", 0)),
    }
    if item is not None:
        placeholders["item"] = str(item)
    if stage is not None:
        placeholders["stage"] = str(stage)
    if batch_idx is not None:
        placeholders["batch_idx"] = str(batch_idx)

    def replacer(m):
        key = m.group(1)
        val = placeholders.get(key)
        return val if val is not None else m.group(0)

    return re.sub(r'\{\{(\w+)\}\}', replacer, template)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ==== init ====

def cmd_init(args: argparse.Namespace) -> None:
    directory = args.dir or DEFAULT_DIR
    slug = args.slug
    path = _state_path(slug, directory)
    if path.exists():
        print(json.dumps({"error": "already_exists", "slug": slug}), file=sys.stderr)
        sys.exit(1)

    items = [i.strip() for i in args.items.split(",") if i.strip()]
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    if not items:
        print(json.dumps({"error": "no_items"}), file=sys.stderr)
        sys.exit(1)
    if not stages:
        print(json.dumps({"error": "no_stages"}), file=sys.stderr)
        sys.exit(1)

    for stage in stages:
        if "{{" in stage or "}}" in stage:
            print(json.dumps({"error": "invalid_stage_name", "detail": f"stage '{stage}' contains template markers"}), file=sys.stderr)
            sys.exit(1)
    if len(stages) != len(set(stages)):
        print(json.dumps({"error": "duplicate_stages"}), file=sys.stderr)
        sys.exit(1)

    reserved_names = {"_finder"}
    for item in items:
        if "{{" in item or "}}" in item:
            print(json.dumps({"error": "invalid_item_name", "detail": f"item '{item}' contains template markers"}), file=sys.stderr)
            sys.exit(1)
        if item in reserved_names:
            print(json.dumps({"error": "invalid_item_name", "detail": f"item '{item}' is a reserved name"}), file=sys.stderr)
            sys.exit(1)
    if len(items) != len(set(items)):
        print(json.dumps({"error": "duplicate_items"}), file=sys.stderr)
        sys.exit(1)

    # load prompt templates if provided
    prompt_templates = {}
    if args.prompt_file:
        try:
            prompt_templates = json.loads(Path(args.prompt_file).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(json.dumps({"error": "invalid_prompt_file", "detail": str(e)}), file=sys.stderr)
            sys.exit(1)

    items_dict = {}
    for name in items:
        items_dict[name] = {
            "stage_idx": -1,
            "status": "pending",
            "retry_count": 0,
            "dispatched_at": None,
            "attempts": [],
            "results": [],
            "error": None,
        }

    state = {
        "slug": slug,
        "mode": args.mode,
        "framework": getattr(args, 'framework', None),
        "created_at": _timestamp(),
        "updated_at": _timestamp(),
        "config": {
            "items": items,
            "stages": stages,
            "budget_total": args.budget,
            "max_concurrency": args.concurrency,
            "pipe": {},
            "waitall": {"fail_fast": False},
            "loop": {"dry_threshold": args.dry_threshold, "max_rounds": args.max_rounds},
            "max_retries": args.max_retries,
            "context": {"domain": "", "seen": []},
        },
        "prompt_templates": prompt_templates,
        "budget": {"spent": 0},
        "items": items_dict,
        "loop": {"round": 0, "dry_counter": 0, "seen_count": 0, "feedback_pending": False},
        "waitall": {"active": True, "batch_idx": 0, "completed": [], "barrier_pending_ack": False},
        "phase": "running",
    }

    _save_or_exit(state, directory)
    print(json.dumps({"status": "initialized", "slug": slug, "mode": args.mode,
                      "framework": args.framework, "items": len(items), "stages": len(stages)}))


# ==== library API (importable, no side effects) ====

def get_next_action(state: dict[str, Any]) -> dict[str, Any]:
    """Pure logic: determine next action from state. Mutates state in-place (marks items running).
    Returns action dict. Caller is responsible for save_state."""
    mode = state["mode"]
    if mode == "pipe":
        return dispatch_pipe(state)
    elif mode == "waitall":
        return dispatch_waitall(state)
    elif mode == "loop":
        return dispatch_loop(state)
    else:
        raise ValueError(f"unknown_mode: {mode}")


def apply_result(
    state: dict[str, Any],
    item: str,
    stage: str,
    result: str | None = None,
    tokens: int | None = None,
    retry: bool = False,
    context: str | None = None,
) -> dict[str, Any]:
    """Pure logic: apply a completion result to state. Mutates state in-place.
    Caller is responsible for save_state."""
    items_dict = state["items"]

    if item not in items_dict:
        raise ValueError(f"invalid_item: {item}")

    it = items_dict[item]

    # protocol guard: item must be in "running" status
    if it["status"] != "running":
        stages_list = state["config"]["stages"]
        expected = stages_list[it["stage_idx"]] if 0 <= it["stage_idx"] < len(stages_list) else "N/A"
        raise ValueError(f"protocol_violation: item '{item}' status is '{it['status']}', "
                         f"expected stage '{expected}', called stage '{stage}'")

    # protocol guard: completed stage must match item's current stage
    stages_list = state["config"]["stages"]
    if 0 <= it["stage_idx"] < len(stages_list):
        current_stage = stages_list[it["stage_idx"]]
        if stage != current_stage:
            raise ValueError(f"stage_mismatch: item '{item}' at stage '{current_stage}', "
                             f"called stage '{stage}'")

    # accept result
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except (json.JSONDecodeError, TypeError):
        parsed = result

    if retry:
        it["attempts"].append({"result": parsed, "tokens": tokens or 0, "timestamp": _timestamp()})
        it["retry_count"] += 1
        if it["retry_count"] >= state["config"]["max_retries"]:
            it["status"] = "failed"
            it["error"] = "max_retries_exceeded"
        else:
            it["status"] = "pending"
    else:
        it["results"].append(parsed)
        it["attempts"].append({"result": parsed, "tokens": tokens or 0, "timestamp": _timestamp()})
        if parsed is None:
            it["status"] = "failed"
            it["error"] = "null_result"
        else:
            it["status"] = "done"
        it["retry_count"] = 0

    it["dispatched_at"] = None

    # budget
    if not retry:
        tok = tokens or ESTIMATED_TOKENS_PER_AGENT
        state["budget"]["spent"] += tok

    # loop mode: require loop-feedback after finder completes
    if state["mode"] == "loop" and item == "_finder" and not retry:
        state["loop"]["feedback_pending"] = True

    # merge context if provided
    if context is not None:
        try:
            ctx_update = json.loads(context) if isinstance(context, str) else context
            ctx = state["config"].setdefault("context", {})
            ctx.update(ctx_update)
        except (json.JSONDecodeError, TypeError):
            pass

    return {"item": item, "stage": stage, "item_status": it["status"]}


# ==== dispatch CLI ====

def cmd_dispatch(args: argparse.Namespace) -> None:
    directory = args.dir or DEFAULT_DIR
    state = _load_or_exit(args.slug, directory)

    try:
        result = get_next_action(state)
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    _save_or_exit(state, directory)
    print(json.dumps(result, ensure_ascii=False))


def dispatch_pipe(state: dict[str, Any]) -> dict[str, Any]:
    config = state["config"]
    items_dict = state["items"]
    max_conc = config["max_concurrency"]
    stages = config["stages"]
    templates = state.get("prompt_templates", {})

    if not _budget_allows(state):
        state["phase"] = "stopped"
        return {"action": "stop", "reason": "budget_exhausted",
                "spent": state["budget"]["spent"], "total": state["config"]["budget_total"]}

    # count currently running items
    running = sum(1 for it in items_dict.values() if it["status"] == "running")
    if running >= max_conc:
        return {"action": "wait", "reason": "concurrency_limit", "running": running}

    # first pass: items done with current stage, advance to next stage immediately
    # (pipe semantics: "A stage 2 starts as soon as A stage 1 completes")
    for name in config["items"]:
        it = items_dict[name]
        if it["status"] == "done" and it["stage_idx"] < len(stages) - 1:
            next_idx = it["stage_idx"] + 1
            it["stage_idx"] = next_idx
            it["status"] = "pending"
            return _spawn_item(state, name, next_idx, templates)

    # second pass: items not yet started (stage_idx == -1, pending)
    for name in config["items"]:
        it = items_dict[name]
        if it["stage_idx"] == -1 and it["status"] == "pending":
            return _spawn_item(state, name, 0, templates)

    # third pass: retried items (pending + stage_idx >= 0, i.e., not brand new)
    for name in config["items"]:
        it = items_dict[name]
        if it["status"] == "pending" and it["stage_idx"] >= 0:
            return _spawn_item(state, name, it["stage_idx"], templates)

    # check if done
    all_terminal = all(
        (it["status"] == "done" and it["stage_idx"] >= len(stages) - 1)
        or (it["status"] == "failed" and it["retry_count"] >= config["max_retries"])
        for it in items_dict.values()
    )
    if all_terminal:
        return {"action": "done", "summary": _summarize(state)}
    return {"action": "wait", "reason": "all_items_blocked"}


def dispatch_waitall(state: dict[str, Any]) -> dict[str, Any]:
    config = state["config"]
    items_dict = state["items"]
    max_conc = config["max_concurrency"]
    stages = config["stages"]
    ws = state["waitall"]
    templates = state.get("prompt_templates", {})
    batch_idx = ws["batch_idx"]

    # barrier must be ack'd before continuing
    if ws.get("barrier_pending_ack"):
        return {"action": "barrier_pending_ack", "hint": "必须先调用 barrier-done 再继续 dispatch"}

    # past the last stage?
    if batch_idx >= len(stages):
        return {"action": "done", "summary": _summarize(state)}

    # count running items in this batch
    running = sum(
        1 for it in items_dict.values()
        if it["status"] == "running" and it["stage_idx"] == batch_idx
    )
    if running >= max_conc:
        return {"action": "wait", "reason": "concurrency_limit", "running": running}

    # find a pending item in the current batch
    for name in config["items"]:
        it = items_dict[name]
        # items with stage_idx == -1 haven't been assigned to a batch yet
        if it["stage_idx"] == -1 and it["status"] == "pending":
            it["stage_idx"] = batch_idx
        if it["stage_idx"] == batch_idx and it["status"] == "pending":
            return _spawn_item(state, name, batch_idx, templates)

    # also check: items that failed with retries remaining
    for name in config["items"]:
        it = items_dict[name]
        if it["stage_idx"] == -1 and it["status"] == "failed":
            it["stage_idx"] = batch_idx
        if (it["stage_idx"] == batch_idx and it["status"] == "failed"
                and it["retry_count"] < config["max_retries"]):
            it["status"] = "pending"
            return _spawn_item(state, name, batch_idx, templates)

    # all items in this batch resolved?
    all_resolved = all(
        items_dict[n]["status"] in ("done", "failed")
        for n in config["items"]
        if items_dict[n]["stage_idx"] == batch_idx
    )
    if all_resolved:
        # internal barrier processing
        return _process_barrier(state)

    return {"action": "wait", "reason": "all_items_blocked"}


def _process_barrier(state: dict[str, Any]) -> dict[str, Any]:
    """Internal barrier processing: aggregate, gate, dedup, merge context, notify."""
    config = state["config"]
    items_dict = state["items"]
    ws = state["waitall"]
    batch_idx = ws["batch_idx"]
    stages = config["stages"]
    stage_name = stages[batch_idx]

    # 1. Aggregate
    batch_results = {}
    any_failed = False
    for name in config["items"]:
        it = items_dict[name]
        if it["stage_idx"] == batch_idx:
            batch_results[name] = {
                "status": it["status"],
                "result": it["results"][-1] if it["results"] else None,
                "error": it["error"],
            }
            if it["status"] == "failed":
                any_failed = True

    # 2. Gate
    fail_fast = config.get("waitall", {}).get("fail_fast", False)
    if any_failed and fail_fast:
        state["phase"] = "stopped"
        return {"action": "stop", "reason": "barrier_gate_failed",
                "stage": stage_name, "batch_idx": batch_idx}

    # 3. Dedup/Merge — collect all results as context for next batch
    merged_context = {}
    for name, br in batch_results.items():
        if br["status"] == "done" and br["result"] is not None:
            merged_context[name] = br["result"]

    # 4. Context-passing — merge into config.context for next batch templates
    ctx = config.setdefault("context", {})
    ctx[f"batch_{batch_idx}_{stage_name}"] = merged_context

    # Reset failed items' status for next batch (fail_fast=false path)
    # Only promote failed items that haven't exhausted retries
    for name in config["items"]:
        it = items_dict[name]
        if it["stage_idx"] == batch_idx and it["status"] == "failed":
            if it["retry_count"] < config["max_retries"]:
                it["stage_idx"] += 1
                it["status"] = "pending"
                it["retry_count"] = 0
                it["error"] = None

    # Mark done items for next batch
    for name in config["items"]:
        it = items_dict[name]
        if it["stage_idx"] == batch_idx and it["status"] == "done":
            it["stage_idx"] += 1
            it["status"] = "pending"

    ws["completed"].append(batch_idx)
    ws["batch_idx"] = batch_idx + 1
    ws["barrier_pending_ack"] = True  # requires barrier-done before next dispatch

    # 5. Notify
    summary = {
        "stage": stage_name,
        "batch_idx": batch_idx,
        "total": len(batch_results),
        "done": sum(1 for br in batch_results.values() if br["status"] == "done"),
        "failed": sum(1 for br in batch_results.values() if br["status"] == "failed"),
        "next_stage": stages[batch_idx + 1] if batch_idx + 1 < len(stages) else None,
    }
    return {"action": "barrier", "summary": summary}


def dispatch_loop(state: dict[str, Any]) -> dict[str, Any]:
    config = state["config"]
    loop_cfg = config["loop"]
    loop_st = state["loop"]
    templates = state.get("prompt_templates", {})

    # loop-feedback must be called after finder completes
    if loop_st.get("feedback_pending"):
        return {"action": "loop_feedback_pending",
                "hint": "finder 已完成，必须先调用 loop-feedback 再继续 dispatch"}

    # are we done?
    if loop_st["dry_counter"] >= loop_cfg["dry_threshold"]:
        return {"action": "done", "summary": _summarize(state)}
    if loop_st["round"] >= loop_cfg["max_rounds"]:
        state["phase"] = "stopped"
        return {"action": "stop", "reason": "max_rounds_reached",
                "round": loop_st["round"]}

    # is there a running finder that hasn't completed yet?
    # we use a special item to track the finder
    finder = state["items"].get("_finder")
    if finder and finder["status"] == "running":
        return {"action": "wait", "reason": "finder_running"}

    # ensure _finder item exists
    if "_finder" not in state["items"]:
        state["items"]["_finder"] = {
            "stage_idx": 0, "status": "pending", "retry_count": 0,
            "dispatched_at": None, "attempts": [], "results": [], "error": None,
        }

    finder = state["items"]["_finder"]
    if finder["status"] == "failed":
        state["phase"] = "stopped"
        return {"action": "stop", "reason": "finder_failed",
                "round": loop_st["round"]}
    if finder["status"] == "pending":
        loop_st["round"] += 1
        finder["stage_idx"] = 0
        return _spawn_item(state, "_finder", 0, templates, is_loop_finder=True)

    return {"action": "wait", "reason": "loop_intermediate"}


def _spawn_item(
    state: dict[str, Any],
    item_name: str,
    stage_idx: int,
    templates: dict[str, str],
    is_loop_finder: bool = False,
) -> dict[str, Any]:
    """Mark item as running and return spawn action. Returns stop action if budget exceeded."""
    # budget hard cap: only blocks new spawns, not done/barrier signals
    if not _budget_allows(state):
        state["phase"] = "stopped"
        return {"action": "stop", "reason": "budget_exhausted",
                "spent": state["budget"]["spent"], "total": state["config"]["budget_total"]}

    it = state["items"][item_name]
    it["status"] = "running"
    it["dispatched_at"] = _timestamp()
    it["stage_idx"] = stage_idx

    stages = state["config"]["stages"]
    if stage_idx >= len(stages):
        raise ValueError(f"stage_idx {stage_idx} out of range (max {len(stages)-1})")
    stage_name = stages[stage_idx]
    template_key = state["mode"]
    if is_loop_finder:
        template_key = "loop_finder"

    # build prompt
    tpl = templates.get(template_key, "")
    if tpl:
        prompt = _render_prompt(
            tpl, state,
            item=item_name if not is_loop_finder else None,
            stage=stage_name if not is_loop_finder else None,
            batch_idx=state["waitall"]["batch_idx"] if state["mode"] == "waitall" else None,
        )
    else:
        prompt = None  # Orchestrator must provide

    action = {
        "action": "spawn",
        "item": item_name,
        "stage": stage_name,
        "stage_idx": stage_idx,
        "prompt": prompt,
    }
    if is_loop_finder:
        action["round"] = state["loop"]["round"]
    return action


# ==== complete CLI ====

def cmd_complete(args: argparse.Namespace) -> None:
    directory = args.dir or DEFAULT_DIR
    state = _load_or_exit(args.slug, directory)

    try:
        result = apply_result(
            state, args.item, args.stage,
            result=args.result, tokens=args.tokens,
            retry=args.retry, context=args.context,
        )
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    _save_or_exit(state, directory)
    print(json.dumps({"status": "completed", **result}))


# ==== barrier-done ====

def cmd_barrier_done(args: argparse.Namespace) -> None:
    directory = args.dir or DEFAULT_DIR
    state = _load_or_exit(args.slug, directory)

    if state["mode"] != "waitall":
        print(json.dumps({"error": "not_waitall_mode", "mode": state["mode"]}), file=sys.stderr)
        sys.exit(1)

    if not state["waitall"].get("barrier_pending_ack"):
        print(json.dumps({"error": "protocol_violation",
                          "hint": "当前无 pending barrier，无需调用 barrier-done"}), file=sys.stderr)
        sys.exit(1)

    if args.context is not None:
        try:
            ctx_update = json.loads(args.context)
            ctx = state["config"].setdefault("context", {})
            ctx.update(ctx_update)
        except json.JSONDecodeError:
            pass

    ws = state["waitall"]
    ws["barrier_pending_ack"] = False
    batch_idx = ws.get("batch_idx", 0)
    state["phase"] = "running"

    _save_or_exit(state, directory)
    print(json.dumps({"status": "barrier_acked", "batch_idx": batch_idx}))


# ==== loop-feedback ====

def cmd_loop_feedback(args: argparse.Namespace) -> None:
    directory = args.dir or DEFAULT_DIR
    state = _load_or_exit(args.slug, directory)

    if state["mode"] != "loop":
        print(json.dumps({"error": "not_loop_mode", "mode": state["mode"]}), file=sys.stderr)
        sys.exit(1)

    loop_st = state["loop"]
    if not loop_st.get("feedback_pending"):
        print(json.dumps({"error": "protocol_violation",
                          "hint": "必须先 dispatch → complete _finder 再调用 loop-feedback"}), file=sys.stderr)
        sys.exit(1)

    new_count = args.new_count
    loop_st["feedback_pending"] = False

    if new_count == 0:
        loop_st["dry_counter"] += 1
    else:
        loop_st["dry_counter"] = 0
        loop_st["seen_count"] += new_count

    if args.context is not None:
        try:
            ctx_update = json.loads(args.context)
            ctx = state["config"].setdefault("context", {})
            if "seen" in ctx_update:
                ctx["seen"] = ctx_update["seen"]
            else:
                ctx.update(ctx_update)
        except json.JSONDecodeError:
            pass

    if "_finder" in state["items"]:
        state["items"]["_finder"]["status"] = "pending"
        state["items"]["_finder"]["results"] = []
        state["items"]["_finder"]["attempts"] = []
        state["items"]["_finder"]["retry_count"] = 0
        state["items"]["_finder"]["error"] = None

    _save_or_exit(state, directory)
    print(json.dumps({
        "status": "feedback_applied",
        "round": loop_st["round"],
        "new_count": new_count,
        "dry_counter": loop_st["dry_counter"],
        "dry_threshold": state["config"]["loop"]["dry_threshold"],
    }))


# ==== status ====

def cmd_status(args: argparse.Namespace) -> None:
    directory = args.dir or DEFAULT_DIR
    state = _load_or_exit(args.slug, directory)

    items_dict = state["items"]
    running = sum(1 for n, it in items_dict.items() if it["status"] == "running" and n != "_finder")
    pending = sum(1 for n, it in items_dict.items() if it["status"] == "pending" and n != "_finder")
    done = sum(1 for n, it in items_dict.items() if it["status"] == "done" and n != "_finder")
    failed = sum(1 for n, it in items_dict.items() if it["status"] == "failed" and n != "_finder")
    total = len([n for n in items_dict if n != "_finder"])  # exclude internal _finder

    ws = state.get("waitall", {})
    print(json.dumps({
        "slug": state["slug"],
        "mode": state["mode"],
        "framework": state.get("framework"),
        "phase": state["phase"],
        "running_count": running,
        "pending_count": pending,
        "done_count": done,
        "failed_count": failed,
        "total_items": total,
        "current_batch": ws.get("batch_idx", 0) if state["mode"] == "waitall" else None,
        "current_round": state.get("loop", {}).get("round", 0) if state["mode"] == "loop" else None,
        "budget_spent": state["budget"]["spent"],
        "budget_total": state["config"]["budget_total"],
    }, ensure_ascii=False))


# ==== budget ====

def cmd_budget(args: argparse.Namespace) -> None:
    directory = args.dir or DEFAULT_DIR
    state = _load_or_exit(args.slug, directory)

    if args.spend:
        if args.spend < 0:
            print(json.dumps({"error": "negative_spend", "detail": "--spend must be non-negative"}), file=sys.stderr)
            sys.exit(1)
        state["budget"]["spent"] += args.spend
        _save_or_exit(state, directory)

    total = state["config"]["budget_total"]
    spent = state["budget"]["spent"]
    remaining = max(0, total - spent) if total is not None else None
    allowed = total is None or spent < total

    print(json.dumps({
        "total": total,
        "spent": spent,
        "remaining": remaining,
        "allowed": allowed,
    }, ensure_ascii=False))


# ==== summary ====

def _summarize(state: dict[str, Any]) -> dict[str, Any]:
    items_dict = state["items"]
    done = sum(1 for n, it in items_dict.items() if it["status"] == "done" and n != "_finder")
    failed = sum(1 for n, it in items_dict.items() if it["status"] == "failed" and n != "_finder")
    return {
        "total_items": len([n for n in items_dict if n != "_finder"]),
        "done": done,
        "failed": failed,
        "budget_spent": state["budget"]["spent"],
        "rounds": state.get("loop", {}).get("round", 0),
    }


# ==== cli ====

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scheduler.py",
        description="编排决策状态机 — Dynamic Workflow SKILL 辅助工具")
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="初始化 workflow")
    p_init.add_argument("--slug", required=True)
    p_init.add_argument("--mode", required=True, choices=["pipe", "waitall", "loop"])
    p_init.add_argument("--items", required=True, help="逗号分隔的 item 名称列表")
    p_init.add_argument("--stages", required=True, help="逗号分隔的 stage 名称列表")
    p_init.add_argument("--budget", type=int, default=None, help="token 预算上限")
    p_init.add_argument(
        "--concurrency",
        type=int,
        default=16,
        help="operator 配置的调度上限；不代表 executor 实际并行",
    )
    p_init.add_argument("--dry-threshold", type=int, default=2, help="loop 模式 dry 阈值")
    p_init.add_argument("--max-rounds", type=int, default=20, help="loop 模式最大轮数")
    p_init.add_argument("--max-retries", type=int, default=3, help="item 最大重试次数")
    p_init.add_argument("--framework", default=None, choices=["opencode", "codex"], help="执行框架标识")
    p_init.add_argument("--prompt-file", default=None, help="prompt 模板 JSON 文件路径")
    p_init.add_argument("--dir", default=None, help="状态文件目录")

    # dispatch
    p_disp = sub.add_parser("dispatch", help="获取下一步 action")
    p_disp.add_argument("--slug", required=True)
    p_disp.add_argument("--dir", default=None)

    # complete
    p_comp = sub.add_parser("complete", help="报告 agent 完成")
    p_comp.add_argument("--slug", required=True)
    p_comp.add_argument("--item", required=True)
    p_comp.add_argument("--stage", required=True)
    p_comp.add_argument("--result", default="null")
    p_comp.add_argument("--tokens", type=int, default=None)
    p_comp.add_argument("--retry", action="store_true", default=False)
    p_comp.add_argument("--context", default=None)
    p_comp.add_argument("--dir", default=None)

    # barrier-done
    p_bd = sub.add_parser("barrier-done", help="确认 barrier（纯 ack）")
    p_bd.add_argument("--slug", required=True)
    p_bd.add_argument("--context", default=None)
    p_bd.add_argument("--dir", default=None)

    # loop-feedback
    p_lf = sub.add_parser("loop-feedback", help="传回 loop 轮次的去重结果")
    p_lf.add_argument("--slug", required=True)
    p_lf.add_argument("--new-count", type=int, required=True, help="新发现数量（0 = 本轮无新发现）")
    p_lf.add_argument("--context", default=None)
    p_lf.add_argument("--dir", default=None)

    # status
    p_stat = sub.add_parser("status", help="查询状态")
    p_stat.add_argument("--slug", required=True)
    p_stat.add_argument("--dir", default=None)

    # budget
    p_bud = sub.add_parser("budget", help="查询/更新预算")
    p_bud.add_argument("--slug", required=True)
    p_bud.add_argument("--spend", type=int, default=None)
    p_bud.add_argument("--dir", default=None)

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "dispatch":
        cmd_dispatch(args)
    elif args.command == "complete":
        cmd_complete(args)
    elif args.command == "barrier-done":
        cmd_barrier_done(args)
    elif args.command == "loop-feedback":
        cmd_loop_feedback(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "budget":
        cmd_budget(args)


if __name__ == "__main__":
    main()
