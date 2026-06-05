"""codex CLI 适配器。"""

import json
import subprocess
import sys
import time
from .base import BaseAdapter, CLIResult


class CodexAdapter(BaseAdapter):
    """codex CLI 适配器。

    命令: codex exec --json -C <workdir> "<prompt>"
    解析: JSONL，提取最后一条 role=assistant 的 content
    """

    def execute(self, prompt: str, workdir: str = ".", timeout: int = 300, verbose: bool = False) -> CLIResult:
        start_time = time.time()
        cmd = ["codex", "exec", "--json", "-C", workdir, prompt]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workdir
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

            # 解析 JSONL
            final_message = self._extract_final_message(result.stdout)

            return CLIResult(
                success=True,
                final_message=final_message,
                raw_output=result.stdout,
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
                ["codex", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _extract_final_message(self, output: str) -> str:
        """从 JSONL 中提取最后一条 role=assistant 的 content。"""
        lines = output.strip().split("\n")
        for line in reversed(lines):
            try:
                event = json.loads(line)
                if event.get("role") == "assistant":
                    content = event.get("content", "")
                    if isinstance(content, list):
                        return " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                    return str(content)
            except json.JSONDecodeError:
                continue
        return output.strip()
