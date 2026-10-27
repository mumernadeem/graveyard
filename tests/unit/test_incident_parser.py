"""
Tests for the incident parser (checks/incident_check.py)
Covers: fenced block extraction, rule parsing, edge cases, backward compat.
"""
import os
import sys
import tempfile
import shutil

# Add source to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "cli"))

from checks.incident_check import (
    parse_incident_file,
    _parse_rules_yaml,
    enforce_rules,
    run_incident_check,
)


class TestParseRulesYaml:
    """Test the YAML-like rule parser."""

    def test_basic_rule(self):
        text = "- type: deploy_window\n  block_days: friday\n  block_after: 16:00"
        rules = _parse_rules_yaml(text)
        assert len(rules) == 1
        assert rules[0]["type"] == "deploy_window"
        assert rules[0]["block_days"] == "friday"
        assert rules[0]["block_after"] == "16:00"

    def test_multiple_rules(self):
        text = """- type: deploy_window
  block_days: friday

- type: min_pass_rate
  value: 98"""
        rules = _parse_rules_yaml(text)
        assert len(rules) == 2
        assert rules[0]["type"] == "deploy_window"
        assert rules[1]["type"] == "min_pass_rate"
        assert rules[1]["value"] == 98

    def test_url_with_port(self):
        """URLs with colons should not break the parser."""
        text = "- type: dependency\n  url: https://db-health.internal:5432/status\n  name: DB Health"
        rules = _parse_rules_yaml(text)
        assert len(rules) == 1
        assert rules[0]["url"] == "https://db-health.internal:5432/status"

    def test_url_with_multiple_colons(self):
        text = "- type: dependency\n  url: http://example.com:8080/api/v1:check\n  name: Complex URL"
        rules = _parse_rules_yaml(text)
        assert rules[0]["url"] == "http://example.com:8080/api/v1:check"

    def test_boolean_true(self):
        text = "- type: security_scan\n  required: true"
        rules = _parse_rules_yaml(text)
        assert rules[0]["required"] is True

    def test_boolean_false(self):
        text = "- type: image_tag\n  block_latest: false"
        rules = _parse_rules_yaml(text)
        assert rules[0]["block_latest"] is False

    def test_integer_value(self):
        text = "- type: min_replicas\n  value: 5"
        rules = _parse_rules_yaml(text)
        assert rules[0]["value"] == 5
        assert isinstance(rules[0]["value"], int)

    def test_quoted_string(self):
        text = '- type: deploy_window\n  block_after: "16:00"'
        rules = _parse_rules_yaml(text)
        assert rules[0]["block_after"] == "16:00"

    def test_single_quoted_string(self):
        text = "- type: deploy_window\n  block_after: '16:00'"
        rules = _parse_rules_yaml(text)
        assert rules[0]["block_after"] == "16:00"

    def test_comments_ignored(self):
        text = "# This is a comment\n- type: min_pass_rate\n  # Another comment\n  value: 90"
        rules = _parse_rules_yaml(text)
        assert len(rules) == 1
        assert rules[0]["value"] == 90

    def test_empty_input(self):
        rules = _parse_rules_yaml("")
        assert rules == []

    def test_no_rules(self):
        rules = _parse_rules_yaml("just some random text\nno rules here")
        assert rules == []


class TestParseIncidentFile:
    """Test parsing of full incident markdown files."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def _write_incident(self, filename, content):
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_fenced_block_extraction(self):
        path = self._write_incident("test.md", """
# Incident: Test Incident
# Date: 2025-01-01
# Severity: P1
# Service: my-service

## Deploy Rules

```graveyard
- type: min_pass_rate
  value: 99
```
""")
        incident = parse_incident_file(path)
        assert incident["title"] == "Test Incident"
        assert incident["date"] == "2025-01-01"
        assert incident["severity"] == "P1"
        assert incident["service"] == "my-service"
        assert len(incident["rules"]) == 1
        assert incident["rules"][0]["value"] == 99

    def test_multiple_fenced_blocks(self):
        path = self._write_incident("test.md", """
# Incident: Multi Block

```graveyard
- type: min_pass_rate
  value: 95
```

Some text in between.

```graveyard
- type: deploy_window
  block_days: friday
```
""")
        incident = parse_incident_file(path)
        assert len(incident["rules"]) == 2

    def test_backward_compat_no_fenced_block(self):
        """Old-format incidents (no fenced block) should still work."""
        path = self._write_incident("test.md", """
# Incident: Old Format

## Deploy Rules

- type: min_pass_rate
  value: 90

- type: deploy_window
  block_days: friday
""")
        incident = parse_incident_file(path)
        assert len(incident["rules"]) == 2
        assert incident["rules"][0]["value"] == 90

    def test_no_rules_section(self):
        path = self._write_incident("test.md", """
# Incident: No Rules

## What Happened
Something bad.
""")
        incident = parse_incident_file(path)
        assert incident["rules"] == []

    def test_missing_metadata(self):
        path = self._write_incident("test.md", """
## Deploy Rules

```graveyard
- type: min_pass_rate
  value: 50
```
""")
        incident = parse_incident_file(path)
        assert incident["title"] is None
        assert incident["severity"] is None
        assert len(incident["rules"]) == 1

    def test_url_with_port_in_fenced_block(self):
        path = self._write_incident("test.md", """
# Incident: URL Test

## Deploy Rules

