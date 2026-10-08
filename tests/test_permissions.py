import unittest
import tempfile
from pathlib import Path

from assistant import execute_tool, tool_risk
from tools import apply_file_edit, preview_file_edit, read_file, service_status


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

    def test_file_edit_preview_does_not_modify_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.txt"
            path.write_text("before\n", encoding="utf-8")
            result = preview_file_edit(str(path), "after\n")
            self.assertTrue(result["changed"])
            self.assertIn("-before", result["diff"])
            self.assertEqual(path.read_text(encoding="utf-8"), "before\n")

    def test_file_edit_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.txt"
            path.write_text("before\n", encoding="utf-8")
            result = execute_tool(
                "apply_file_edit", {"path": str(path), "content": "after\n"},
                confirm_callback=lambda name, arguments: False,
            )
            self.assertTrue(result["denied"])
            self.assertEqual(path.read_text(encoding="utf-8"), "before\n")

    def test_file_edit_creates_backup_and_detects_stale_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.txt"
            path.write_text("before\n", encoding="utf-8")
            preview = preview_file_edit(str(path), "after\n")
            path.write_text("changed\n", encoding="utf-8")
            stale = apply_file_edit(str(path), "after\n", preview["old_sha256"])
            self.assertIn("changed since preview", stale["error"])

            path.write_text("before\n", encoding="utf-8")
            result = apply_file_edit(str(path), "after\n", preview["old_sha256"])
            self.assertTrue(result["changed"])
            self.assertEqual(path.read_text(encoding="utf-8"), "after\n")
            self.assertEqual(Path(result["backup_path"]).read_text(encoding="utf-8"), "before\n")

    def test_file_edit_policy_requires_confirmation(self):
        self.assertEqual(tool_risk("preview_file_edit", {}), "ALLOW")
        self.assertEqual(tool_risk("apply_file_edit", {}), "CONFIRM")

    def test_file_edit_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.txt"
            link = Path(directory) / "link.txt"
            target.write_text("before\n", encoding="utf-8")
            link.symlink_to(target)
            result = preview_file_edit(str(link), "after\n")
            self.assertIn("Symbolic-link", result["error"])


if __name__ == "__main__":
    unittest.main()
