"""Error handling tests — contract assertions E-01~E-15."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import scheduler


def _run_cmd_stderr(cmd_func, *args, **kwargs):
    """Run a scheduler command and capture stderr. Returns (exit_code, stderr_dict)."""
    import io
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        cmd_func(*args, **kwargs)
        return 0, None
    except SystemExit as e:
        stderr_output = sys.stderr.getvalue()
        try:
            error = json.loads(stderr_output)
        except json.JSONDecodeError:
            error = {"raw": stderr_output}
        return e.code, error
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr


class TestE01_InitDuplicateSlug:
    """E-01: init duplicate slug → already_exists error, exit code 1."""

    def test_duplicate_init_fails(self, init_pipe, tmp_dir):
        init_pipe(slug="test", items="a", stages="x")
        args = type("Args", (), {
            "slug": "test", "mode": "pipe", "items": "a", "stages": "x",
            "budget": None, "concurrency": 16, "dry_threshold": 2,
            "max_rounds": 20, "max_retries": 3, "framework": None,
            "prompt_file": None, "dir": tmp_dir,
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_init, args)
        assert code == 1
        assert error["error"] == "already_exists"


class TestE02_DispatchNonexistentSlug:
    """E-02: dispatch nonexistent slug → not_found error, exit code 1."""

    def test_dispatch_nonexistent(self, tmp_dir):
        args = type("Args", (), {"slug": "nonexistent", "dir": tmp_dir})()
        code, error = _run_cmd_stderr(scheduler.cmd_dispatch, args)
        assert code == 1
        assert error["error"] == "not_found"


class TestE03_InitEmptyItems:
    """E-03: init with empty items → no_items error, exit code 1."""

    def test_empty_items(self, tmp_dir):
        args = type("Args", (), {
            "slug": "t", "mode": "pipe", "items": "", "stages": "x",
            "budget": None, "concurrency": 16, "dry_threshold": 2,
            "max_rounds": 20, "max_retries": 3, "framework": None,
            "prompt_file": None, "dir": tmp_dir,
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_init, args)
        assert code == 1
        assert error["error"] == "no_items"


class TestE04_InitEmptyStages:
    """E-04: init with empty stages → no_stages error, exit code 1."""

    def test_empty_stages(self, tmp_dir):
        args = type("Args", (), {
            "slug": "t", "mode": "pipe", "items": "a", "stages": "",
            "budget": None, "concurrency": 16, "dry_threshold": 2,
            "max_rounds": 20, "max_retries": 3, "framework": None,
            "prompt_file": None, "dir": tmp_dir,
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_init, args)
        assert code == 1
        assert error["error"] == "no_stages"


class TestE05_CompleteInvalidItem:
    """E-05: complete with nonexistent item → invalid_item error, exit code 1."""

    def test_invalid_item(self, init_pipe, do_dispatch, tmp_dir):
        init_pipe(slug="t", items="a", stages="x")
        do_dispatch("t")
        args = type("Args", (), {
            "slug": "t", "item": "nonexistent", "stage": "x",
            "result": '{"ok":true}', "tokens": None, "retry": False,
            "context": None, "dir": tmp_dir,
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_complete, args)
        assert code == 1
        assert "invalid_item" in error["error"]


class TestE06_CompleteNonRunningItem:
    """E-06: complete non-running item → protocol_violation error, exit code 1."""

    def test_complete_pending_item(self, init_pipe, tmp_dir):
        init_pipe(slug="t", items="a", stages="x")
        # a is still pending (not dispatched)
        args = type("Args", (), {
            "slug": "t", "item": "a", "stage": "x",
            "result": '{"ok":true}', "tokens": None, "retry": False,
            "context": None, "dir": tmp_dir,
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_complete, args)
        assert code == 1
        assert "protocol_violation" in error["error"]


class TestE07_BarrierDoneNotWaitallMode:
    """E-07: barrier-done in non-waitall mode → not_waitall_mode error."""

    def test_barrier_done_in_pipe_mode(self, init_pipe, tmp_dir):
        init_pipe(slug="t", items="a", stages="x")
        args = type("Args", (), {"slug": "t", "context": None, "dir": tmp_dir})()
        code, error = _run_cmd_stderr(scheduler.cmd_barrier_done, args)
        assert code == 1
        assert error["error"] == "not_waitall_mode"


class TestE08_BarrierDoneNoBarrier:
    """E-08: barrier-done when no pending barrier → protocol_violation error."""

    def test_barrier_done_without_pending(self, init_waitall, tmp_dir):
        init_waitall(slug="t", items="a", stages="x")
        args = type("Args", (), {"slug": "t", "context": None, "dir": tmp_dir})()
        code, error = _run_cmd_stderr(scheduler.cmd_barrier_done, args)
        assert code == 1
        assert "protocol_violation" in error["error"]


class TestE09_LoopFeedbackNotLoopMode:
    """E-09: loop-feedback in non-loop mode → not_loop_mode error."""

    def test_loop_feedback_in_pipe_mode(self, init_pipe, tmp_dir):
        init_pipe(slug="t", items="a", stages="x")
        args = type("Args", (), {
            "slug": "t", "new_count": 0, "context": None, "dir": tmp_dir,
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_loop_feedback, args)
        assert code == 1
        assert error["error"] == "not_loop_mode"


class TestE10_LoopFeedbackNoFinder:
    """E-10: loop-feedback when finder not completed → protocol_violation error."""

    def test_loop_feedback_without_finder(self, init_loop, tmp_dir):
        init_loop(slug="t", items="a", stages="x")
        args = type("Args", (), {
            "slug": "t", "new_count": 0, "context": None, "dir": tmp_dir,
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_loop_feedback, args)
        assert code == 1
        assert "protocol_violation" in error["error"]


class TestE11_InvalidPromptFileNotFound:
    """E-11: init with nonexistent prompt-file → invalid_prompt_file error."""

    def test_nonexistent_prompt_file(self, tmp_dir):
        args = type("Args", (), {
            "slug": "t", "mode": "pipe", "items": "a", "stages": "x",
            "budget": None, "concurrency": 16, "dry_threshold": 2,
            "max_rounds": 20, "max_retries": 3, "framework": None,
            "prompt_file": "/nonexistent/path.json", "dir": tmp_dir,
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_init, args)
        assert code == 1
        assert error["error"] == "invalid_prompt_file"


class TestE12_InvalidPromptFileBadJson:
    """E-12: init with bad JSON prompt-file → invalid_prompt_file error."""

    def test_bad_json_prompt_file(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")
        args = type("Args", (), {
            "slug": "t", "mode": "pipe", "items": "a", "stages": "x",
            "budget": None, "concurrency": 16, "dry_threshold": 2,
            "max_rounds": 20, "max_retries": 3, "framework": None,
            "prompt_file": str(bad_file), "dir": str(tmp_path),
        })()
        code, error = _run_cmd_stderr(scheduler.cmd_init, args)
        assert code == 1
        assert error["error"] == "invalid_prompt_file"


class TestE13_CorruptedStateFile:
    """E-13: corrupted state.json → invalid_state error."""

    def test_corrupted_state(self, init_pipe, tmp_dir):
        init_pipe(slug="t", items="a", stages="x")
        # Corrupt the state file
        state_path = Path(tmp_dir) / "t" / "state.json"
        state_path.write_text("not json!", encoding="utf-8")
        args = type("Args", (), {"slug": "t", "dir": tmp_dir})()
        code, error = _run_cmd_stderr(scheduler.cmd_dispatch, args)
        assert code == 1
        assert error["error"] == "invalid_state"


class TestE14_WriteFailed:
    """E-14: Windows file lock → write_failed error. (Hard to test reliably, skip or mock.)"""

    @pytest.mark.skip(reason="Cannot reliably simulate file locking on all platforms")
    def test_write_failed(self):
        pass


class TestE15_BudgetNoneAllowsAll:
    """E-15: budget_total=None → _budget_allows always returns True."""

    def test_no_budget_allows_dispatch(self, init_pipe, do_dispatch, do_complete):
        init_pipe(slug="t", items="a,b,c", stages="x", budget=None)
        # All dispatches should succeed without budget limit
        action1 = do_dispatch("t")
        assert action1["action"] == "spawn"
        do_complete("t", "a", "x")
        action2 = do_dispatch("t")
        assert action2["action"] == "spawn"
        do_complete("t", "b", "x")
        action3 = do_dispatch("t")
        assert action3["action"] == "spawn"
