import unittest
from unittest.mock import patch

import assistant


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.system = {"role": "system", "content": "system"}

    def test_preserves_system_and_removes_oldest_complete_exchanges(self):
        messages = [
            self.system,
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "system_info"}}]},
            {"role": "tool", "content": "old tool result"},
            {"role": "user", "content": "current"},
            {"role": "assistant", "content": "current answer"},
        ]

        assistant.trim_history(messages, max_messages=4, max_tokens=0)

        self.assertIs(messages[0], self.system)
        self.assertEqual([message["role"] for message in messages[1:]], ["user", "assistant"])
        self.assertEqual(messages[1]["content"], "current")

    def test_keeps_active_tool_context_together(self):
        messages = [
            self.system,
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current"},
            {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "system_info", "arguments": {}}}],
            },
            {"role": "tool", "content": "current tool result"},
        ]

        assistant.trim_history(messages, max_messages=4, max_tokens=0)

        self.assertEqual(messages[1]["content"], "current")
        self.assertEqual(
            [message["role"] for message in messages[1:]],
            ["user", "assistant", "tool"],
        )

    def test_trims_to_approximate_token_budget(self):
        messages = [
            self.system,
            {"role": "user", "content": "x" * 100},
            {"role": "assistant", "content": "y" * 100},
            {"role": "user", "content": "new"},
            {"role": "assistant", "content": "answer"},
        ]
        budget = assistant.approximate_tokens(self.system) + sum(
            assistant.approximate_tokens(message) for message in messages[-2:]
        )

        assistant.trim_history(messages, max_messages=0, max_tokens=budget)

        self.assertEqual(messages[1]["content"], "new")


class ToolLoopLimitTests(unittest.TestCase):
    def test_repeated_tool_call_stops_without_more_model_requests(self):
        tool_response = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "system_info",
                            "arguments": {},
                        }
                    }
                ],
            }
        }
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "inspect"},
        ]

        with patch("assistant.ollama_request", side_effect=[tool_response, tool_response]):
            with patch("assistant.execute_tool", return_value={"ok": True}) as execute_tool:
                result = assistant.ask(messages)

        self.assertEqual(result, "The assistant stopped a repeated tool-call loop.")
        execute_tool.assert_called_once_with(
            "system_info", {}, confirm_callback=assistant.confirm_tool_call
        )
        self.assertEqual(len(messages), 6)
        self.assertEqual(messages[-1]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
