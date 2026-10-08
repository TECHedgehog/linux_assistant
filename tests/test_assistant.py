import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

import assistant


class AssistantTests(unittest.TestCase):
    def test_normal_response(self):
        with patch.object(
            assistant,
            "ollama_request",
            return_value={"message": {"content": "Hello"}},
        ):
            self.assertEqual(assistant.ask([]), "Hello")

    def test_tool_call_is_executed_and_followed_by_answer(self):
        responses = iter(
            [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "system_info",
                                    "arguments": {},
                                }
                            }
                        ]
                    }
                },
                {"message": {"content": "System inspected."}},
            ]
        )

        with patch.object(assistant, "ollama_request", side_effect=responses), patch.object(
            assistant, "execute_tool", return_value={"hostname": "test-host"}
        ) as execute:
            messages = []
            self.assertEqual(assistant.ask(messages), "System inspected.")

        execute.assert_called_once_with(
            "system_info", {}, confirm_callback=assistant.confirm_tool_call
        )
        self.assertEqual(messages[-1]["role"], "tool")
        self.assertEqual(json.loads(messages[-1]["content"])["hostname"], "test-host")

    def test_malformed_response_is_rejected(self):
        with patch.object(assistant, "ollama_request", side_effect=RuntimeError("invalid JSON")):
            with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                assistant.ask([])

    def test_repeated_tool_call_is_not_executed_twice(self):
        call = {
            "function": {"name": "system_info", "arguments": {}}
        }
        responses = iter(
            [
                {"message": {"tool_calls": [call]}},
                {"message": {"tool_calls": [call]}},
                {"message": {"content": "Done"}},
            ]
        )

        with patch.object(assistant, "ollama_request", side_effect=responses), patch.object(
            assistant, "execute_tool", return_value={"ok": True}
        ) as execute:
            messages = []
            self.assertEqual(
                assistant.ask(messages),
                "The assistant stopped a repeated tool-call loop.",
            )

        execute.assert_called_once()
        duplicate = json.loads(messages[-1]["content"])
        self.assertIn("already been executed", duplicate["error"])

    def test_backend_failure_is_reported(self):
        error = urllib.error.URLError("connection refused")
        with patch.object(assistant, "ollama_request", side_effect=error):
            with self.assertRaisesRegex(urllib.error.URLError, "connection refused"):
                assistant.ask([])

    def test_ollama_request_rejects_invalid_message_shape(self):
        response = Mock()
        response.status = 200
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"message": "not an object"}'

        with patch.object(assistant.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid response"):
                assistant.ollama_request([])


if __name__ == "__main__":
    unittest.main()
