"""Adapter tests for opencode and codex command construction and message extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from adapters.opencode import OpenCodeAdapter
from adapters.codex import CodexAdapter


class TestOpenCodeCommandConstruction:
    def test_command_list_format(self):
        adapter = OpenCodeAdapter()
        result = adapter.execute("test prompt", workdir=".", timeout=1)
        assert result.error == "opencode CLI not found"

    def test_extract_final_message_with_end_event(self):
        adapter = OpenCodeAdapter()
        output = '{"type":"text","text":"intermediate"}\n{"type":"end","content":"final answer"}'
        result = adapter._extract_final_message(output)
        assert result == "final answer"

    def test_extract_final_message_with_text_fallback(self):
        adapter = OpenCodeAdapter()
        output = '{"type":"text","text":"hello world"}'
        result = adapter._extract_final_message(output)
        assert result == "hello world"

    def test_extract_final_message_empty(self):
        adapter = OpenCodeAdapter()
        result = adapter._extract_final_message("")
        assert result == ""

    def test_extract_final_message_raw_fallback(self):
        adapter = OpenCodeAdapter()
        result = adapter._extract_final_message("plain text output")
        assert result == "plain text output"


class TestCodexCommandConstruction:
    def test_basic_command(self):
        adapter = CodexAdapter(sandbox="read-only")
        cmd = adapter._build_command("do something", "/workspace")
        assert cmd[0].lower().endswith(("codex", "codex.cmd", "codex.exe"))
        assert "--ask-for-approval" in cmd
        assert "never" in cmd
        assert "--sandbox" in cmd
        assert "read-only" in cmd
        assert "--json" in cmd
        assert "exec" in cmd
        assert cmd[-1] == "do something"

    def test_ephemeral_flag(self):
        adapter = CodexAdapter(sandbox="read-only", ephemeral=True)
        cmd = adapter._build_command("task", "/workspace")
        assert "--ephemeral" in cmd

    def test_session_resume_command(self):
        adapter = CodexAdapter(sandbox="read-only", session_id="sess-123")
        cmd = adapter._build_command("task", "/workspace")
        assert "resume" in cmd
        assert "sess-123" in cmd

    def test_extract_final_message_with_completed(self):
        adapter = CodexAdapter.__new__(CodexAdapter)
        output = (
            '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"last answer"}}\n'
        )
        result = adapter._extract_final_message(output)
        assert result == "last answer"

    def test_extract_final_message_no_completed(self):
        adapter = CodexAdapter.__new__(CodexAdapter)
        output = '{"type":"thread.started","thread_id":"t1"}\n'
        result = adapter._extract_final_message(output)
        assert result is None

    def test_extract_tokens(self):
        adapter = CodexAdapter.__new__(CodexAdapter)
        output = '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":50}}\n'
        result = adapter._extract_tokens(output)
        assert result == 150

    def test_extract_tokens_missing(self):
        adapter = CodexAdapter.__new__(CodexAdapter)
        output = '{"type":"thread.started"}\n'
        result = adapter._extract_tokens(output)
        assert result is None

    def test_invalid_sandbox_raises(self):
        with pytest.raises(ValueError, match="invalid codex sandbox"):
            CodexAdapter(sandbox="invalid")

    def test_ephemeral_and_session_raises(self):
        with pytest.raises(ValueError, match="ephemeral session resume"):
            CodexAdapter(sandbox="read-only", ephemeral=True, session_id="s1")
