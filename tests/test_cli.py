import unittest
from unittest.mock import patch

from cli import confirm_tool_call


class CliTests(unittest.TestCase):
    @patch("cli.input", return_value="yes")
    def test_confirmation_accepts_yes(self, _input):
        self.assertTrue(confirm_tool_call("run_command", {"command": "echo ok"}))

    @patch("cli.input", return_value="no")
    def test_confirmation_rejects_non_yes(self, _input):
        self.assertFalse(confirm_tool_call("run_command", {"command": "echo ok"}))


if __name__ == "__main__":
    unittest.main()
