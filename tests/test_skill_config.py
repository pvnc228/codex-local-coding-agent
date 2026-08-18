import tempfile
import unittest
from pathlib import Path

from local_coding_agent.skill_config import (
    get_skill_content,
    integrate_skill_config,
)


class SkillConfigTests(unittest.TestCase):
    def test_get_skill_content_returns_valid_markdown(self):
        content = get_skill_content()
        self.assertIn("Local Coding Agent — AI Agent Delegation Skill", content)
        self.assertIn("delegate_code", content)
        self.assertIn("apply_proposal", content)

    def test_integrate_skill_config_print(self):
        res = integrate_skill_config(print_content=True)
        self.assertEqual(res["action"], "print")
        self.assertIn("name: local-coding-agent", res["content"])

    def test_integrate_skill_config_dry_run_and_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_target = Path(temp_dir) / "sub" / "SKILL.md"
            
            # Dry run
            dry = integrate_skill_config(target_path=custom_target, dry_run=True)
            self.assertEqual(dry["status"], "dry_run_preview")
            self.assertFalse(custom_target.exists())

            # Write
            write_res = integrate_skill_config(target_path=custom_target, dry_run=False)
            self.assertEqual(write_res["status"], "installed")
            self.assertTrue(custom_target.is_file())
            self.assertTrue(write_res["written"])
            
            content = custom_target.read_text(encoding="utf-8")
            self.assertIn("delegate_code", content)

    def test_integrate_skill_config_auto_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            res = integrate_skill_config(client="auto", workspace=temp_dir, dry_run=True)
            self.assertIn("results", res)
            clients = [r["client"] for r in res["results"]]
            self.assertIn("workspace", clients)


if __name__ == "__main__":
    unittest.main()
