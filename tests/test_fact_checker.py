"""Tests for Fact Checker."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_ci.checkers.fact import FactChecker
from agent_ci.types import Severity


@pytest.fixture
def checker():
    return FactChecker()


@pytest.mark.asyncio
async def test_file_existence_valid(valid_output, checker):
    """Verify file count for existing pattern."""
    config = {
        "fact": {
            "files": [
                {"pattern": "*.json", "expected_count": 1}
            ]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(valid_output)
    file_count = [c for c in report.checks if c.check_name == "fact:file_count"]
    assert any(c.severity == Severity.PASS for c in file_count)


@pytest.mark.asyncio
async def test_file_existence_mismatch(valid_output):
    """Verify wrong expected count triggers failure."""
    config = {
        "fact": {
            "files": [
                {"pattern": "*.json", "expected_count": 999}
            ]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(valid_output)
    file_count = [c for c in report.checks if c.check_name == "fact:file_count"]
    assert any(c.severity == Severity.FAIL for c in file_count)


@pytest.mark.asyncio
async def test_min_size_check(tmp_path):
    """Verify files below min size trigger warning."""
    (tmp_path / "tiny.json").write_text("{}")
    config = {
        "fact": {
            "files": [
                {"pattern": "*.json", "min_size_bytes": 100}
            ]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)
    size_checks = [c for c in report.checks if c.check_name == "fact:file_size"]
    assert any(c.severity == Severity.WARN for c in size_checks)


@pytest.mark.asyncio
async def test_content_contains(tmp_path):
    """Verify content contains check passes."""
    (tmp_path / "result.json").write_text(json.dumps({"status": "success"}))
    config = {
        "fact": {
            "files": [{
                "pattern": "result.json",
                "content_checks": [{"type": "contains", "value": "success"}]
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)
    content = [c for c in report.checks if c.check_name == "fact:content_contains"]
    assert any(c.severity == Severity.PASS for c in content)


@pytest.mark.asyncio
async def test_content_contains_fail(tmp_path):
    """Verify missing content triggers failure."""
    (tmp_path / "result.json").write_text(json.dumps({"status": "error"}))
    config = {
        "fact": {
            "files": [{
                "pattern": "result.json",
                "content_checks": [{"type": "contains", "value": "nonexistent_value"}]
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)
    content = [c for c in report.checks if c.check_name == "fact:content_contains"]
    assert any(c.severity == Severity.FAIL for c in content)


@pytest.mark.asyncio
async def test_content_not_contains(tmp_path):
    """Verify forbidden content triggers failure."""
    (tmp_path / "result.json").write_text(json.dumps({"error": "panic: null pointer"}))
    config = {
        "fact": {
            "files": [{
                "pattern": "result.json",
                "content_checks": [{"type": "not_contains", "value": "panic"}]
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)
    content = [c for c in report.checks if c.check_name == "fact:content_not_contains"]
    assert any(c.severity == Severity.FAIL for c in content)


@pytest.mark.asyncio
async def test_api_check_skipped_no_endpoint(valid_output):
    """Empty API config should skip gracefully."""
    config = {"fact": {"api": [{}]}}
    checker = FactChecker(config=config)
    report = await checker.verify(valid_output)
    api_checks = [c for c in report.checks if c.check_name == "fact:api"]
    assert len(api_checks) == 1
    assert api_checks[0].severity == Severity.WARN


@pytest.mark.asyncio
async def test_api_check_success():
    """Verify API check success without depending on external network."""
    mock_client = _mock_async_client(response_status=200, response_text="ok")
    config = {
        "fact": {
            "api": [{
                "endpoint": "https://example.com/get",
                "method": "GET",
                "expected_status": 200,
                "timeout": 10,
            }]
        }
    }
    checker = FactChecker(config=config)
    with patch("httpx.AsyncClient", return_value=mock_client):
        report = await checker.verify(Path("/tmp"))

    api_checks = [c for c in report.checks if c.check_name == "fact:api"]
    assert len(api_checks) == 1
    assert api_checks[0].severity == Severity.PASS
    mock_client.get.assert_called_once_with("https://example.com/get")


@pytest.mark.asyncio
async def test_api_check_timeout():
    """Verify timeout handling."""
    mock_client = _mock_async_client(
        side_effect=httpx.TimeoutException("timed out")
    )
    config = {
        "fact": {
            "api": [{
                "endpoint": "https://example.com/delay/5",
                "method": "GET",
                "expected_status": 200,
                "timeout": 1,
            }]
        }
    }
    checker = FactChecker(config=config)
    with patch("httpx.AsyncClient", return_value=mock_client):
        report = await checker.verify(Path("/tmp"))

    api_checks = [c for c in report.checks if c.check_name == "fact:api"]
    assert len(api_checks) == 1
    assert api_checks[0].severity == Severity.FAIL
    assert "timeout" in api_checks[0].message.lower()


@pytest.mark.asyncio
async def test_llm_judge_no_file(valid_output):
    """LLM judge without file should warn."""
    config = {"fact": {"llm_judge": [{"rubric": "test"}]}}
    checker = FactChecker(config=config)
    report = await checker.verify(valid_output)
    judge = [c for c in report.checks if c.check_name == "fact:llm_judge"]
    assert len(judge) == 1
    assert judge[0].severity == Severity.WARN


@pytest.mark.asyncio
async def test_llm_judge_no_matching_files(valid_output):
    """LLM judge with non-matching pattern should fail."""
    config = {
        "fact": {
            "llm_judge": [{"file": "nonexistent_*.json", "rubric": "test"}]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(valid_output)
    judge = [c for c in report.checks if c.check_name == "fact:llm_judge"]
    assert len(judge) == 1
    assert judge[0].severity == Severity.FAIL


@pytest.mark.asyncio
async def test_llm_judge_no_llm_installed(valid_output):
    """LLM judge without openai/litellm should warn gracefully."""
    config = {
        "fact": {
            "llm_judge": [{"file": "result.json", "rubric": "Check correctness"}]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(valid_output)
    judge = [c for c in report.checks if c.check_name == "fact:llm_judge"]
    assert len(judge) >= 1
    # Should fail or warn since no LLM is installed
    assert judge[0].severity in (Severity.WARN, Severity.FAIL)


# ═══════════════════════════════════════════════════════════════════════════
# API checker — mocked tests (error paths and non-GET methods)
# ═══════════════════════════════════════════════════════════════════════════

def _mock_async_client(response_status=200, response_text="ok", side_effect=None):
    """Build a mocked httpx.AsyncClient with configurable response/error."""
    mock_response = MagicMock()
    mock_response.status_code = response_status
    mock_response.text = response_text

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client

    if side_effect:
        mock_client.get.side_effect = side_effect
        mock_client.post.side_effect = side_effect
        mock_client.request.side_effect = side_effect
    else:
        mock_client.get.return_value = mock_response
        mock_client.post.return_value = mock_response
        mock_client.request.return_value = mock_response

    return mock_client


@pytest.mark.asyncio
async def test_api_check_post_method(tmp_path):
    """Mock a successful POST request."""
    mock_client = _mock_async_client(response_status=201, response_text="created")

    config = {
        "fact": {
            "api": [{
                "endpoint": "https://example.com/api",
                "method": "POST",
                "body": {"key": "value"},
                "expected_status": 201,
            }]
        }
    }
    checker = FactChecker(config=config)
    with patch("httpx.AsyncClient", return_value=mock_client):
        report = await checker.verify(tmp_path)

    api_checks = [c for c in report.checks if c.check_name == "fact:api"]
    assert len(api_checks) == 1
    assert api_checks[0].severity == Severity.PASS
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_api_check_put_method(tmp_path):
    """Mock a PUT request (exercises the generic-method branch)."""
    mock_client = _mock_async_client()

    config = {
        "fact": {
            "api": [{
                "endpoint": "https://example.com/api/1",
                "method": "PUT",
                "body": {"key": "updated"},
                "expected_status": 200,
            }]
        }
    }
    checker = FactChecker(config=config)
    with patch("httpx.AsyncClient", return_value=mock_client):
        report = await checker.verify(tmp_path)

    api_checks = [c for c in report.checks if c.check_name == "fact:api"]
    assert len(api_checks) == 1
    assert api_checks[0].severity == Severity.PASS
    mock_client.request.assert_called_once_with(
        "PUT", "https://example.com/api/1", json={"key": "updated"}
    )


@pytest.mark.asyncio
async def test_api_check_error_status(tmp_path):
    """API returns 500 — should be a FAIL with detail including body snippet."""
    mock_client = _mock_async_client(
        response_status=500,
        response_text="Internal Server Error",
    )

    config = {
        "fact": {
            "api": [{
                "endpoint": "https://example.com/api",
                "method": "GET",
                "expected_status": 200,
            }]
        }
    }
    checker = FactChecker(config=config)
    with patch("httpx.AsyncClient", return_value=mock_client):
        report = await checker.verify(tmp_path)

    api_checks = [c for c in report.checks if c.check_name == "fact:api"]
    assert len(api_checks) == 1
    assert api_checks[0].severity == Severity.FAIL
    assert "500" in api_checks[0].detail
    assert "Internal Server Error" in api_checks[0].detail


@pytest.mark.asyncio
async def test_api_check_connection_refused(tmp_path):
    """Connection error — should be caught as generic Exception."""
    mock_client = _mock_async_client(
        side_effect=httpx.ConnectError("Connection refused"),
    )

    config = {
        "fact": {
            "api": [{
                "endpoint": "https://localhost:9999/api",
                "method": "GET",
                "expected_status": 200,
            }]
        }
    }
    checker = FactChecker(config=config)
    with patch("httpx.AsyncClient", return_value=mock_client):
        report = await checker.verify(tmp_path)

    api_checks = [c for c in report.checks if c.check_name == "fact:api"]
    assert len(api_checks) == 1
    assert api_checks[0].severity == Severity.FAIL
    assert "error" in api_checks[0].message.lower()


@pytest.mark.asyncio
async def test_api_check_generic_exception(tmp_path):
    """Generic Exception (e.g. invalid URL) caught gracefully."""
    mock_client = _mock_async_client(
        side_effect=ValueError("Invalid URL"),
    )

    config = {
        "fact": {
            "api": [{
                "endpoint": "not-a-valid-url",
                "method": "GET",
                "expected_status": 200,
            }]
        }
    }
    checker = FactChecker(config=config)
    with patch("httpx.AsyncClient", return_value=mock_client):
        report = await checker.verify(tmp_path)

    api_checks = [c for c in report.checks if c.check_name == "fact:api"]
    assert len(api_checks) == 1
    assert api_checks[0].severity == Severity.FAIL
    assert "Invalid URL" in api_checks[0].detail


# ═══════════════════════════════════════════════════════════════════════════
# File checker — edge cases
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_content_not_contains_pass(tmp_path):
    """Not-contains check passes when forbidden content is absent."""
    (tmp_path / "clean.json").write_text(json.dumps({"status": "ok"}))

    config = {
        "fact": {
            "files": [{
                "pattern": "*.json",
                "content_checks": [{"type": "not_contains", "value": "error"}],
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)

    content = [c for c in report.checks if c.check_name == "fact:content_not_contains"]
    assert len(content) == 1
    assert content[0].severity == Severity.PASS


@pytest.mark.asyncio
async def test_content_unicode_decode_error(tmp_path):
    """Binary file should be silently skipped during content checks."""
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02\xff\xfe")

    config = {
        "fact": {
            "files": [{
                "pattern": "*.bin",
                "content_checks": [{"type": "contains", "value": "text"}],
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)

    # No content checks should be produced — binary skipped
    content = [c for c in report.checks if c.check_name.startswith("fact:content")]
    assert len(content) == 0, f"Expected 0 content checks for binary file, got {content}"


@pytest.mark.asyncio
async def test_file_size_above_min(tmp_path):
    """File above min_size produces NO size warnings."""
    (tmp_path / "big.json").write_text("x" * 200)

    config = {
        "fact": {
            "files": [{
                "pattern": "*.json",
                "min_size_bytes": 100,
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)

    size_checks = [c for c in report.checks if c.check_name == "fact:file_size"]
    assert len(size_checks) == 0, f"Expected no size warnings, got {size_checks}"


@pytest.mark.asyncio
async def test_file_check_recursive_glob(tmp_path):
    """Recursive glob pattern '**/*.json' works with expected_count."""
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (tmp_path / "a.json").write_text("{}")
    (subdir / "b.json").write_text("{}")

    config = {
        "fact": {
            "files": [{
                "pattern": "**/*.json",
                "expected_count": 2,
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)

    file_count = [c for c in report.checks if c.check_name == "fact:file_count"]
    assert len(file_count) == 1
    assert file_count[0].severity == Severity.PASS


@pytest.mark.asyncio
async def test_multiple_file_checks(tmp_path):
    """Multiple file specs in one config produce independent results."""
    (tmp_path / "a.json").write_text('{"x": 1}')
    (tmp_path / "b.txt").write_text("hello world")

    config = {
        "fact": {
            "files": [
                {"pattern": "*.json", "expected_count": 1},
                {"pattern": "*.txt", "expected_count": 1},
            ]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)

    file_counts = [c for c in report.checks if c.check_name == "fact:file_count"]
    assert len(file_counts) == 2
    assert all(c.severity == Severity.PASS for c in file_counts)


@pytest.mark.asyncio
async def test_file_check_no_matches_expected_count(tmp_path):
    """expected_count with no matching files should FAIL."""
    config = {
        "fact": {
            "files": [{
                "pattern": "nonexistent_*.bin",
                "expected_count": 3,
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)

    file_count = [c for c in report.checks if c.check_name == "fact:file_count"]
    assert len(file_count) == 1
    assert file_count[0].severity == Severity.FAIL
    assert "0" in file_count[0].message  # found 0 files


# ═══════════════════════════════════════════════════════════════════════════
# LLM judge — edge cases
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_llm_judge_unicode_decode_error(tmp_path):
    """LLM judge gracefully handles binary files it cannot decode."""
    (tmp_path / "output.bin").write_bytes(b"\x00\x01\xff\xfe")

    config = {
        "fact": {
            "llm_judge": [{
                "file": "output.bin",
                "rubric": "Check the binary",
            }]
        }
    }
    checker = FactChecker(config=config)
    report = await checker.verify(tmp_path)

    judge = [c for c in report.checks if c.check_name == "fact:llm_judge"]
    assert len(judge) == 1
    assert judge[0].severity == Severity.WARN
    assert "cannot read" in judge[0].message.lower()


# ═══════════════════════════════════════════════════════════════════════════
# _parse_judge_response — static method tests (no async needed)
# ═══════════════════════════════════════════════════════════════════════════

def test_parse_judge_response_valid_pass():
    """Parse a valid PASS verdict from LLM response."""
    response = "VERDICT: PASS\nREASON: Everything looks correct."
    verdict, reason = FactChecker._parse_judge_response(response)
    assert verdict == "PASS"
    assert reason == "Everything looks correct."


def test_parse_judge_response_valid_fail():
    """Parse a valid FAIL verdict from LLM response."""
    response = "VERDICT: FAIL\nREASON: The output contains hallucinations."
    verdict, reason = FactChecker._parse_judge_response(response)
    assert verdict == "FAIL"
    assert reason == "The output contains hallucinations."


def test_parse_judge_response_valid_warn():
    """Parse a valid WARN verdict."""
    response = "VERDICT: WARN\nREASON: Minor issues found."
    verdict, reason = FactChecker._parse_judge_response(response)
    assert verdict == "WARN"
    assert reason == "Minor issues found."


def test_parse_judge_response_lowercase():
    """Case-insensitive matching for verdict line."""
    response = "verdict: pass\nreason: All good."
    verdict, reason = FactChecker._parse_judge_response(response)
    assert verdict == "PASS"
    assert reason == "All good."


def test_parse_judge_response_garbled():
    """Garbled response returns default WARN verdict."""
    response = "Lorem ipsum dolor sit amet\nconsectetur adipiscing elit"
    verdict, reason = FactChecker._parse_judge_response(response)
    assert verdict == "WARN"
    assert reason == "Could not parse judge response"


def test_parse_judge_response_empty():
    """Empty response returns default WARN verdict."""
    verdict, reason = FactChecker._parse_judge_response("")
    assert verdict == "WARN"
    assert reason == "Could not parse judge response"


def test_parse_judge_response_whitespace_only():
    """Whitespace-only response returns defaults."""
    verdict, reason = FactChecker._parse_judge_response("   \n  \n  ")
    assert verdict == "WARN"


def test_parse_judge_response_partial():
    """Response with only VERDICT but no REASON."""
    response = "VERDICT: FAIL\nSome extra text without reason label"
    verdict, reason = FactChecker._parse_judge_response(response)
    assert verdict == "FAIL"
    assert reason == "Could not parse judge response"


# ═══════════════════════════════════════════════════════════════════════════
# _llm_judge — successful call path (mock _call_llm)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_llm_judge_successful_call(tmp_path):
    """LLM judge with a mocked _call_llm that returns PASS."""
    (tmp_path / "output.txt").write_text("All tests pass.")

    config = {
        "fact": {
            "llm_judge": [{
                "file": "output.txt",
                "rubric": "Check correctness",
            }]
        }
    }
    checker = FactChecker(config=config)

    async def fake_call_llm(prompt, model):
        return "VERDICT: PASS\nREASON: Output looks correct."

    with patch.object(checker, "_call_llm", side_effect=fake_call_llm):
        report = await checker.verify(tmp_path)

    judge = [c for c in report.checks if c.check_name == "fact:llm_judge"]
    assert len(judge) == 1
    assert judge[0].severity == Severity.PASS
    assert "PASS" in judge[0].message


@pytest.mark.asyncio
async def test_llm_judge_call_returns_warn(tmp_path):
    """Mocked _call_llm returns WARN verdict."""
    (tmp_path / "output.txt").write_text("Minor issues.")

    config = {
        "fact": {
            "llm_judge": [{
                "file": "output.txt",
                "rubric": "Check quality",
            }]
        }
    }
    checker = FactChecker(config=config)

    async def fake_call_llm(prompt, model):
        return "VERDICT: WARN\nREASON: Minor formatting issues."

    with patch.object(checker, "_call_llm", side_effect=fake_call_llm):
        report = await checker.verify(tmp_path)

    judge = [c for c in report.checks if c.check_name == "fact:llm_judge"]
    assert len(judge) == 1
    assert judge[0].severity == Severity.WARN


@pytest.mark.asyncio
async def test_llm_judge_call_returns_fail(tmp_path):
    """Mocked _call_llm returns FAIL verdict."""
    (tmp_path / "output.txt").write_text("Broken output.")

    config = {
        "fact": {
            "llm_judge": [{
                "file": "output.txt",
                "rubric": "Check integrity",
            }]
        }
    }
    checker = FactChecker(config=config)

    async def fake_call_llm(prompt, model):
        return "VERDICT: FAIL\nREASON: Critical errors found."

    with patch.object(checker, "_call_llm", side_effect=fake_call_llm):
        report = await checker.verify(tmp_path)

    judge = [c for c in report.checks if c.check_name == "fact:llm_judge"]
    assert len(judge) == 1
    assert judge[0].severity == Severity.FAIL


# ═══════════════════════════════════════════════════════════════════════════
# _call_llm — mocked module import paths
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_call_llm_openai_success():
    """_call_llm via mocked openai module returns response text."""
    import sys

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "VERDICT: PASS\nREASON: All good."

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    mock_async_openai = MagicMock(return_value=mock_client)

    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI = mock_async_openai

    checker = FactChecker()
    with patch.dict(sys.modules, {"openai": mock_openai}):
        result = await checker._call_llm("test prompt", "gpt-4")

    assert result == "VERDICT: PASS\nREASON: All good."
    mock_async_openai.assert_called_once()
    mock_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_llm_openai_error_with_key():
    """openai raises an error while api_key is set → RuntimeError."""
    import sys

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("API rate limit exceeded")
    )

    mock_async_openai = MagicMock(return_value=mock_client)

    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI = mock_async_openai

    checker = FactChecker(config={
        "llm": {"api_key": "sk-test-key"},
    })

    with (
        patch.dict(sys.modules, {"openai": mock_openai}),
        pytest.raises(RuntimeError, match="LLM call failed"),
    ):
        await checker._call_llm("test prompt", "gpt-4")


@pytest.mark.asyncio
async def test_call_llm_openai_error_no_key_falls_through_to_litellm():
    """openai raises but no api_key → falls through to litellm (mocked)."""
    import sys

    # openai raises
    mock_openai_client = MagicMock()
    mock_openai_client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("auth error")
    )
    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI = MagicMock(return_value=mock_openai_client)

    # litellm succeeds
    mock_litellm_response = MagicMock()
    mock_litellm_response.choices = [MagicMock()]
    mock_litellm_response.choices[0].message.content = "VERDICT: WARN\nREASON: okay"

    mock_litellm = MagicMock()
    mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)

    checker = FactChecker()
    with patch.dict(sys.modules, {
        "openai": mock_openai,
        "litellm": mock_litellm,
    }):
        result = await checker._call_llm("test prompt", "claude-3")

    assert result == "VERDICT: WARN\nREASON: okay"
    mock_litellm.acompletion.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_llm_no_modules():
    """Neither openai nor litellm available → RuntimeError with install hint.

    The _llm_judge path (test_llm_judge_no_llm_installed) already covers this
    through the exception handler at line 290-300 of fact.py.
    """
    import sys

    checker = FactChecker()
    with (
        patch.dict(sys.modules, {"openai": None, "litellm": None}),
        # When openai import fails (None in sys.modules causes ImportError
        # since None is not a module), it falls to litellm which also fails.
        pytest.raises(RuntimeError, match="Neither openai nor litellm"),
    ):
        await checker._call_llm("test", "model")


@pytest.mark.asyncio
async def test_call_llm_openai_with_base_url():
    """_call_llm passes base_url to AsyncOpenAI when configured (covers line 329)."""
    import sys

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    mock_async_openai = MagicMock(return_value=mock_client)
    mock_openai = MagicMock()
    mock_openai.AsyncOpenAI = mock_async_openai

    checker = FactChecker(config={
        "llm": {"base_url": "https://custom.api.example.com/v1"},
    })

    with patch.dict(sys.modules, {"openai": mock_openai}):
        await checker._call_llm("test prompt", "gpt-4")

    mock_async_openai.assert_called_once_with(
        base_url="https://custom.api.example.com/v1",
    )
