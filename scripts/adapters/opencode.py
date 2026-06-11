"""opencode CLI 适配器。"""

import json
import subprocess
import sys
import time
from pathlib import Path
from .base import BaseAdapter, CLIResult


class OpenCodeAdapter(BaseAdapter):
    """opencode CLI 适配器。

    命令: opencode run --format json --dir <workdir> "<prompt>"
    解析: JSON 事件流，提取 type=end 时的 content
    """

    MAX_CMD_LENGTH = 8000

    def execute(self, prompt: str, workdir: str = ".", timeout: int = 300, verbose: bool = False) -> CLIResult:
        start_time = time.time()
        effective_workdir = str(Path(workdir).resolve())

        if len(prompt) > self.MAX_CMD_LENGTH:
            return CLIResult(
                success=False,
                final_message="",
                raw_output="",
                error=f"Prompt too long ({len(prompt)} chars, max {self.MAX_CMD_LENGTH}). "
                      f"opencode CLI does not support --prompt-file or stdin piping for prompts.",
                duration_seconds=0
            )

        cmd = ["opencode", "run", "--format", "json", "--dir", effective_workdir, prompt]

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

            # 解析 JSON 事件流
            final_message = self._extract_final_message(result.stdout)
            tokens_used = self._extract_tokens(result.stdout)

            return CLIResult(
                success=True,
                final_message=final_message,
                raw_output=result.stdout,
                tokens_used=tokens_used,
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
                error="opencode CLI not found",
                duration_seconds=0
            )

    def health_check(self) -> bool:
        try:
            result = subprocess.run(
                ["opencode", "--version"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _extract_final_message(self, output: str) -> str:
        """从 JSON 事件流中提取 type=end 时的 content。"""
        lines = output.strip().split("\n")
        for line in reversed(lines):
            try:
                event = json.loads(line)
                if event.get("type") == "end":
                    return event.get("content", "")
                if event.get("type") == "text":
                    return event.get("text", "")
            except json.JSONDecodeError:
                continue
        return output.strip()

    def _extract_tokens(self, output: str) -> int | None:
        """从 JSON 事件流中提取 token 消耗。"""
        lines = output.strip().split("\n")
        for line in reversed(lines):
            try:
                event = json.loads(line)
                if event.get("type") == "end":
                    return event.get("tokens")
            except json.JSONDecodeError:
                continue
        return None
