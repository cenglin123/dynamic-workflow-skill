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
    @pytest.fixture(autouse=True)
    def codex_executable(self):
        with patch("shutil.which", return_value="codex"):
            yield

    @pytest.fixture
    def codex_jsonl(self):
        fixture = Path(__file__).parent / "fixtures" / "codex-0.137.0-basic.jsonl"
        return fixture.read_text(encoding="utf-8")

    @patch("subprocess.run")
    def test_execute_extracts_real_protocol_metadata(self, mock_run, codex_jsonl):
        mock_run.return_value = Mock(
            returncode=0,
            stdout=codex_jsonl,
            stderr=""
        )
        adapter = CodexAdapter()
        result = adapter.execute("test prompt", workdir="workspace")
        assert result.success is True
        assert result.final_message == "中文测试"
        assert result.tokens_used == 12271
        assert result.metadata["thread_id"] == "019e9d61-95b7-7dd3-8557-7e76670bb7ae"

        expected_workdir = str(Path("workspace").resolve())
        cmd = mock_run.call_args.args[0]
        assert cmd == [
            "codex",
            "--ask-for-approval", "never",
            "--sandbox", "read-only",
            "--cd", expected_workdir,
            "exec",
            "--json",
            "test prompt",
        ]
        kwargs = mock_run.call_args.kwargs
        assert kwargs["cwd"] == expected_workdir
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"

    def test_extracts_last_agent_message_and_skips_malformed_lines(self, codex_jsonl):
        adapter = CodexAdapter()
        output = "\n".join([
            codex_jsonl.rstrip(),
            "not-json",
            json.dumps({
                "type": "item.completed",
                "item": {"id": "item_1", "type": "agent_message", "text": "最后一条中文消息"},
            }, ensure_ascii=False),
        ])
        assert adapter._extract_final_message(output) == "最后一条中文消息"

    @patch("subprocess.run")
    def test_execute_nonzero_exit(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="err")
        adapter = CodexAdapter()
        result = adapter.execute("test prompt")
        assert result.success is False
        assert "Exit code 1" in result.error

    @patch("subprocess.run")
    def test_execute_rejects_success_exit_without_completed_agent_message(self, mock_run):
        output = "\n".join([
            '{"type":"thread.started","thread_id":"thread-id"}',
            '{"type":"turn.started"}',
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}',
        ])
        mock_run.return_value = Mock(returncode=0, stdout=output, stderr="")

        result = CodexAdapter().execute("test prompt")

        assert result.success is False
        assert result.final_message == ""
        assert result.raw_output == output
        assert "protocol" in result.error.lower()
        assert "agent_message" in result.error

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

    def test_extract_final_message_no_assistant(self):
        adapter = CodexAdapter()
        output = "raw fallback"
        assert adapter._extract_final_message(output) is None

    @patch("subprocess.run")
    def test_builds_ephemeral_schema_workspace_write_command(self, mock_run, codex_jsonl):
        mock_run.return_value = Mock(returncode=0, stdout=codex_jsonl, stderr="")
        adapter = CodexAdapter(
            sandbox="workspace-write",
            ephemeral=True,
            output_schema="schemas/result.json",
        )

        adapter.execute("write files", workdir="repo")

        expected_workdir = str(Path("repo").resolve())
        expected_schema = str((Path(expected_workdir) / "schemas" / "result.json").resolve())
        assert mock_run.call_args.args[0] == [
            "codex",
            "--ask-for-approval", "never",
            "--sandbox", "workspace-write",
            "--cd", expected_workdir,
            "exec",
            "--json",
            "--ephemeral",
            "--output-schema", expected_schema,
            "write files",
        ]

    @patch("subprocess.run")
    def test_normalizes_relative_workdir_to_one_absolute_path(
        self, mock_run, codex_jsonl, tmp_path, monkeypatch
    ):
        mock_run.return_value = Mock(returncode=0, stdout=codex_jsonl, stderr="")
        repo = tmp_path / "repo"
        repo.mkdir()
        monkeypatch.chdir(tmp_path)

        CodexAdapter().execute("inspect", workdir="repo")

        expected = str(repo.resolve())
        assert mock_run.call_args.kwargs["cwd"] == expected
        cmd = mock_run.call_args.args[0]
        assert cmd[cmd.index("--cd") + 1] == expected

    @patch("subprocess.run")
    def test_resolves_relative_schema_against_effective_workdir(
        self, mock_run, codex_jsonl, tmp_path, monkeypatch
    ):
        mock_run.return_value = Mock(returncode=0, stdout=codex_jsonl, stderr="")
        repo = tmp_path / "repo"
        repo.mkdir()
        monkeypatch.chdir(tmp_path)

        CodexAdapter(output_schema="schemas/result.json").execute(
            "inspect", workdir="repo"
        )

        expected_schema = str((repo / "schemas" / "result.json").resolve())
        cmd = mock_run.call_args.args[0]
        assert cmd[cmd.index("--output-schema") + 1] == expected_schema

    @patch("subprocess.run")
    def test_builds_resume_command(self, mock_run, codex_jsonl):
        mock_run.return_value = Mock(returncode=0, stdout=codex_jsonl, stderr="")
        adapter = CodexAdapter(
            sandbox="read-only",
            session_id="019e9d61-95b7-7dd3-8557-7e76670bb7ae",
            output_schema="schemas/result.json",
        )

        adapter.execute("continue", workdir="repo")

        expected_workdir = str(Path("repo").resolve())
        expected_schema = str((Path(expected_workdir) / "schemas" / "result.json").resolve())
        assert mock_run.call_args.args[0] == [
            "codex",
            "--ask-for-approval", "never",
            "--sandbox", "read-only",
            "--cd", expected_workdir,
            "exec",
            "resume",
            "--json",
            "--output-schema", expected_schema,
            "019e9d61-95b7-7dd3-8557-7e76670bb7ae",
            "continue",
        ]

    def test_rejects_ephemeral_resume(self):
        with pytest.raises(ValueError, match="ephemeral.*resume"):
            CodexAdapter(ephemeral=True, session_id="thread-id")

    def test_rejects_unknown_sandbox(self):
        with pytest.raises(ValueError, match="sandbox"):
            CodexAdapter(sandbox="unknown")

    @patch("subprocess.run")
    def test_resolves_windows_command_shim(self, mock_run, codex_jsonl):
        mock_run.return_value = Mock(returncode=0, stdout=codex_jsonl, stderr="")
        with patch("shutil.which", return_value=r"C:\tools\codex.CMD"):
            adapter = CodexAdapter(ephemeral=True)
            adapter.execute("test")

        assert mock_run.call_args.args[0][0] == r"C:\tools\codex.CMD"
