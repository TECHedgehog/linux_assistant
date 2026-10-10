import unittest
from unittest.mock import patch

from session import AssistantSession


class SessionTests(unittest.TestCase):
    @patch("session.ask", return_value="Done")
    def test_submit_keeps_conversation(self, ask):
        session = AssistantSession()

        self.assertEqual(session.submit("Check status"), "Done")

        self.assertEqual(session.messages[-2]["content"], "Check status")
        self.assertEqual(session.messages[-1]["content"], "Done")
        ask.assert_called_once()

    @patch("session.ask", side_effect=RuntimeError("offline"))
    def test_failed_submit_removes_pending_user_message(self, _ask):
        session = AssistantSession()

        with self.assertRaisesRegex(RuntimeError, "offline"):
            session.submit("Hello")

        self.assertEqual(len(session.messages), 1)

    def test_clear_keeps_system_message(self):
        session = AssistantSession()
        session.messages.append({"role": "user", "content": "old"})

        session.clear()

        self.assertEqual(len(session.messages), 1)
        self.assertEqual(session.messages[0]["role"], "system")


if __name__ == "__main__":
    unittest.main()
