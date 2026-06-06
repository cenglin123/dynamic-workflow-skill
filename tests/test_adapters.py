"""Tests for framework adapters (opencode/codex) using mocks."""

import json
import subprocess

import pytest
from unittest.mock import patch, Mock

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from adapters.opencode import OpenCodeAdapter
from adapters.codex import CodexAdapter


class TestOpenCodeAdapter:
    @patch("subprocess.run")
    def test_execute_success(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"type":"end","content":"result","tokens":42}',
            stderr=""
        )
        adapter = OpenCodeAdapter()
        result = adapter.execute("test prompt")
        assert result.success is True
        assert result.final_message == "result"
        assert result.tokens_used == 42
        assert result.duration_seconds >= 0

    @patch("subprocess.run")
    def test_execute_nonzero_exit(self, mock_run):
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="error output"
        )
        adapter = OpenCodeAdapter()
        result = adapter.execute("test prompt")
        assert result.success is False
        assert "Exit code 1" in result.error

    @patch("subprocess.run")
    def test_execute_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="opencode", timeout=300)
        adapter = OpenCodeAdapter()
        result = adapter.execute("test prompt")
        assert result.success is False
        assert "Timeout" in result.error

    @patch("subprocess.run")
    def test_execute_cli_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        adapter = OpenCodeAdapter()
        result = adapter.execute("test prompt")
        assert result.success is False
        assert "not found" in result.error

    @patch("subprocess.run")
    def test_execute_text_event_fallback(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"type":"text","text":"hello world"}',
            stderr=""
        )
        adapter = OpenCodeAdapter()
        result = adapter.execute("test prompt")
        assert result.success is True
        assert result.final_message == "hello world"

    @patch("subprocess.run")
    def test_health_check_success(self, mock_run):
        mock_run.return_value = Mock(returncode=0)
        adapter = OpenCodeAdapter()
        assert adapter.health_check() is True

    @patch("subprocess.run")
    def test_health_check_failure(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        adapter = OpenCodeAdapter()
        assert adapter.health_check() is False

    @patch("subprocess.run")
    def test_health_check_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="opencode", timeout=10)
        adapter = OpenCodeAdapter()
        assert adapter.health_check() is False

    def test_extract_final_message_multiline(self):
        adapter = OpenCodeAdapter()
        output = '{"type":"start"}\n{"type":"end","content":"final answer"}'
        assert adapter._extract_final_message(output) == "final answer"

    def test_extract_final_message_no_end(self):
        adapter = OpenCodeAdapter()
        output = "raw text output"
        assert adapter._extract_final_message(output) == "raw text output"

    def test_extract_tokens_present(self):
        adapter = OpenCodeAdapter()
        output = '{"type":"end","content":"x","tokens":100}'
        assert adapter._extract_tokens(output) == 100

    def test_extract_tokens_absent(self):
        adapter = OpenCodeAdapter()
        output = '{"type":"start"}'
        assert adapter._extract_tokens(output) is None


class TestCodexAdapter:
    @patch("subprocess.run")
    def test_execute_success(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"role":"assistant","content":"result"}',
            stderr=""
        )
        adapter = CodexAdapter()
        result = adapter.execute("test prompt")
        assert result.success is True
        assert result.final_message == "result"

    @patch("subprocess.run")
    def test_execute_success_list_content(self, mock_run):
        content = [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({"role": "assistant", "content": content}),
            stderr=""
        )
        adapter = CodexAdapter()
        result = adapter.execute("test prompt")
        assert result.success is True
        assert result.final_message == "part1 part2"

    @patch("subprocess.run")
    def test_execute_nonzero_exit(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="err")
        adapter = CodexAdapter()
        result = adapter.execute("test prompt")
        assert result.success is False
        assert "Exit code 1" in result.error

    @patch("subprocess.run")
    def test_execute_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="codex", timeout=300)
        adapter = CodexAdapter()
        result = adapter.execute("test prompt")
        assert result.success is False
        assert "Timeout" in result.error

    @patch("subprocess.run")
    def test_execute_cli_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        adapter = CodexAdapter()
        result = adapter.execute("test prompt")
        assert result.success is False
        assert "not found" in result.error

    @patch("subprocess.run")
    def test_health_check_success(self, mock_run):
        mock_run.return_value = Mock(returncode=0)
        adapter = CodexAdapter()
        assert adapter.health_check() is True

    @patch("subprocess.run")
    def test_health_check_failure(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        adapter = CodexAdapter()
        assert adapter.health_check() is False

    def test_extract_final_message_multiline(self):
        adapter = CodexAdapter()
        output = '{"role":"user","content":"q"}\n{"role":"assistant","content":"answer"}'
        assert adapter._extract_final_message(output) == "answer"

    def test_extract_final_message_no_assistant(self):
        adapter = CodexAdapter()
        output = "raw fallback"
        assert adapter._extract_final_message(output) == "raw fallback"
