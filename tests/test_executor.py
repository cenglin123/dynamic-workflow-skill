"""Tests for executor CLI option validation and serial execution."""

import argparse
import subprocess
import sys
from pathlib import Path

from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import executor


def test_cli_rejects_ephemeral_resume_combination():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/executor.py",
            "--codex-ephemeral",
            "--codex-session-id", "thread-id",
            "execute-step",
            "--slug", "unused",
            "--framework", "codex",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 2
    assert "ephemeral" in result.stderr
    assert "resume" in result.stderr


def test_cli_rejects_session_resume_with_run():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/executor.py",
            "--codex-session-id", "thread-id",
            "run",
            "--slug", "unused",
            "--framework", "codex",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 2
    assert "session" in result.stderr
    assert "execute-step" in result.stderr


def test_run_executes_steps_serially():
    args = argparse.Namespace(
        slug="workflow",
        framework="codex",
        dir=".workflow",
        timeout=300,
        max_retries=0,
        verbose=False,
        workdir=".",
        max_rounds=None,
        codex_sandbox="read-only",
        codex_output_schema=None,
        codex_ephemeral=True,
        codex_session_id=None,
    )
    events = []
    results = [
        {"status": "completed", "item": "a", "stage": "review"},
        {"status": "completed", "item": "b", "stage": "review"},
        {"status": "done"},
    ]

    def fake_step(step_args):
        events.append((step_args.slug, len(events)))
        return results[len(events) - 1]

    with patch.object(executor, "cmd_execute_step", side_effect=fake_step):
        executor.cmd_run(args)

    assert events == [
        ("workflow", 0),
        ("workflow", 1),
        ("workflow", 2),
    ]
