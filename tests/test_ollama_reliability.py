import io
import json
import socket
import unittest
import urllib.error
from unittest.mock import patch

import assistant


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body.encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class OllamaRequestTests(unittest.TestCase):
    def response(self, message=None):
        return FakeResponse(json.dumps({"message": message or {"content": "ok"}}))

    @patch("assistant.urllib.request.urlopen")
    def test_valid_response_is_returned(self, urlopen):
        urlopen.return_value = self.response({"content": "hello", "tool_calls": []})

        result = assistant.ollama_request([])

        self.assertEqual(result["message"]["content"], "hello")
        urlopen.assert_called_once()
        self.assertEqual(urlopen.call_args.kwargs["timeout"], assistant.OLLAMA_TIMEOUT)

    @patch("assistant.time.sleep")
    @patch("assistant.urllib.request.urlopen")
    def test_connection_failure_retries_then_succeeds(self, urlopen, sleep):
        urlopen.side_effect = [
            urllib.error.URLError("connection refused"),
            self.response({"content": "recovered", "tool_calls": []}),
        ]

        result = assistant.ollama_request([])

        self.assertEqual(result["message"]["content"], "recovered")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    @patch("assistant.time.sleep")
    @patch("assistant.urllib.request.urlopen")
    def test_timeout_exhausts_bounded_retries(self, urlopen, sleep):
        urlopen.side_effect = socket.timeout("timed out")

        with self.assertRaisesRegex(RuntimeError, "Could not connect to Ollama"):
            assistant.ollama_request([])

        self.assertEqual(urlopen.call_count, assistant.OLLAMA_RETRIES + 1)
        self.assertEqual(sleep.call_count, assistant.OLLAMA_RETRIES)

    @patch("assistant.urllib.request.urlopen")
    def test_http_error_is_not_retried(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            assistant.OLLAMA_URL,
            403,
            "denied",
            {},
            io.BytesIO(b"access denied"),
        )

        with self.assertRaisesRegex(RuntimeError, "Ollama HTTP 403"):
            assistant.ollama_request([])

        urlopen.assert_called_once()

    @patch("assistant.urllib.request.urlopen")
    def test_non_success_response_status_is_rejected(self, urlopen):
        urlopen.return_value = FakeResponse('{"message": {"content": "no"}}', status=503)

        with self.assertRaisesRegex(RuntimeError, "HTTP status 503"):
            assistant.ollama_request([])

        urlopen.assert_called_once()

    @patch("assistant.urllib.request.urlopen")
    def test_invalid_json_is_not_retried(self, urlopen):
        urlopen.return_value = FakeResponse("not json")

        with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
            assistant.ollama_request([])

        urlopen.assert_called_once()

    @patch("assistant.urllib.request.urlopen")
    def test_invalid_message_shape_is_rejected(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({"message": {"content": 42}}))

        with self.assertRaisesRegex(RuntimeError, "content must be text"):
            assistant.ollama_request([])


class ToolCallValidationTests(unittest.TestCase):
    def test_malformed_arguments_do_not_execute_tool(self):
        messages = []
        response = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "list_directory",
                            "arguments": "not-json",
                        }
                    }
                ],
            }
        }

        with patch("assistant.ollama_request", side_effect=[response, {"message": {"content": "done"}}]), patch(
            "assistant.execute_tool"
        ) as execute_tool:
            result = assistant.ask(messages)

        self.assertEqual(result, "done")
        execute_tool.assert_not_called()
        self.assertIn("was not executed", messages[-1]["content"])

    def test_malformed_tool_call_does_not_crash_or_execute(self):
        messages = []
        response = {
            "message": {"content": "", "tool_calls": [{"function": "bad"}]}
        }

        with patch("assistant.ollama_request", side_effect=[response, {"message": {"content": "done"}}]), patch(
            "assistant.execute_tool"
        ) as execute_tool:
            result = assistant.ask(messages)

        self.assertEqual(result, "done")
        execute_tool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
