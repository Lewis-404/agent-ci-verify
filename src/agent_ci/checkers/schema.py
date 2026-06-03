"""Schema Checker — validates output file formats, structure, and security."""

import json
import re
from pathlib import Path

import yaml
from jsonschema import Draft7Validator

from agent_ci.checkers.base import BaseChecker
from agent_ci.types import CheckerReport, CheckResult, Severity

_SECRET_PATTERNS: list[tuple[str, str, str]] = [
    ("aws_access_key", r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (
        "github_token",
        r"gh[pousr]_[A-Za-z0-9_]{36,}",
        "GitHub Personal Access Token",
    ),
    ("openai_key", r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}", "OpenAI API Key"),
    (
        "jwt_token",
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        "JWT Token",
    ),
    (
        "private_key",
        r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----",
        "Private Key",
    ),
    (
        "generic_password",
        r'(?:password|passwd|pwd|secret)\s*[:=]\s*["\'][^\s"\']{8,}["\']',
        "Password/Secret assignment",
    ),
]


class SchemaChecker(BaseChecker):
    """Validates output file formats, JSON/YAML schema compliance, and security."""

    name = "schema"

    async def verify(self, output_dir: Path) -> CheckerReport:
        report = CheckerReport(checker_name=self.name)
        files = list(output_dir.rglob("*"))
        config = self.config.get("schema", {})

        json_files = [file_path for file_path in files if file_path.suffix == ".json"]
        for file_path in json_files:
            report.checks.extend(self._validate_json(file_path))

        yaml_files = [
            file_path for file_path in files if file_path.suffix in (".yaml", ".yml")
        ]
        for file_path in yaml_files:
            report.checks.extend(self._validate_yaml(file_path))

        schemas = config.get("json_schemas") or {}
        for schema_path, file_pattern in schemas.items():
            schema, schema_error = self._load_schema(Path(schema_path))
            if schema_error:
                report.checks.append(
                    CheckResult(
                        checker=self.name,
                        check_name="schema_load",
                        severity=Severity.FAIL,
                        message=f"Could not load JSON schema: {schema_path}",
                        detail=schema_error,
                        file_path=str(schema_path),
                    )
                )
                continue
            assert schema is not None
            for file_path in output_dir.glob(file_pattern):
                report.checks.append(
                    self._check_schema_compliance(file_path, schema)
                )

        security_config = config.get("security", {})
        if security_config.get("enabled", True):
            report.checks.extend(self._security_scan(files))

        required_files = config.get("required_files", [])
        for pattern in required_files:
            matches = list(output_dir.glob(pattern))
            if not matches:
                report.checks.append(
                    CheckResult(
                        checker=self.name,
                        check_name="required_file",
                        severity=Severity.FAIL,
                        message=f"Required file not found: {pattern}",
                        detail=f"Pattern '{pattern}' matched 0 files in {output_dir}",
                    )
                )
                continue

            for match in matches:
                report.checks.append(
                    CheckResult(
                        checker=self.name,
                        check_name="required_file",
                        severity=Severity.PASS,
                        message=(
                            "Required file found: "
                            f"{match.relative_to(output_dir)}"
                        ),
                    )
                )

        return report

    def _validate_json(self, file_path: Path) -> list[CheckResult]:
        relative_path = str(file_path)
        try:
            content = file_path.read_text(encoding="utf-8")
            json.loads(content)
            return [
                CheckResult(
                    checker=self.name,
                    check_name="json_valid",
                    severity=Severity.PASS,
                    message=f"Valid JSON: {relative_path}",
                )
            ]
        except json.JSONDecodeError as error:
            return [
                CheckResult(
                    checker=self.name,
                    check_name="json_valid",
                    severity=Severity.FAIL,
                    message=f"Invalid JSON: {relative_path}",
                    detail=(
                        f"Line {error.lineno}, col {error.colno}: {error.msg}"
                    ),
                    file_path=relative_path,
                )
            ]
        except UnicodeDecodeError:
            return [
                CheckResult(
                    checker=self.name,
                    check_name="json_valid",
                    severity=Severity.WARN,
                    message=f"Not a UTF-8 text file (skipped): {relative_path}",
                )
            ]

    def _validate_yaml(self, file_path: Path) -> list[CheckResult]:
        relative_path = str(file_path)
        try:
            content = file_path.read_text(encoding="utf-8")
            yaml.safe_load(content)
            return [
                CheckResult(
                    checker=self.name,
                    check_name="yaml_valid",
                    severity=Severity.PASS,
                    message=f"Valid YAML: {relative_path}",
                )
            ]
        except yaml.YAMLError as error:
            return [
                CheckResult(
                    checker=self.name,
                    check_name="yaml_valid",
                    severity=Severity.FAIL,
                    message=f"Invalid YAML: {relative_path}",
                    detail=str(error),
                    file_path=relative_path,
                )
            ]

    def _load_schema(self, path: Path) -> tuple[dict | None, str | None]:
        try:
            schema = json.loads(path.read_text())
        except FileNotFoundError:
            return None, f"Schema file not found: {path}"
        except json.JSONDecodeError as error:
            return (
                None,
                f"Invalid JSON schema at line {error.lineno}, col {error.colno}: {error.msg}",
            )
        if not isinstance(schema, dict):
            return None, f"Schema must be a JSON object, got {type(schema).__name__}"
        return schema, None

    def _check_schema_compliance(self, file_path: Path, schema: dict) -> CheckResult:
        relative_path = str(file_path)
        try:
            data = json.loads(file_path.read_text())
            validator = Draft7Validator(schema)
            errors = list(validator.iter_errors(data))
            if not errors:
                return CheckResult(
                    checker=self.name,
                    check_name="schema_compliance",
                    severity=Severity.PASS,
                    message=f"Schema compliant: {relative_path}",
                )

            details = "; ".join(
                f"{' → '.join(str(part) for part in error.path) or '(root)'}: "
                f"{error.message}"
                for error in errors[:3]
            )
            return CheckResult(
                checker=self.name,
                check_name="schema_compliance",
                severity=Severity.FAIL,
                message=f"Schema violations ({len(errors)}): {relative_path}",
                detail=details,
                file_path=relative_path,
            )
        except (json.JSONDecodeError, FileNotFoundError) as error:
            return CheckResult(
                checker=self.name,
                check_name="schema_compliance",
                severity=Severity.WARN,
                message=f"Could not check schema compliance: {relative_path}",
                detail=str(error),
            )

    def _security_scan(self, files: list[Path]) -> list[CheckResult]:
        results: list[CheckResult] = []
        text_extensions = {
            ".json",
            ".yaml",
            ".yml",
            ".txt",
            ".md",
            ".py",
            ".js",
            ".ts",
            ".go",
            ".rs",
            ".sh",
            ".toml",
            ".cfg",
            ".ini",
            ".xml",
            ".html",
            ".css",
            ".env",
        }
        text_files = [
            file_path for file_path in files if file_path.suffix in text_extensions
        ]

        found_any = False
        for file_path in text_files:
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            relative_path = str(file_path)
            for name, pattern, description in _SECRET_PATTERNS:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    found_any = True
                    line_number = content[: match.start()].count("\n") + 1
                    snippet = match.group()[:40]
                    if len(match.group()) > 40:
                        snippet += "..."

                    results.append(
                        CheckResult(
                            checker=self.name,
                            check_name=f"secret:{name}",
                            severity=Severity.FAIL,
                            message=(
                                f"Secret detected ({description}): "
                                f"{relative_path}:L{line_number}"
                            ),
                            detail=f"Matched: {snippet}",
                            file_path=relative_path,
                        )
                    )

        if not found_any:
            results.append(
                CheckResult(
                    checker=self.name,
                    check_name="security_scan",
                    severity=Severity.PASS,
                    message="No secrets detected in output files",
                )
            )

        return results
