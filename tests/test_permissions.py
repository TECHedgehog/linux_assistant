import unittest

from assistant import execute_tool, tool_risk
from tools import read_file, service_status


class PermissionTests(unittest.TestCase):
    def test_read_only_tool_is_allowed(self):
        self.assertEqual(tool_risk("system_info", {}), "ALLOW")

    def test_known_read_only_command_is_allowed(self):
        self.assertEqual(tool_risk("run_command", {"command": "uname -a"}), "ALLOW")

    def test_unknown_command_requires_confirmation(self):
        self.assertEqual(
            tool_risk("run_command", {"command": "echo hello"}),
            "CONFIRM",
        )

    def test_dangerous_command_is_denied(self):
        self.assertEqual(tool_risk("run_command", {"command": "sudo reboot"}), "DENY")

    def test_unknown_tool_is_denied(self):
        result = execute_tool("container.exec", {})
        self.assertTrue(result["denied"])
        self.assertEqual(result["risk"], "DENY")

    def test_service_changes_require_confirmation(self):
        self.assertEqual(
            tool_risk("restart_service", {"service": "ollama.service"}),
            "CONFIRM",
        )

    def test_invalid_service_name_is_rejected(self):
        result = service_status("ollama.service; reboot")
        self.assertIn("error", result)

    def test_declined_confirmation_does_not_execute(self):
        result = execute_tool(
            "run_command",
            {"command": "echo should-not-run"},
            confirm_callback=lambda name, arguments: False,
        )
        self.assertTrue(result["denied"])
        self.assertFalse(result["confirmed"])

    def test_shell_composition_is_denied(self):
        self.assertEqual(
            tool_risk("run_command", {"command": "echo safe; reboot"}),
            "DENY",
        )

    def test_leading_dash_service_name_is_rejected(self):
        result = service_status("--no-pager")
        self.assertIn("error", result)

    def test_sensitive_file_is_rejected(self):
        result = read_file("/etc/shadow")
        self.assertIn("error", result)

    def test_file_outside_approved_roots_is_rejected(self):
        result = read_file("/var/log/syslog")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
