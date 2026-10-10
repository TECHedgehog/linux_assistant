"""Compatibility entry point for Liam."""

from cli import confirm_tool_call, main
from config import OLLAMA_RETRIES, OLLAMA_TIMEOUT, OLLAMA_URL
from model import ollama_request
from policy import tool_risk
from supervisor import ask as _ask, execute_tool
import time
import urllib


def approximate_tokens(message):
    """Estimate message token usage for compatibility with the old API."""
    return max(1, len(str(message.get("content", ""))) // 4)


def trim_history(messages, max_messages, max_tokens):
    """Trim old complete exchanges while preserving the system message."""
    if not messages:
        return
    system = messages[:1] if messages[0].get("role") == "system" else []
    rest = messages[1:] if system else messages[:]
    while rest and ((max_messages and len(system) + len(rest) > max_messages) or
                    (max_tokens and sum(approximate_tokens(m) for m in system + rest) > max_tokens)):
        if rest[0].get("role") == "tool":
            rest.pop(0)
            continue
        end = 1
        while end < len(rest) and rest[end].get("role") != "user":
            end += 1
        del rest[:end]
    messages[:] = system + rest


def ask(messages):
    """Compatibility wrapper that keeps old monkey-patching points working."""
    return _ask(messages, confirm_callback=confirm_tool_call,
                model_request=ollama_request, execute_tool_fn=execute_tool)


__all__ = ["ask", "approximate_tokens", "execute_tool", "main", "ollama_request",
           "tool_risk", "trim_history"]


if __name__ == "__main__":
    main()
