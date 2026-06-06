"""Shared fixtures for scheduler.py tests."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts/ to path so we can import scheduler
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import scheduler


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for workflow state files."""
    return str(tmp_path)


@pytest.fixture
def init_pipe(tmp_dir):
    """Initialize a pipe workflow with items a,b,c and stages x,y."""
    def _init(slug="test", items="a,b,c", stages="x,y", budget=None, concurrency=16, max_retries=3):
        args = type("Args", (), {
            "slug": slug,
            "mode": "pipe",
            "items": items,
            "stages": stages,
            "budget": budget,
            "concurrency": concurrency,
            "dry_threshold": 2,
            "max_rounds": 20,
            "max_retries": max_retries,
            "framework": None,
            "prompt_file": None,
            "dir": tmp_dir,
        })()
        scheduler.cmd_init(args)
        return slug
    return _init


@pytest.fixture
def init_waitall(tmp_dir):
    """Initialize a waitall workflow."""
    def _init(slug="test", items="a,b,c", stages="x,y", budget=None, concurrency=16, max_retries=3):
        args = type("Args", (), {
            "slug": slug,
            "mode": "waitall",
            "items": items,
            "stages": stages,
            "budget": budget,
            "concurrency": concurrency,
            "dry_threshold": 2,
            "max_rounds": 20,
            "max_retries": max_retries,
            "framework": None,
            "prompt_file": None,
            "dir": tmp_dir,
        })()
        scheduler.cmd_init(args)
        return slug
    return _init


@pytest.fixture
def init_loop(tmp_dir):
    """Initialize a loop workflow."""
    def _init(slug="test", items="a,b", stages="x", budget=None, concurrency=16,
              dry_threshold=2, max_rounds=20, max_retries=3):
        args = type("Args", (), {
            "slug": slug,
            "mode": "loop",
            "items": items,
            "stages": stages,
            "budget": budget,
            "concurrency": concurrency,
            "dry_threshold": dry_threshold,
            "max_rounds": max_rounds,
            "max_retries": max_retries,
            "framework": None,
            "prompt_file": None,
            "dir": tmp_dir,
        })()
        scheduler.cmd_init(args)
        return slug
    return _init


@pytest.fixture
def do_dispatch(tmp_dir):
    """Dispatch and return the action dict."""
    def _dispatch(slug="test"):
        args = type("Args", (), {"slug": slug, "dir": tmp_dir})()
        # Capture stdout
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            scheduler.cmd_dispatch(args)
            output = sys.stdout.getvalue()
            return json.loads(output)
        finally:
            sys.stdout = old_stdout
    return _dispatch


@pytest.fixture
def do_complete(tmp_dir):
    """Complete an item and return the result dict."""
    def _complete(slug, item, stage, result='{"ok":true}', tokens=None, retry=False, context=None):
        args = type("Args", (), {
            "slug": slug,
            "item": item,
            "stage": stage,
            "result": result,
            "tokens": tokens,
            "retry": retry,
            "context": context,
            "dir": tmp_dir,
        })()
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            scheduler.cmd_complete(args)
            output = sys.stdout.getvalue()
            return json.loads(output)
        finally:
            sys.stdout = old_stdout
    return _complete


@pytest.fixture
def do_barrier_done(tmp_dir):
    """Ack a barrier and return the result dict."""
    def _barrier_done(slug="test", context=None):
        args = type("Args", (), {"slug": slug, "context": context, "dir": tmp_dir})()
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            scheduler.cmd_barrier_done(args)
            output = sys.stdout.getvalue()
            return json.loads(output)
        finally:
            sys.stdout = old_stdout
    return _barrier_done


@pytest.fixture
def do_loop_feedback(tmp_dir):
    """Call loop-feedback and return the result dict."""
    def _loop_feedback(slug="test", new_count=0, context=None):
        args = type("Args", (), {
            "slug": slug,
            "new_count": new_count,
            "context": context,
            "dir": tmp_dir,
        })()
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            scheduler.cmd_loop_feedback(args)
            output = sys.stdout.getvalue()
            return json.loads(output)
        finally:
            sys.stdout = old_stdout
    return _loop_feedback


@pytest.fixture
def do_status(tmp_dir):
    """Get status and return the result dict."""
    def _status(slug="test"):
        args = type("Args", (), {"slug": slug, "dir": tmp_dir})()
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            scheduler.cmd_status(args)
            output = sys.stdout.getvalue()
            return json.loads(output)
        finally:
            sys.stdout = old_stdout
    return _status


@pytest.fixture
def do_budget(tmp_dir):
    """Query/update budget and return the result dict."""
    def _budget(slug="test", spend=None):
        args = type("Args", (), {"slug": slug, "spend": spend, "dir": tmp_dir})()
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            scheduler.cmd_budget(args)
            output = sys.stdout.getvalue()
            return json.loads(output)
        finally:
            sys.stdout = old_stdout
    return _budget


@pytest.fixture
def read_state(tmp_dir):
    """Read state.json for a given slug."""
    def _read(slug="test"):
        path = Path(tmp_dir) / slug / "state.json"
        return json.loads(path.read_text(encoding="utf-8"))
    return _read
