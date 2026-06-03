"""Tests for pipeline and config."""


import pytest

from agent_ci.config import DEFAULT_CONFIG, load_config
from agent_ci.pipeline import run_pipeline
from agent_ci.types import PipelineReport, Verdict


@pytest.mark.asyncio
async def test_pipeline_all_checkers(valid_output):
    """Pipeline should run all three checkers by default."""
    config = DEFAULT_CONFIG.copy()
    report = await run_pipeline(valid_output, config)
    assert isinstance(report, PipelineReport)
    assert report.schema is not None
    assert report.fact is not None
    assert report.diff is not None


@pytest.mark.asyncio
async def test_pipeline_selective(valid_output):
    """Should only run enabled checkers."""
    config = DEFAULT_CONFIG.copy()
    config["pipeline"] = {"enabled_checkers": ["schema"]}
    report = await run_pipeline(valid_output, config)
    assert report.schema is not None
    assert report.fact is None
    assert report.diff is None


@pytest.mark.asyncio
async def test_pipeline_unknown_checker_rejects(valid_output):
    """Unknown enabled checkers should fail instead of being silently skipped."""
    config = DEFAULT_CONFIG.copy()
    config["pipeline"] = {"enabled_checkers": ["scheam"]}

    report = await run_pipeline(valid_output, config)

    assert report.verdict == Verdict.REJECT
    assert report.extras is not None
    assert report.extras["scheam"].failed == 1
    assert "Unknown checker" in report.extras["scheam"].checks[0].message


@pytest.mark.asyncio
async def test_pipeline_verdict_pass(valid_output, baseline_dir):
    """Clean valid output with matching baseline should PASS."""
    config = DEFAULT_CONFIG.copy()
    config["diff"] = {"baseline": str(baseline_dir)}
    report = await run_pipeline(valid_output, config)
    # config.yaml is new → WARN, but rest matches baseline
    assert report.verdict in (Verdict.PASS, Verdict.PASS_WITH_WARNINGS)


@pytest.mark.asyncio
async def test_pipeline_verdict_reject(invalid_output):
    """Invalid output should REJECT."""
    config = DEFAULT_CONFIG.copy()
    report = await run_pipeline(invalid_output, config)
    assert report.verdict == Verdict.REJECT


@pytest.mark.asyncio
async def test_config_defaults():
    """Default config should have all expected keys."""
    config = DEFAULT_CONFIG
    assert "schema" in config
    assert "fact" in config
    assert "diff" in config
    assert "pipeline" in config
    assert config["pipeline"]["enabled_checkers"] == ["schema", "fact", "diff"]
    assert config["schema"]["security"]["enabled"] is True


def test_config_merge_none_skipped(tmp_path):
    """None values in user config should not override defaults."""
    config_path = tmp_path / ".agent-ci.yaml"
    config_path.write_text("pipeline:\n  fail_fast: true\n  enabled_checkers: null\n")
    config = load_config(config_path)
    # enabled_checkers was null → should keep default
    assert config["pipeline"]["enabled_checkers"] == ["schema", "fact", "diff"]
    assert config["pipeline"]["fail_fast"] is True


def test_config_merge_partial(tmp_path):
    """Partial user config should deep-merge with defaults."""
    config_path = tmp_path / ".agent-ci.yaml"
    config_path.write_text("""
schema:
  required_files:
    - output/result.json
    - output/log.txt
""")
    config = load_config(config_path)
    assert config["schema"]["required_files"] == ["output/result.json", "output/log.txt"]
    assert config["schema"]["security"]["enabled"] is True  # from defaults
