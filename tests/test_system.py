import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import (
    disk_usage,
    list_directory,
    open_app,
    read_file,
    run_command,
    service_logs,
    service_status,
)
from tools import system


class SystemToolTests(unittest.TestCase):
    def test_read_file_and_list_directory_use_safe_paths(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            path = Path(directory) / "note.txt"
            path.write_text("hello", encoding="utf-8")

            self.assertEqual(read_file(str(path))["content"], "hello")
            names = [entry["name"] for entry in list_directory(directory)["entries"]]
            self.assertEqual(names, ["note.txt"])

    def test_disk_usage_returns_path_and_sizes(self):
        result = disk_usage("/tmp")
        self.assertEqual(result["path"], "/tmp")
        self.assertIn("free_gb", result)

    def test_run_command_returns_subprocess_result(self):
        result = run_command("printf hello")
        self.assertEqual(result["return_code"], 0)
        self.assertEqual(result["stdout"], "hello")

    def test_open_app_rejects_unknown_application(self):
        result = open_app("unknown-app")
        self.assertIn("error", result)
        self.assertIn("unknown-app", result["error"])

    def test_service_tools_validate_names_and_lines(self):
        self.assertIn("error", service_status("bad/service"))
        self.assertIn("error", service_logs("ollama.service", lines=0))

    @patch.object(system, "subprocess")
    def test_service_status_builds_safe_systemctl_command(self, subprocess):
        subprocess.run.return_value.returncode = 0
        subprocess.run.return_value.stdout = "active"
        subprocess.run.return_value.stderr = ""

        result = service_status("ollama.service")

        self.assertEqual(result["return_code"], 0)
        subprocess.run.assert_called_once_with(
            ["systemctl", "status", "--no-pager", "--full", "ollama.service"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
