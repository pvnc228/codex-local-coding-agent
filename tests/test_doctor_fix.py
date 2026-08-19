"""Unit tests for Self-Healing Environment & Auto-Pulling (R21 doctor --fix)."""

import pytest
from local_coding_agent.doctor import diagnose_environment, remediate_environment, DoctorFixReport


def test_diagnose_environment_runs():
    report = diagnose_environment()
    assert report is not None
    assert len(report.checks) > 0


def test_remediate_environment_dry_run():
    fix_report = remediate_environment(write=False)
    assert isinstance(fix_report, DoctorFixReport)
    assert fix_report.success is True
    assert isinstance(fix_report.actions, list)
    assert isinstance(fix_report.recommendations, list)


def test_remediate_environment_renders_text():
    fix_report = remediate_environment(write=False)
    text = fix_report.render_text()
    assert "System Remediation" in text
    assert "Recommended Model Pulls" in text
