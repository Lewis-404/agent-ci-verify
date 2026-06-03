"""Tests for HTML report generator."""

from pathlib import Path

import pytest

from agent_ci import __version__
from agent_ci.report import _build_table_rows, _escape_attr, generate_report
from agent_ci.types import (
    CheckerReport,
    CheckResult,
    PipelineReport,
    Severity,
)

# ── Fixtures ──────────────────────────────────────────────────────


def _make_check(name: str, severity: Severity, message: str = "") -> CheckResult:
    return CheckResult(
        checker="test",
        check_name=name,
        severity=severity,
        message=message or name,
    )


def _make_checker_report(
    name: str,
    passed: int = 0,
    warnings: int = 0,
    failed: int = 0,
) -> CheckerReport:
    checks: list[CheckResult] = []
    checks.extend(
        _make_check(f"{name}_pass_{i}", Severity.PASS) for i in range(passed)
    )
    checks.extend(
        _make_check(f"{name}_warn_{i}", Severity.WARN) for i in range(warnings)
    )
    checks.extend(
        _make_check(f"{name}_fail_{i}", Severity.FAIL) for i in range(failed)
    )
    return CheckerReport(checker_name=name, checks=checks)


@pytest.fixture
def pass_report() -> PipelineReport:
    return PipelineReport(
        schema=_make_checker_report("schema", passed=3),
        fact=_make_checker_report("fact", passed=2),
        diff=_make_checker_report("diff", passed=1),
    )


@pytest.fixture
def warn_report() -> PipelineReport:
    return PipelineReport(
        schema=_make_checker_report("schema", passed=2, warnings=1),
        fact=_make_checker_report("fact", passed=1),
        diff=_make_checker_report("diff", passed=1),
    )


@pytest.fixture
def reject_report() -> PipelineReport:
    return PipelineReport(
        schema=_make_checker_report("schema", passed=2),
        fact=_make_checker_report("fact", passed=1, failed=1),
        diff=_make_checker_report("diff", passed=1),
    )


# ── generate_report tests ─────────────────────────────────────────


def test_report_pass(pass_report: PipelineReport):
    html = generate_report(pass_report, Path("/tmp/output"))

    assert '<div class="verdict PASS">PASS</div>' in html
    assert "PASS WITH WARNINGS" not in html
    assert '<div class="verdict REJECT">' not in html
    assert '<div class="verdict WARN">' not in html
    assert "agent-ci-verify" in html


def test_report_warn(warn_report: PipelineReport):
    html = generate_report(warn_report, Path("/tmp/output"))

    assert "PASS WITH WARNINGS" in html
    assert 'class="verdict WARN"' in html


def test_report_reject(reject_report: PipelineReport):
    html = generate_report(reject_report, Path("/tmp/output"))

    assert "REJECT" in html
    assert 'class="verdict REJECT"' in html


def test_report_contains_version_default(pass_report: PipelineReport):
    html = generate_report(pass_report, Path("/tmp/output"))

    assert f"v{__version__}" in html


def test_report_custom_version(pass_report: PipelineReport):
    custom_version = "9.9.9-test"
    html = generate_report(pass_report, Path("/tmp/output"), version=custom_version)

    assert f"v{custom_version}" in html
    assert f"v{__version__}" not in html


def test_report_contains_timestamp(pass_report: PipelineReport):
    html = generate_report(pass_report, Path("/tmp/output"))

    assert "UTC" in html


def test_report_contains_output_dir(pass_report: PipelineReport):
    html = generate_report(pass_report, Path("/some/custom/path"))

    assert "/some/custom/path" in html


def test_report_summary_counts(pass_report: PipelineReport):
    html = generate_report(pass_report, Path("/tmp/output"))

    # 3 + 2 + 1 = 6 passed
    assert "6 Passed" in html
    assert "0 Warnings" in html
    assert "0 Failed" in html
    assert "Total checks: 6" in html


def test_report_with_extras():
    report = PipelineReport(
        schema=_make_checker_report("schema", passed=1),
        extras={"custom_plugin": _make_checker_report("custom", passed=1)},
    )

    html = generate_report(report, Path("/tmp/output"))

    assert "custom_plugin" in html
    assert "(plugin)" in html


def test_report_escapes_plugin_names_and_output_dir():
    report = PipelineReport(
        extras={"custom<script>": _make_checker_report("custom", passed=1)},
    )

    html = generate_report(report, Path("/tmp/<output>"))

    assert "custom&lt;script&gt;" in html
    assert "/tmp/&lt;output&gt;" in html
    assert "custom<script>" not in html
    assert "/tmp/<output>" not in html


def test_report_all_none_checkers():
    """If all built-in checkers are None, still produces valid HTML."""
    report = PipelineReport()

    html = generate_report(report, Path("/tmp/output"))

    assert "PASS" in html
    assert "Total checks: 0" in html


def test_generate_report_returns_string(pass_report: PipelineReport):
    result = generate_report(pass_report, Path("/tmp/output"))

    assert isinstance(result, str)
    assert result.startswith("<!DOCTYPE html>")


# ── _build_table_rows tests ───────────────────────────────────────


def test_build_table_rows_empty():
    report = CheckerReport(checker_name="empty")

    html = _build_table_rows(report)

    assert "No checks" in html


def test_build_table_rows_with_checks():
    report = CheckerReport(
        checker_name="test",
        checks=[
            _make_check("check_a", Severity.PASS, "passed"),
            _make_check("check_b", Severity.FAIL, "failed"),
        ],
    )

    html = _build_table_rows(report)

    assert "check_a" in html
    assert "check_b" in html
    assert 'class="badge pass"' in html
    assert 'class="badge fail"' in html


def test_build_table_rows_escapes_check_content():
    report = CheckerReport(
        checker_name="test",
        checks=[
            CheckResult(
                checker="test",
                check_name='bad"<script>',
                severity=Severity.FAIL,
                message="<img src=x onerror=alert(1)>",
                detail="<script>alert(1)</script>",
            ),
        ],
    )

    html = _build_table_rows(report)

    assert 'bad"&lt;script&gt;' in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "<script>alert(1)</script>" not in html


def test_build_table_rows_truncates_long_detail():
    report = CheckerReport(
        checker_name="test",
        checks=[
            CheckResult(
                checker="test",
                check_name="long",
                severity=Severity.PASS,
                message="ok",
                detail="x" * 200,
            ),
        ],
    )

    html = _build_table_rows(report)

    # Visible content truncated: 147 chars + "..."
    expected_truncated = "x" * 147 + "..."
    assert expected_truncated in html
    # The full 200 chars live in the title="" attribute — that's OK.
    # Verify the visible portion (between ><) is truncated:
    visible = html.split(">")[2].split("<")[0] if html.count(">") >= 3 else ""
    assert len(visible) <= 150  # 147 + "..."


# ── _escape_attr tests ────────────────────────────────────────────


def test_escape_attr_ampersand():
    assert _escape_attr("a & b") == "a &amp; b"


def test_escape_attr_quote():
    assert _escape_attr('say "hello"') == "say &quot;hello&quot;"


def test_escape_attr_angle_brackets():
    assert _escape_attr("<script>") == "&lt;script&gt;"


def test_escape_attr_no_change():
    assert _escape_attr("plain text") == "plain text"
