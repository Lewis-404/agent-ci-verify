"""Verification pipeline orchestrator with plugin support and parallel execution."""

import asyncio
from pathlib import Path
from typing import Any

from agent_ci.checkers import BaseChecker
from agent_ci.checkers.diff import DiffChecker
from agent_ci.checkers.fact import FactChecker
from agent_ci.checkers.integrity import IntegrityChecker
from agent_ci.checkers.schema import SchemaChecker
from agent_ci.plugins import discover_plugins
from agent_ci.types import CheckerReport, CheckResult, PipelineReport, Severity

# Built-in checkers
_BUILTIN_REGISTRY: dict[str, type[BaseChecker]] = {
    "schema": SchemaChecker,
    "fact": FactChecker,
    "diff": DiffChecker,
    "integrity": IntegrityChecker,
}

# Slot mapping for PipelineReport fields
_SLOT_MAP = {"schema": "schema", "fact": "fact", "diff": "diff"}


async def run_pipeline(output_dir: Path, config: dict[str, Any]) -> PipelineReport:
    """Run all enabled checkers against the output directory.

    Supports:
    - Built-in checkers (schema, fact, diff)
    - Plugin checkers (discovered from entry points or directories)
    - Parallel execution (config: pipeline.parallel = true)
    - Fail-fast (config: pipeline.fail_fast = true, sequential only)
    """
    report = PipelineReport()
    pipeline_cfg = config.get("pipeline", {})
    enabled = pipeline_cfg.get("enabled_checkers", ["schema", "fact", "diff"])
    fail_fast = pipeline_cfg.get("fail_fast", False)
    parallel = pipeline_cfg.get("parallel", True)

    # Merge built-in + plugin checkers
    registry = dict(_BUILTIN_REGISTRY)
    registry.update(discover_plugins(config))

    # Build checker instances
    tasks: list[tuple[str, BaseChecker]] = []
    for name in enabled:
        cls = registry.get(name)
        if cls is None:
            _assign_slot(report, name, _checker_error_report(
                name,
                f"Unknown checker '{name}' configured in pipeline.enabled_checkers",
            ))
            if fail_fast:
                return report
            continue
        tasks.append((name, cls(config=config)))

    if parallel and not fail_fast:
        # Run all checkers concurrently
        results = await asyncio.gather(
            *[checker.verify(output_dir) for _, checker in tasks],
            return_exceptions=True,
        )
        for (name, _), result in zip(tasks, results, strict=True):
            if isinstance(result, BaseException):
                # Checker crashed — create error report
                _assign_slot(
                    report,
                    name,
                    _checker_error_report(name, f"Checker '{name}' crashed: {result}"),
                )
            else:
                _assign_slot(report, name, result)
    else:
        # Sequential execution (needed for fail_fast)
        for name, checker in tasks:
            try:
                result = await checker.verify(output_dir)
            except Exception as e:
                result = _checker_error_report(name, f"Checker '{name}' crashed: {e}")
            _assign_slot(report, name, result)

            if fail_fast and result.failed > 0:
                break

    return report


def _checker_error_report(name: str, message: str) -> CheckerReport:
    """Create a failing checker report for pipeline-level errors."""
    report = CheckerReport(checker_name=name)
    report.checks.append(CheckResult(
        checker=name,
        check_name="checker_error",
        severity=Severity.FAIL,
        message=message,
    ))
    return report


def _assign_slot(report: PipelineReport, name: str, result: CheckerReport) -> None:
    """Map checker result to the correct PipelineReport field."""
    if name in _SLOT_MAP:
        setattr(report, _SLOT_MAP[name], result)
    else:
        # Plugin checker — store in extras
        if report.extras is None:
            report.extras = {}
        report.extras[name] = result
