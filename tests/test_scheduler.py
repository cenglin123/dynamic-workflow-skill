"""Scheduler core behavior tests — contract assertions B-01~B-21."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import scheduler


class TestB01_InitCreatesCorrectState:
    """B-01: init creates correct state.json with items, stages, mode."""

    def test_init_pipe_creates_state(self, init_pipe, read_state, tmp_dir):
        init_pipe(slug="test", items="a,b,c", stages="x,y")
        state = read_state("test")
        assert state["config"]["items"] == ["a", "b", "c"]
        assert state["config"]["stages"] == ["x", "y"]
        assert state["mode"] == "pipe"
        assert state["phase"] == "running"

    def test_init_waitall_creates_state(self, init_waitall, read_state):
        init_waitall(slug="w", items="p,q", stages="s1,s2,s3")
        state = read_state("w")
        assert state["config"]["items"] == ["p", "q"]
        assert state["config"]["stages"] == ["s1", "s2", "s3"]
        assert state["mode"] == "waitall"

    def test_init_loop_creates_state(self, init_loop, read_state):
        init_loop(slug="l", items="x", stages="y")
        state = read_state("l")
        assert state["config"]["items"] == ["x"]
        assert state["mode"] == "loop"
        assert state["loop"]["dry_counter"] == 0
        assert state["loop"]["round"] == 0


class TestB02_DispatchReturnsSpawn:
    """B-02: dispatch in pipe mode returns spawn for first item, first stage."""

    def test_first_dispatch(self, init_pipe, do_dispatch):
        init_pipe(slug="t", items="a,b,c", stages="x,y")
        action = do_dispatch("t")
        assert action["action"] == "spawn"
        assert action["item"] == "a"
        assert action["stage"] == "x"
        assert action["stage_idx"] == 0


class TestB03_CompleteSetsDone:
    """B-03: complete sets item status to done and increases budget.spent."""

    def test_complete_marks_done(self, init_pipe, do_dispatch, do_complete, read_state):
        init_pipe(slug="t", items="a", stages="x", budget=100000)
        do_dispatch("t")
        do_complete("t", "a", "x", result='{"ok":true}')
        state = read_state("t")
        assert state["items"]["a"]["status"] == "done"
        assert state["budget"]["spent"] > 0

    def test_complete_with_custom_tokens(self, init_pipe, do_dispatch, do_complete, read_state):
        init_pipe(slug="t", items="a", stages="x", budget=100000)
        do_dispatch("t")
        do_complete("t", "a", "x", result='{"ok":true}', tokens=500)
        state = read_state("t")
        assert state["budget"]["spent"] == 500


class TestB04_PipeAdvancesStage:
    """B-04: pipe mode — after completing item A stage 1, dispatch returns item A stage 2."""

    def test_pipe_stage_progression(self, init_pipe, do_dispatch, do_complete):
        init_pipe(slug="t", items="a,b", stages="x,y")
        # dispatch a@x
        action1 = do_dispatch("t")
        assert action1["item"] == "a" and action1["stage"] == "x"
        # complete a@x
        do_complete("t", "a", "x")
        # dispatch should return a@y, NOT b@x
        action2 = do_dispatch("t")
        assert action2["item"] == "a"
        assert action2["stage"] == "y"
        assert action2["stage_idx"] == 1


class TestB05_WaitallBarrier:
    """B-05: waitall mode — all items complete for a stage → dispatch returns barrier."""

    def test_waitall_barrier_after_all_complete(self, init_waitall, do_dispatch, do_complete):
        init_waitall(slug="t", items="a,b", stages="x,y")
        # dispatch and complete both items for stage x
        do_dispatch("t")  # a@x
        do_complete("t", "a", "x")
        do_dispatch("t")  # b@x
        do_complete("t", "b", "x")
        # next dispatch should return barrier
        action = do_dispatch("t")
        assert action["action"] == "barrier"


class TestB06_BarrierRequiresAck:
    """B-06: barrier-done must be called before continuing dispatch after barrier."""

    def test_dispatch_blocked_until_barrier_done(self, init_waitall, do_dispatch, do_complete, do_barrier_done):
        init_waitall(slug="t", items="a", stages="x,y")
        do_dispatch("t")  # a@x
        do_complete("t", "a", "x")
        do_dispatch("t")  # barrier
        # try dispatch without barrier-done
        action = do_dispatch("t")
        assert action["action"] == "barrier_pending_ack"
        # now ack
        do_barrier_done("t")
        # dispatch should work now
        action2 = do_dispatch("t")
        assert action2["action"] == "spawn"


class TestB07_LoopDispatchFinder:
    """B-07: loop mode dispatch returns spawn for _finder with round field."""

    def test_loop_first_dispatch(self, init_loop, do_dispatch):
        init_loop(slug="t", items="a,b", stages="x")
        action = do_dispatch("t")
        assert action["action"] == "spawn"
        assert action["item"] == "_finder"
        assert "round" in action
        assert action["round"] == 1


class TestB08_LoopRequiresFeedback:
    """B-08: loop mode — after completing _finder, loop-feedback must be called."""

    def test_dispatch_blocked_until_feedback(self, init_loop, do_dispatch, do_complete, do_loop_feedback):
        init_loop(slug="t", items="a", stages="x")
        do_dispatch("t")  # _finder round 1
        do_complete("t", "_finder", "x")
        # try dispatch without feedback
        action = do_dispatch("t")
        assert action["action"] == "loop_feedback_pending"
        # now feedback
        do_loop_feedback("t", new_count=3)
        # dispatch should work
        action2 = do_dispatch("t")
        assert action2["action"] == "spawn"
        assert action2["item"] == "_finder"


class TestB09_DryCounterBehavior:
    """B-09: loop-feedback new_count=0 increments dry_counter; N>0 resets it."""

    def test_dry_counter_increment(self, init_loop, do_dispatch, do_complete, do_loop_feedback, read_state):
        init_loop(slug="t", items="a", stages="x")
        do_dispatch("t")
        do_complete("t", "_finder", "x")
        do_loop_feedback("t", new_count=0)
        state = read_state("t")
        assert state["loop"]["dry_counter"] == 1

    def test_dry_counter_reset(self, init_loop, do_dispatch, do_complete, do_loop_feedback, read_state):
        init_loop(slug="t", items="a", stages="x")
        do_dispatch("t")
        do_complete("t", "_finder", "x")
        do_loop_feedback("t", new_count=5)
        state = read_state("t")
        assert state["loop"]["dry_counter"] == 0


class TestB10_LoopDoneOnDryThreshold:
    """B-10: loop mode — dry_counter >= dry_threshold → dispatch returns done."""

    def test_loop_done_after_threshold(self, init_loop, do_dispatch, do_complete, do_loop_feedback):
        init_loop(slug="t", items="a", stages="x", dry_threshold=2)
        # round 1: dry
        do_dispatch("t")
        do_complete("t", "_finder", "x")
        do_loop_feedback("t", new_count=0)
        # round 2: dry
        do_dispatch("t")
        do_complete("t", "_finder", "x")
        do_loop_feedback("t", new_count=0)
        # dispatch should return done
        action = do_dispatch("t")
        assert action["action"] == "done"


class TestB11_BudgetExhausted:
    """B-11: budget_total exceeded → dispatch returns stop with reason budget_exhausted."""

    def test_budget_blocks_spawn(self, init_pipe, do_dispatch, do_complete, read_state):
        init_pipe(slug="t", items="a,b", stages="x", budget=100)
        do_dispatch("t")  # a@x
        do_complete("t", "a", "x", tokens=100)
        # budget is exhausted, next dispatch should stop
        action = do_dispatch("t")
        assert action["action"] == "stop"
        assert action["reason"] == "budget_exhausted"


class TestB12_StatusFields:
    """B-12: status returns running_count, pending_count, done_count, failed_count."""

    def test_status_has_required_fields(self, init_pipe, do_status):
        init_pipe(slug="t", items="a,b", stages="x")
        status = do_status("t")
        assert "running_count" in status
        assert "pending_count" in status
        assert "done_count" in status
        assert "failed_count" in status


class TestB13_BudgetFields:
    """B-13: budget returns total, spent, remaining, allowed."""

    def test_budget_has_required_fields(self, init_pipe, do_budget):
        init_pipe(slug="t", items="a", stages="x", budget=1000)
        budget = do_budget("t")
        assert "total" in budget
        assert "spent" in budget
        assert "remaining" in budget
        assert "allowed" in budget
        assert budget["total"] == 1000
        assert budget["spent"] == 0
        assert budget["remaining"] == 1000


class TestB14_StageMismatch:
    """B-14: complete with wrong stage returns stage_mismatch error."""

    def test_stage_mismatch_error(self, init_pipe, do_dispatch, tmp_dir):
        init_pipe(slug="t", items="a", stages="x,y")
        do_dispatch("t")  # a@x
        # try complete with wrong stage
        args = type("Args", (), {
            "slug": "t", "item": "a", "stage": "WRONG",
            "result": '{"ok":true}', "tokens": None, "retry": False,
            "context": None, "dir": tmp_dir,
        })()
        import io
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            with pytest.raises(SystemExit) as exc_info:
                scheduler.cmd_complete(args)
            assert exc_info.value.code == 1
            stderr_output = sys.stderr.getvalue()
            error = json.loads(stderr_output)
            assert "stage_mismatch" in error["error"]
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


class TestB15_BudgetAllowedSemantics:
    """B-15: budget allowed=false when spent >= total."""

    def test_allowed_false_when_spent_equals_total(self, init_pipe, do_budget, read_state):
        init_pipe(slug="t", items="a", stages="x", budget=1000)
        do_budget("t", spend=1000)
        budget = do_budget("t")
        assert budget["allowed"] is False
        assert budget["spent"] == 1000

    def test_allowed_true_when_spent_less_than_total(self, init_pipe, do_budget):
        init_pipe(slug="t", items="a", stages="x", budget=1000)
        do_budget("t", spend=999)
        budget = do_budget("t")
        assert budget["allowed"] is True


class TestB16_StdoutStderrJson:
    """B-16: dispatch JSON output on stdout; errors on stderr as valid JSON."""

    def test_normal_dispatch_stdout(self, init_pipe, do_dispatch):
        init_pipe(slug="t", items="a", stages="x")
        action = do_dispatch("t")
        # Should be valid JSON with action field
        assert "action" in action

    def test_error_dispatch_stderr_json(self, tmp_dir):
        """Dispatch nonexistent slug → stderr with valid JSON."""
        import io
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            args = type("Args", (), {"slug": "nonexistent", "dir": tmp_dir})()
            with pytest.raises(SystemExit) as exc_info:
                scheduler.cmd_dispatch(args)
            assert exc_info.value.code == 1
            stderr_output = sys.stderr.getvalue()
            error = json.loads(stderr_output)  # must be valid JSON
            assert error["error"] == "not_found"
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


class TestB17_NonJsonResult:
    """B-17: complete with non-JSON result stores raw string."""

    def test_raw_string_result(self, init_pipe, do_dispatch, do_complete, read_state):
        init_pipe(slug="t", items="a", stages="x")
        do_dispatch("t")
        do_complete("t", "a", "x", result="not-json-string")
        state = read_state("t")
        # Should store raw string, not raise error
        assert state["items"]["a"]["results"][-1] == "not-json-string"


class TestB18_RetryBehavior:
    """B-18: complete --retry resets item to pending and increments retry_count."""

    def test_retry_resets_to_pending(self, init_pipe, do_dispatch, do_complete, read_state):
        init_pipe(slug="t", items="a", stages="x", max_retries=3)
        do_dispatch("t")  # a@x running
        do_complete("t", "a", "x", retry=True)  # retry
        state = read_state("t")
        assert state["items"]["a"]["status"] == "pending"
        assert state["items"]["a"]["retry_count"] == 1


class TestB19_MaxRetriesExceeded:
    """B-19: retry count reaching max_retries → item status becomes failed."""

    def test_max_retries_sets_failed(self, init_pipe, read_state, tmp_dir):
        """Use library API to test retry behavior since dispatch_pipe doesn't
        handle retried pending items (they need orchestrator re-dispatch)."""
        init_pipe(slug="t", items="a", stages="x", max_retries=2)
        state = read_state("t")
        # First attempt: dispatch a@x (make it running), then retry
        scheduler.get_next_action(state)
        scheduler.apply_result(state, "a", "x", result='{"ok":true}', retry=True)
        assert state["items"]["a"]["status"] == "pending"
        assert state["items"]["a"]["retry_count"] == 1
        # Second attempt: dispatch again (make it running), then retry
        # Since dispatch_pipe doesn't handle retried items, manually set to running
        state["items"]["a"]["status"] = "running"
        scheduler.apply_result(state, "a", "x", result='{"ok":true}', retry=True)
        assert state["items"]["a"]["status"] == "failed"
        assert state["items"]["a"]["error"] == "max_retries_exceeded"


class TestB20_CustomDir:
    """B-20: --dir parameter writes state to custom_dir/<slug>/state.json."""

    def test_custom_dir(self, tmp_path):
        custom_dir = str(tmp_path / "custom_workflow")
        args = type("Args", (), {
            "slug": "test",
            "mode": "pipe",
            "items": "a,b",
            "stages": "x",
            "budget": None,
            "concurrency": 16,
            "dry_threshold": 2,
            "max_rounds": 20,
            "max_retries": 3,
            "framework": None,
            "prompt_file": None,
            "dir": custom_dir,
        })()
        scheduler.cmd_init(args)
        state_path = Path(custom_dir) / "test" / "state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["slug"] == "test"


class TestB21_MaxRetriesZero:
    """B-21: --max-retries 0 → complete --retry immediately sets item to failed."""

    def test_max_retries_zero_immediate_fail(self, init_pipe, do_dispatch, do_complete, read_state):
        init_pipe(slug="t", items="a", stages="x", max_retries=0)
        do_dispatch("t")  # a@x running
        do_complete("t", "a", "x", retry=True)
        state = read_state("t")
        assert state["items"]["a"]["status"] == "failed"
        assert state["items"]["a"]["error"] == "max_retries_exceeded"


class TestB22_DuplicateItems:
    def test_duplicate_items_rejected(self, tmp_dir):
        args = type("Args", (), {
            "slug": "t22", "mode": "pipe", "items": "a,a",
            "stages": "x", "budget": None, "concurrency": 16,
            "dry_threshold": 2, "max_rounds": 20, "max_retries": 3,
            "framework": None, "prompt_file": None, "dir": tmp_dir,
        })()
        import io
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            with pytest.raises(SystemExit):
                scheduler.cmd_init(args)
            assert "duplicate_items" in sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


class TestB23_TemplateMarkerItems:
    def test_template_marker_items_rejected(self, tmp_dir):
        args = type("Args", (), {
            "slug": "t23", "mode": "pipe", "items": "{{item}}",
            "stages": "x", "budget": None, "concurrency": 16,
            "dry_threshold": 2, "max_rounds": 20, "max_retries": 3,
            "framework": None, "prompt_file": None, "dir": tmp_dir,
        })()
        import io
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            with pytest.raises(SystemExit):
                scheduler.cmd_init(args)
            assert "template markers" in sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


class TestB24_ReservedItemName:
    def test_reserved_item_name_rejected(self, tmp_dir):
        args = type("Args", (), {
            "slug": "t24", "mode": "pipe", "items": "_finder",
            "stages": "x", "budget": None, "concurrency": 16,
            "dry_threshold": 2, "max_rounds": 20, "max_retries": 3,
            "framework": None, "prompt_file": None, "dir": tmp_dir,
        })()
        import io
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            with pytest.raises(SystemExit):
                scheduler.cmd_init(args)
            assert "reserved name" in sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


class TestB25_InvalidSlug:
    def test_invalid_slug_rejected(self, tmp_dir):
        with pytest.raises(scheduler.StateError) as exc_info:
            scheduler.load_state("bad slug!", tmp_dir)
        assert "invalid_slug" in str(exc_info.value)


class TestB26_EmptyItems:
    def test_empty_items_rejected(self, tmp_dir):
        args = type("Args", (), {
            "slug": "t26", "mode": "pipe", "items": "",
            "stages": "x", "budget": None, "concurrency": 16,
            "dry_threshold": 2, "max_rounds": 20, "max_retries": 3,
            "framework": None, "prompt_file": None, "dir": tmp_dir,
        })()
        import io
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            with pytest.raises(SystemExit):
                scheduler.cmd_init(args)
            assert "no_items" in sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


class TestB27_CorruptedStateLoad:
    def test_corrupted_state_raises_error(self, tmp_dir):
        from pathlib import Path
        state_dir = Path(tmp_dir) / "t27"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("NOT VALID JSON{{{{", encoding="utf-8")
        with pytest.raises(scheduler.StateError):
            scheduler.load_state("t27", tmp_dir)


class TestB28_FailFastWaitall:
    def test_fail_fast_stops_on_failure(self, tmp_dir):
        args = type("Args", (), {
            "slug": "t28", "mode": "waitall", "items": "a,b",
            "stages": "x,y", "budget": None, "concurrency": 16,
            "dry_threshold": 2, "max_rounds": 20, "max_retries": 3,
            "framework": None, "prompt_file": None, "dir": tmp_dir,
        })()
        scheduler.cmd_init(args)

        import io
        state = scheduler.load_state("t28", tmp_dir)
        state["config"]["waitall"]["fail_fast"] = True
        scheduler.save_state(state, tmp_dir)

        state = scheduler.load_state("t28", tmp_dir)
        scheduler.get_next_action(state)
        state["items"]["a"]["status"] = "failed"
        state["items"]["a"]["retry_count"] = 3
        state["items"]["a"]["error"] = "test_fail"
        state["items"]["b"]["status"] = "done"
        state["items"]["b"]["results"] = [{"ok": True}]
        scheduler.save_state(state, tmp_dir)

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            disp_args = type("Args", (), {"slug": "t28", "dir": tmp_dir})()
            scheduler.cmd_dispatch(disp_args)
            output = sys.stdout.getvalue()
            result = json.loads(output)
        finally:
            sys.stdout = old_stdout
        assert result["action"] == "stop"
        assert result["reason"] == "barrier_gate_failed"