```graveyard
- type: dependency
  url: https://db.internal:5432/health
  name: Database
```
""")
        incident = parse_incident_file(path)
        assert incident["rules"][0]["url"] == "https://db.internal:5432/health"


class TestEnforceRules:
    """Test rule enforcement logic."""

    def _make_incident(self, title, severity, rules):
        return {
            "file": "test.md",
            "title": title,
            "severity": severity,
            "rules": rules,
        }

    def test_min_pass_rate_creates_override(self):
        incidents = [self._make_incident("Test", "P1", [{"type": "min_pass_rate", "value": 99}])]
        results = enforce_rules(incidents, {})
        assert len(results) == 1
        assert results[0]["status"] == "INFO"
        assert results[0]["override"]["check"] == "tests"
        assert results[0]["override"]["value"] == 99

    def test_min_replicas_creates_override(self):
        incidents = [self._make_incident("Test", "P1", [{"type": "min_replicas", "value": 5}])]
        results = enforce_rules(incidents, {})
        assert results[0]["override"]["check"] == "k8s"
        assert results[0]["override"]["value"] == 5

    def test_dependency_creates_extra_dep(self):
        incidents = [self._make_incident("Test", "P1", [
            {"type": "dependency", "url": "https://api.example.com", "name": "Example API"}
        ])]
        results = enforce_rules(incidents, {})
        assert results[0]["extra_dep"]["url"] == "https://api.example.com"
        assert results[0]["extra_dep"]["name"] == "Example API"

    def test_security_scan_required(self):
        incidents = [self._make_incident("Test", "P1", [
            {"type": "security_scan", "required": True, "block_on": "CRITICAL", "max_high": 0}
        ])]
        results = enforce_rules(incidents, {})
        # Should create 3 INFO entries (required, block_on, max_high)
        assert len(results) == 3

    def test_image_tag_block_latest(self):
        incidents = [self._make_incident("Test", "P2", [
            {"type": "image_tag", "block_latest": True}
        ])]
        results = enforce_rules(incidents, {})
        assert results[0]["override"]["check"] == "k8s"
        assert results[0]["override"]["field"] == "block_latest"

    def test_custom_command_pass(self):
        incidents = [self._make_incident("Custom Cmd", "P1", [
            {"type": "custom_command", "name": "Always True", "run": 'python3 -c "exit(0)"'}
        ])]
        results = enforce_rules(incidents, {})
        assert results[0]["status"] == "PASS"
        assert "Always True" in results[0]["rule"]

    def test_custom_command_fail(self):
        incidents = [self._make_incident("Custom Cmd", "P1", [
            {"type": "custom_command", "name": "Always False", "run": 'python3 -c "exit(1)"'}
        ])]
        results = enforce_rules(incidents, {})
        assert results[0]["status"] == "FAIL"
        assert "Always False" in results[0]["rule"]

    def test_blast_radius_inactive_day(self):
        incidents = [self._make_incident("Blast Radius", "P2", [
            {"type": "blast_radius", "max_lines": 100, "block_days": "neverday"}
        ])]
        results = enforce_rules(incidents, {})
        assert results[0]["status"] == "PASS"
        assert "not active today" in results[0]["rule"]

    def test_env_check_pass(self):
        os.environ["GRAVEYARD_TEST_VAR"] = "present"
        try:
            incidents = [self._make_incident("Env Check", "P2", [
                {"type": "env_check", "required_vars": "GRAVEYARD_TEST_VAR"}
            ])]
            results = enforce_rules(incidents, {})
            assert results[0]["status"] == "PASS"
        finally:
            os.environ.pop("GRAVEYARD_TEST_VAR", None)

    def test_env_check_fail(self):
        incidents = [self._make_incident("Env Check", "P2", [
            {"type": "env_check", "required_vars": "NON_EXISTENT_VAR_XYZ_123"}
        ])]
        results = enforce_rules(incidents, {})
        assert results[0]["status"] == "FAIL"
        assert "NON_EXISTENT_VAR_XYZ_123" in results[0]["rule"]

    def test_unknown_rule_type_warns(self):
        incidents = [self._make_incident("Test", "P1", [{"type": "bogus_rule"}])]
        results = enforce_rules(incidents, {})
        assert results[0]["status"] == "WARN"
        assert "Unknown rule type" in results[0]["rule"]


class TestRunIncidentCheck:
    """Test the full incident check entry point."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_no_directory(self):
        result = run_incident_check("/nonexistent/path", {})
        assert result["status"] == "SKIP"

    def test_empty_directory(self):
        result = run_incident_check(self.tmpdir, {})
        assert result["status"] == "SKIP"

    def test_file_without_rules(self):
        path = os.path.join(self.tmpdir, "no-rules.md")
        with open(path, "w") as f:
            f.write("# Incident: No rules\n## What Happened\nSomething.\n")
        result = run_incident_check(self.tmpdir, {})
        assert result["status"] == "SKIP"

    def test_valid_incident(self):
        path = os.path.join(self.tmpdir, "valid.md")
        with open(path, "w") as f:
            f.write("""# Incident: Valid
# Severity: P1

## Deploy Rules

```graveyard
- type: min_pass_rate
  value: 99
```
""")
        result = run_incident_check(self.tmpdir, {})
        assert result["status"] == "PASS"
        assert "1 incidents" in result["message"]
        assert len(result["overrides"]) == 1
