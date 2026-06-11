"""Executor behavior tests."""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import scheduler
import executor
from adapters.base import CLIResult


def _make_step_args(slug, framework="opencode", tmp_dir=".workflow", **overrides):
    defaults = dict(
        slug=slug,
        framework=framework,
        dir=tmp_dir,
        timeout=300,
        verbose=False,
        dry_run=False,
        workdir=".",
        codex_sandbox="read-only",
        codex_output_schema=None,
        codex_ephemeral=False,
        codex_session_id=None,
    )
    defaults.update(overrides)
    return type("Args", (), defaults)()


class MockAdapter:
    def __init__(self, execute_result=None, healthy=True):
        self._result = execute_result
        self._healthy = healthy

    def health_check(self):
        return self._healthy

    def execute(self, prompt, workdir=".", timeout=300, verbose=False):
        return self._result


class TestCmdExecuteStepDone:
    def test_done_saves_state(self, tmp_path, init_pipe):
        tmp_dir = str(tmp_path)
        init_pipe(slug="t", items="a", stages="x", budget=100000)

        state = scheduler.load_state("t", tmp_dir)
        scheduler.get_next_action(state)
        state["items"]["a"]["status"] = "done"
        state["items"]["a"]["results"] = [{"ok": True}]
        state["items"]["a"]["stage_idx"] = 0
        scheduler.save_state(state, tmp_dir)

        mock_adapter = MockAdapter()
        step_args = _make_step_args("t", tmp_dir=tmp_dir)
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            with patch("executor.get_adapter", return_value=mock_adapter):
                ret = executor.cmd_execute_step(step_args)
        finally:
            sys.stdout = old_stdout

        assert ret["status"] == "done"


class TestCmdExecuteStepSpawnExecute:
    def test_spawn_execute_complete(self, tmp_path, init_pipe):
        tmp_dir = str(tmp_path)
        init_pipe(slug="t", items="a", stages="x", budget=100000)

        cli_result = CLIResult(
            success=True,
            final_message="all done",
            raw_output='{"type":"end","content":"all done"}',
            tokens_used=100,
        )
        mock_adapter = MockAdapter(execute_result=cli_result)

        step_args = _make_step_args("t", tmp_dir=tmp_dir)
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            with patch("executor.get_adapter", return_value=mock_adapter):
                ret = executor.cmd_execute_step(step_args)
        finally:
            sys.stdout = old_stdout

        assert ret["status"] == "completed"
        assert ret["item"] == "a"
        assert ret["stage"] == "x"
        state = scheduler.load_state("t", tmp_dir)
        assert state["items"]["a"]["status"] == "done"
        assert state["budget"]["spent"] == 100


class TestCmdExecuteStepWait:
    def test_wait_saves_state(self, tmp_path, init_pipe, read_state):
        tmp_dir = str(tmp_path)
        init_pipe(slug="t", items="a", stages="x", budget=100000)
        scheduler.load_state("t", tmp_dir)
        scheduler.get_next_action(state := scheduler.load_state("t", tmp_dir))
        state["items"]["a"]["status"] = "running"
        scheduler.save_state(state, tmp_dir)

        mock_adapter = MockAdapter()
        step_args = _make_step_args("t", tmp_dir=tmp_dir)
        with patch("executor.get_adapter", return_value=mock_adapter):
            ret = executor.cmd_execute_step(step_args)

        assert ret["status"] == "wait"
        saved = scheduler.load_state("t", tmp_dir)
        assert saved["items"]["a"]["status"] == "running"


class TestCmdRunBarrierBreak:
    def test_cmd_run_breaks_on_barrier(self, tmp_path, init_waitall):
        tmp_dir = str(tmp_path)
        init_waitall(slug="t", items="a,b", stages="x,y")

        scheduler.load_state("t", tmp_dir)
        state = scheduler.load_state("t", tmp_dir)
        scheduler.get_next_action(state)
        state["items"]["a"]["status"] = "done"
        state["items"]["a"]["results"] = [{"ok": True}]
        scheduler.get_next_action(state)
        state["items"]["b"]["status"] = "done"
        state["items"]["b"]["results"] = [{"ok": True}]
        scheduler.save_state(state, tmp_dir)

        mock_adapter = MockAdapter()
        run_args = type("Args", (), dict(
            slug="t", framework="opencode", dir=tmp_dir,
            timeout=300, verbose=False,
            workdir=".", max_rounds=10,
            codex_sandbox="read-only", codex_output_schema=None,
            codex_ephemeral=False, codex_session_id=None,
        ))()

        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        try:
            with patch("executor.get_adapter", return_value=mock_adapter):
                executor.cmd_run(run_args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        assert '"event": "run_complete"' in output


class TestCmdRunProtocolBlockedBreak:
    def test_cmd_run_breaks_on_protocol_blocked(self, tmp_path, init_waitall):
        tmp_dir = str(tmp_path)
        init_waitall(slug="t", items="a", stages="x,y")

        state = scheduler.load_state("t", tmp_dir)
        scheduler.get_next_action(state)
        state["items"]["a"]["status"] = "done"
        state["items"]["a"]["results"] = [{"ok": True}]
        scheduler.save_state(state, tmp_dir)

        state = scheduler.load_state("t", tmp_dir)
        action = scheduler.get_next_action(state)
        assert action["action"] == "barrier"
        scheduler.save_state(state, tmp_dir)

        mock_adapter = MockAdapter()
        run_args = type("Args", (), dict(
            slug="t", framework="opencode", dir=tmp_dir,
            timeout=300, verbose=False,
            workdir=".", max_rounds=10,
            codex_sandbox="read-only", codex_output_schema=None,
            codex_ephemeral=False, codex_session_id=None,
        ))()

        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        try:
            with patch("executor.get_adapter", return_value=mock_adapter):
                executor.cmd_run(run_args)
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        parsed = [json.loads(l) for l in lines]
        assert any(e.get("status") == "protocol_blocked" or e.get("event") == "protocol_blocked" for e in parsed)


class TestCmdExecuteStepFailureRetry:
    def test_failure_triggers_retry(self, tmp_path, init_pipe):
        tmp_dir = str(tmp_path)
        init_pipe(slug="t", items="a", stages="x", budget=100000, max_retries=3)

        cli_result = CLIResult(
            success=False,
            final_message="",
            raw_output="",
            error="exec failed",
        )
        mock_adapter = MockAdapter(execute_result=cli_result)

        step_args = _make_step_args("t", tmp_dir=tmp_dir)
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            with patch("executor.get_adapter", return_value=mock_adapter):
                ret = executor.cmd_execute_step(step_args)
        finally:
            sys.stdout = old_stdout

        assert ret["status"] == "failed"
        assert ret["item"] == "a"
        assert ret["stage"] == "x"
        state = scheduler.load_state("t", tmp_dir)
        assert state["items"]["a"]["retry_count"] == 1
        assert state["items"]["a"]["status"] == "pending"
