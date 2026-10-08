import unittest

from policy import command_denial_reason, parse_command, tool_risk


class PolicyTests(unittest.TestCase):
    def test_parse_command_supports_quoted_arguments(self):
        self.assertEqual(parse_command('echo "hello world"'), ["echo", "hello world"])

    def test_parse_command_rejects_invalid_input(self):
        self.assertIsNone(parse_command("echo 'unterminated"))
        self.assertIsNone(parse_command(""))

    def test_destructive_and_composed_commands_are_denied(self):
        self.assertIn("blocked", command_denial_reason("rm file"))
        self.assertEqual(
            command_denial_reason("printf safe | tee file"),
            "Shell composition is blocked",
        )

    def test_read_only_commands_are_allowed(self):
        self.assertEqual(tool_risk("run_command", {"command": "ps aux"}), "ALLOW")

    def test_unknown_tools_are_denied(self):
        self.assertEqual(tool_risk("not_a_tool", {}), "DENY")


if __name__ == "__main__":
    unittest.main()
