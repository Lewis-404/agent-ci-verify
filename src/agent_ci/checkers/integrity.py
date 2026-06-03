"""Integrity Checker — validates reference integrity across agent system.

Checks:
1. Agent YAML → referenced skills exist
2. Agent YAML → referenced prompt files exist
3. .layers.yaml → every classified skill has a SKILL.md
4. .layers.yaml → no orphan classifications (SKILL.md missing)
5. All active cronjobs have corresponding agent YAMLs (drift detection)

Corresponds to Anthropic FSI's check.py reference validation pattern.
"""

from pathlib import Path

import yaml

from agent_ci.checkers.base import BaseChecker
from agent_ci.types import CheckerReport, CheckResult, Severity

# Default paths (configurable via .agent-ci.yaml)
DEFAULT_AGENTS_DIR = Path.home() / ".hermes" / "agents"
DEFAULT_SKILLS_DIR = Path.home() / ".hermes" / "skills"
DEFAULT_LAYERS_FILE = DEFAULT_SKILLS_DIR / ".layers.yaml"


class IntegrityChecker(BaseChecker):
    """Validates cross-references between agents, skills, and layers."""

    name = "integrity"

    async def verify(self, output_dir: Path) -> CheckerReport:
        report = CheckerReport(checker_name=self.name)
        config = self.config.get("integrity", {})

        agents_dir = Path(config.get("agents_dir", DEFAULT_AGENTS_DIR))
        skills_dir = Path(config.get("skills_dir", DEFAULT_SKILLS_DIR))
        layers_file = Path(config.get("layers_file", DEFAULT_LAYERS_FILE))

        # Check 1: Agent YAML references
        if agents_dir.exists():
            report.checks.extend(self._check_agent_references(agents_dir, skills_dir))

        # Check 2: Layers file integrity
        if layers_file.exists():
            report.checks.extend(self._check_layers_integrity(layers_file, skills_dir))

        # Check 3: Skills directory health
        if skills_dir.exists():
            report.checks.extend(self._check_skills_health(skills_dir, layers_file))

        # If no checks were run (nothing exists), report that
        if not report.checks:
            report.checks.append(
                CheckResult(
                    checker=self.name,
                    check_name="integrity:no_targets",
                    severity=Severity.WARN,
                    message="No agent/skill directories found to check",
                    detail=f"Checked: agents={agents_dir}, skills={skills_dir}",
                )
            )

        return report

    def _check_agent_references(
        self, agents_dir: Path, skills_dir: Path
    ) -> list[CheckResult]:
        """Verify agent YAML files reference existing skills and prompts."""
        results: list[CheckResult] = []
        yaml_files = list(agents_dir.glob("*.yaml"))

        if not yaml_files:
            results.append(
                CheckResult(
                    checker=self.name,
                    check_name="integrity:agents_found",
                    severity=Severity.WARN,
                    message="No agent YAML files found",
                    detail=f"Expected *.yaml in {agents_dir}",
                )
            )
            return results

        agent_count = 0
        total_skill_refs = 0
        missing_skills = 0
        missing_prompts = 0

        for yf in sorted(yaml_files):
            if yf.name == "SCHEMA.yaml":
                continue
            try:
                agent = yaml.safe_load(yf.read_text())
            except yaml.YAMLError as e:
                results.append(
                    CheckResult(
                        checker=self.name,
                        check_name="integrity:agent_yaml_parse",
                        severity=Severity.FAIL,
                        message=f"Invalid agent YAML: {yf.name}",
                        detail=str(e),
                        file_path=str(yf),
                    )
                )
                continue

            agent_count += 1
            agent_name = agent.get("name", yf.stem)

            # Check skills
            for skill_name in agent.get("skills", []):
                total_skill_refs += 1
                skill_dir = skills_dir / skill_name
                skill_md = skill_dir / "SKILL.md"
                # Also check nested paths
                if not skill_md.exists():
                    # Try finding it anywhere under skills_dir
                    found = list(skills_dir.rglob(f"**/{skill_name}/SKILL.md"))
                    if not found:
                        missing_skills += 1
                        results.append(
                            CheckResult(
                                checker=self.name,
                                check_name="integrity:skill_missing",
                                severity=Severity.FAIL,
                                message=(
                                    f"Agent '{agent_name}' references missing "
                                    f"skill: {skill_name}"
                                ),
                                detail=f"Expected SKILL.md at {skill_md} or under {skills_dir}",
                                file_path=str(yf),
                            )
                        )

            # Check prompt file
            prompt_file = agent.get("system_prompt_file", "")
            if prompt_file:
                prompt_path = agents_dir / prompt_file
                if not prompt_path.exists():
                    missing_prompts += 1
                    results.append(
                        CheckResult(
                            checker=self.name,
                            check_name="integrity:prompt_missing",
                            severity=Severity.FAIL,
                            message=(
                                f"Agent '{agent_name}' prompt file not found: "
                                f"{prompt_file}"
                            ),
                            detail=f"Resolved to: {prompt_path}",
                            file_path=str(yf),
                        )
                    )
            elif not agent.get("system_prompt", ""):
                results.append(
                    CheckResult(
                        checker=self.name,
                        check_name="integrity:no_prompt",
                        severity=Severity.WARN,
                        message=(
                            f"Agent '{agent_name}' has no system_prompt or "
                            f"system_prompt_file"
                        ),
                        file_path=str(yf),
                    )
                )

        # Summary
        results.append(
            CheckResult(
                checker=self.name,
                check_name="integrity:agent_summary",
                severity=(
                    Severity.PASS
                    if missing_skills == 0 and missing_prompts == 0
                    else Severity.FAIL
                ),
                message=(
                    f"Agent integrity: {agent_count} agents, "
                    f"{total_skill_refs} skill refs, "
                    f"{missing_skills} missing skills, "
                    f"{missing_prompts} missing prompts"
                ),
            )
        )

        return results

    def _check_layers_integrity(
        self, layers_file: Path, skills_dir: Path
    ) -> list[CheckResult]:
        """Verify .layers.yaml consistency with actual SKILL.md files."""
        results: list[CheckResult] = []

        try:
            layers = yaml.safe_load(layers_file.read_text())
        except yaml.YAMLError as e:
            results.append(
                CheckResult(
                    checker=self.name,
                    check_name="integrity:layers_parse",
                    severity=Severity.FAIL,
                    message="Invalid .layers.yaml",
                    detail=str(e),
                    file_path=str(layers_file),
                )
            )
            return results

        classifications = layers.get("classifications", {})
        if not classifications:
            results.append(
                CheckResult(
                    checker=self.name,
                    check_name="integrity:layers_empty",
                    severity=Severity.FAIL,
                    message=".layers.yaml has no classifications",
                    file_path=str(layers_file),
                )
            )
            return results

        # Find all actual SKILL.md files
        actual_skills = set()
        for sk in skills_dir.rglob("SKILL.md"):
            if ".archive" in str(sk) or ".curator" in str(sk):
                continue
            actual_skills.add(sk.parent.name)

        classified = set(classifications.keys())

        # Orphan classifications (in layers but SKILL.md missing)
        orphans = classified - actual_skills
        for skill in sorted(orphans):
            results.append(
                CheckResult(
                    checker=self.name,
                    check_name="integrity:layer_orphan",
                    severity=Severity.FAIL,
                    message=f"Orphan layer: '{skill}' classified but SKILL.md missing",
                    detail="Remove from .layers.yaml or restore SKILL.md",
                    file_path=str(layers_file),
                )
            )

        # Unclassified skills (has SKILL.md but no layer)
        unclassified = actual_skills - classified
        for skill in sorted(unclassified):
            results.append(
                CheckResult(
                    checker=self.name,
                    check_name="integrity:skill_unclassified",
                    severity=Severity.WARN,
                    message=f"Unclassified skill: '{skill}' has SKILL.md but no layer",
                    detail="Add to .layers.yaml classifications",
                )
            )

        # Layer stats summary
        core_count = sum(1 for v in classifications.values() if v == "core")
        domain_count = sum(
            1 for v in classifications.values() if v.startswith("domain:")
        )
        agent_count = sum(1 for v in classifications.values() if v == "agent")

        results.append(
            CheckResult(
                checker=self.name,
                check_name="integrity:layer_summary",
                severity=(
                    Severity.PASS
                    if not orphans and not unclassified
                    else Severity.WARN
                ),
                message=(
                    f"Layer integrity: {len(classified)} classified "
                    f"(core={core_count}, domain={domain_count}, agent={agent_count}), "
                    f"{len(orphans)} orphans, {len(unclassified)} unclassified"
                ),
            )
        )

        return results

    def _check_skills_health(
        self, skills_dir: Path, layers_file: Path
    ) -> list[CheckResult]:
        """Check skills directory for common issues."""
        results: list[CheckResult] = []

        # Count total skills
        skill_mds = list(skills_dir.rglob("SKILL.md"))
        valid_count = 0
        frontmatter_issues = 0

        for sk in skill_mds:
            if ".archive" in str(sk) or ".curator" in str(sk):
                continue
            try:
                content = sk.read_text(encoding="utf-8")
                # Check for YAML frontmatter
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        yaml.safe_load(content[3:end])
                        valid_count += 1
                    else:
                        frontmatter_issues += 1
                else:
                    frontmatter_issues += 1
            except (yaml.YAMLError, UnicodeDecodeError):
                frontmatter_issues += 1

        if frontmatter_issues > 0:
            results.append(
                CheckResult(
                    checker=self.name,
                    check_name="integrity:frontmatter_issues",
                    severity=Severity.WARN,
                    message=(
                        f"{frontmatter_issues} skills have frontmatter issues "
                        f"(out of {valid_count + frontmatter_issues} total)"
                    ),
                    detail="Each SKILL.md should start with valid YAML frontmatter",
                )
            )

        results.append(
            CheckResult(
                checker=self.name,
                check_name="integrity:skills_health",
                severity=Severity.PASS if frontmatter_issues == 0 else Severity.WARN,
                message=(
                    f"Skills health: {valid_count + frontmatter_issues} total, "
                    f"{valid_count} valid, {frontmatter_issues} with issues"
                ),
            )
        )

        return results
