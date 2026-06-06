"""框架适配器抽象基类。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CLIResult:
    """CLI 执行结果。"""
    success: bool
    final_message: str       # 提取的最终消息（存入 state.json）
    raw_output: str          # 完整输出（存入日志文件）
    error: str | None = None # 错误信息（如有）
    tokens_used: int | None = None  # token 消耗（如 CLI 提供）
    duration_seconds: float = 0.0   # 执行耗时
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAdapter(ABC):
    """框架适配器抽象基类。"""

    @abstractmethod
    def execute(self, prompt: str, workdir: str = ".", timeout: int = 300, verbose: bool = False) -> CLIResult:
        """执行 agent 任务，返回结构化结果。

        Args:
            prompt: 自足的 agent 指令
            workdir: 工作目录
            timeout: 超时秒数
            verbose: 是否实时显示 CLI 输出
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """检查 CLI 是否可用。"""
        ...
