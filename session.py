"""Shared assistant conversation state for interactive frontends."""

from cli import SYSTEM_PROMPT
from supervisor import ask


class AssistantSession:
    """Keep one conversation and run it through the supervisor."""

    def __init__(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def submit(self, text, confirm_callback=None, tool_output=None):
        """Submit user text and return the assistant response."""
        text = text.strip()
        if not text:
            return ""
        self.messages.append({"role": "user", "content": text})
        try:
            answer = ask(
                self.messages,
                confirm_callback=confirm_callback,
                tool_output=tool_output,
            )
        except Exception:
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
            raise
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    def clear(self):
        """Start a new conversation without replacing this session object."""
        self.messages[:] = [{"role": "system", "content": SYSTEM_PROMPT}]
