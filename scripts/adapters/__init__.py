"""框架适配器包。"""

from .base import BaseAdapter, CLIResult


def get_adapter(framework: str, **options) -> BaseAdapter:
    """获取指定框架的适配器实例。"""
    if framework == "opencode":
        from .opencode import OpenCodeAdapter
        return OpenCodeAdapter()
    elif framework == "codex":
        from .codex import CodexAdapter
        return CodexAdapter(**options)
    else:
        raise ValueError(f"Unknown framework: {framework}")


__all__ = ["BaseAdapter", "CLIResult", "get_adapter"]
