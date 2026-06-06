"""codex CLI 适配器。"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .base import BaseAdapter, CLIResult


class CodexAdapter(BaseAdapter):
    """codex CLI 适配器。

    命令: codex --ask-for-approval never ... exec [resume] --json ...
    解析: Codex 0.137.0 JSONL 事件协议
    """

    SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}

    def __init__(
        self,
        sandbox: str = "read-only",
        ephemeral: bool = False,
        output_schema: str | None = None,
        session_id: str | None = None,
    ) -> None:
        if sandbox not in self.SANDBOXES:
            raise ValueError(f"invalid codex sandbox: {sandbox}")
        if ephemeral and session_id:
            raise ValueError("codex adapter policy forbids ephemeral session resume")
        self.sandbox = sandbox
        self.ephemeral = ephemeral
        self.output_schema = output_schema
        self.session_id = session_id
        self.executable = shutil.which("codex") or "codex"

    def execute(self, prompt: str, workdir: str = ".", timeout: int = 300, verbose: bool = False) -> CLIResult:
        start_time = time.time()
        effective_workdir = str(Path(workdir).resolve())
        cmd = self._build_command(prompt, effective_workdir)

        try:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=effective_workdir
            )
            duration = time.time() - start_time

            if verbose:
                print(result.stdout)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)

            if result.returncode != 0:
                return CLIResult(
                    success=False,
                    final_message="",
                    raw_output=result.stdout + result.stderr,
                    error=f"Exit code {result.returncode}",
                    duration_seconds=duration
                )

            final_message = self._extract_final_message(result.stdout)
            tokens_used = self._extract_tokens(result.stdout)
            thread_id = self._extract_thread_id(result.stdout)

            if final_message is None:
                return CLIResult(
                    success=False,
                    final_message="",
                    raw_output=result.stdout,
                    error="Codex protocol error: no completed agent_message",
                    tokens_used=tokens_used,
                    metadata={"thread_id": thread_id} if thread_id else {},
                    duration_seconds=duration
                )

            return CLIResult(
                success=True,
                final_message=final_message,
                raw_output=result.stdout,
                tokens_used=tokens_used,
                metadata={"thread_id": thread_id} if thread_id else {},
                duration_seconds=duration
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return CLIResult(
                success=False,
                final_message="",
                raw_output="",
                error=f"Timeout after {timeout}s",
                duration_seconds=duration
            )
        except FileNotFoundError:
            return CLIResult(
                success=False,
                final_message="",
                raw_output="",
                error="codex CLI not found",
                duration_seconds=0
            )

    def health_check(self) -> bool:
        try:
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _build_command(self, prompt: str, workdir: str) -> list[str]:
        cmd = [
            self.executable,
            "--ask-for-approval", "never",
            "--sandbox", self.sandbox,
            "--cd", workdir,
            "exec",
        ]
        if self.session_id:
            cmd.append("resume")
        cmd.append("--json")
        if self.ephemeral:
            cmd.append("--ephemeral")
        if self.output_schema:
            schema_path = Path(self.output_schema)
            if not schema_path.is_absolute():
                schema_path = Path(workdir) / schema_path
            cmd.extend(["--output-schema", str(schema_path.resolve())])
        if self.session_id:
            cmd.append(self.session_id)
        cmd.append(prompt)
        return cmd

    def _events(self, output: str):
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event

    def _extract_final_message(self, output: str) -> str | None:
        """提取最后一个完成的 agent_message 文本。"""
        messages = []
        for event in self._events(output):
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
            ):
                messages.append(str(item.get("text", "")))
        return messages[-1] if messages else None

    def _extract_tokens(self, output: str) -> int | None:
        """提取最后一轮 input + output token，避免重复计算 cached input。"""
        usage = None
        for event in self._events(output):
            if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                usage = event["usage"]
        if usage is None:
            return None
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if not isinstance(input_tokens, int) and not isinstance(output_tokens, int):
            return None
        return (input_tokens if isinstance(input_tokens, int) else 0) + (
            output_tokens if isinstance(output_tokens, int) else 0
        )

    def _extract_thread_id(self, output: str) -> str | None:
        thread_id = None
        for event in self._events(output):
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                thread_id = event["thread_id"]
        return thread_id
