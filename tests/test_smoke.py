"""Tests for the interactive smoke test module."""

import unittest
from unittest.mock import MagicMock, patch

from local_coding_agent.smoke import run_smoke_test


class TestSmoke(unittest.TestCase):
    def test_run_smoke_mock_success(self):
        result = run_smoke_test(use_mock=True, verbose=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "accepted")
        self.assertIn("steps", result)
        self.assertTrue(all(step["status"] == "ok" for step in result["steps"]))
        self.assertTrue(result["tps"] > 0)

    def test_run_smoke_real_client_fallback_to_mock_when_no_ollama(self):
        with patch("local_coding_agent.smoke.OllamaClient") as mock_client_cls:
            instance = MagicMock()
            instance.available_models.side_effect = Exception("Ollama offline")
            mock_client_cls.return_value = instance

            result = run_smoke_test(use_mock=False, fallback_to_mock=True, verbose=False)
            self.assertTrue(result["success"])
            self.assertTrue(result.get("mock_fallback", False))


if __name__ == "__main__":
    unittest.main()
