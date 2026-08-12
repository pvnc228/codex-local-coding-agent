import unittest

from local_coding_agent.task import TaskEnvelope
from local_coding_agent.validators import validate_candidate


class CandidateValidatorTests(unittest.TestCase):
    def setUp(self):
        self.task = TaskEnvelope(
            id="validate-one",
            goal="изменить разрешённый файл",
            files=("src/allowed.py",),
            checks=("check allowed",),
        )
        self.patch = (
            "diff --git a/src/allowed.py b/src/allowed.py\n"
            "--- a/src/allowed.py\n"
            "+++ b/src/allowed.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 42\n"
            "+VALUE = 43\n"
        )

    def test_valid_candidate_reports_changed_allowlisted_files(self):
        report = validate_candidate(
            {
                "status": "candidate",
                "summary": "изменено значение",
                "patch": self.patch,
                "checks": [
                    {"command": "check allowed", "passed": True, "evidence": "runner exit 0"}
                ],
                "risks": [],
            },
            self.task,
            observed_checks={"check allowed": {"passed": True, "evidence": "runner exit 0"}},
        )

        self.assertTrue(report.valid)
        self.assertEqual(report.changed_files, ("src/allowed.py",))
        self.assertEqual(report.issues, ())

    def test_validator_rejects_out_of_scope_patch_and_untrusted_check(self):
        report = validate_candidate(
            {
                "status": "candidate",
                "summary": "опасное изменение",
                "patch": self.patch.replace("src/allowed.py", "secret.txt"),
                "checks": [
                    {"command": "Remove-Item *", "passed": True, "evidence": "claimed"}
                ],
                "risks": [],
            },
            self.task,
        )

        self.assertFalse(report.valid)
        self.assertTrue(any("allowlist" in issue for issue in report.issues))
        self.assertTrue(any("allowlisted" in issue for issue in report.issues))

    def test_validator_rejects_candidate_when_external_check_failed(self):
        report = validate_candidate(
            {
                "status": "candidate",
                "summary": "проверка не прошла",
                "patch": "",
                "checks": [
                    {"command": "check allowed", "passed": False, "evidence": "exit_code=1"}
                ],
                "risks": [],
            },
            self.task,
            observed_checks={"check allowed": {"passed": False, "evidence": "exit_code=1"}},
        )

        self.assertFalse(report.valid)
        self.assertIn("check failed: check allowed", report.issues)


if __name__ == "__main__":
    unittest.main()
