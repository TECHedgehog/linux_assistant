import unittest

import config


class ConfigTests(unittest.TestCase):
    def test_configuration_has_safe_defaults(self):
        self.assertTrue(config.OLLAMA_URL.startswith("http://"))
        self.assertTrue(config.MODEL)
        self.assertGreater(config.MAX_TOOL_ROUNDS, 0)
        self.assertGreater(config.COMMAND_TIMEOUT, 0)
        self.assertGreater(config.MAX_OUTPUT, 0)
        self.assertGreater(config.MAX_FILE_SIZE, 0)


if __name__ == "__main__":
    unittest.main()
