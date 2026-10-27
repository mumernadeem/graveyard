"""
Tests for incident learner (cli/incident_learner.py)
"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "cli"))

from incident_learner import (
    extract_rules_heuristic,
    format_postmortem_markdown,
    learn_incident,
    _slugify,
)


class TestIncidentLearner:
    """Test incident learner heuristic engine and formatting."""

    def test_slugify(self):
        assert _slugify("Friday Cache Stampede!!") == "friday-cache-stampede"
        assert _slugify("  P1 -- DB Lock   ") == "p1-db-lock"

    def test_heuristic_friday_deploy(self):
        text = "We deployed on Friday afternoon at 5pm. The cache broke Postgres."
        data = extract_rules_heuristic(text)
        assert data["severity"] == "P2"
        types = [r["type"] for r in data["rules"]]
        assert "deploy_window" in types
        win = next(r for r in data["rules"] if r["type"] == "deploy_window")
        assert win["block_days"] == "friday"

    def test_heuristic_migration_rule(self):
        text = "Production incident: Database migration failed. We ran alter table and locked everything."
        data = extract_rules_heuristic(text)
        types = [r["type"] for r in data["rules"]]
        assert "custom_command" in types

    def test_heuristic_replica_rule(self):
        text = "Traffic spike caused single pod to run out of memory. Needed more replicas."
        data = extract_rules_heuristic(text)
        types = [r["type"] for r in data["rules"]]
        assert "min_replicas" in types

    def test_format_postmortem_markdown(self):
        data = {
            "title": "Test Incident",
            "date": "2026-10-28",
            "severity": "P1",
            "service": "auth-service",
            "what_happened": "Tokens expired.",
            "root_cause": "Clock drift.",
            "rules": [
                {"type": "deploy_window", "block_days": "friday", "block_after": "16:00"},
                {"type": "min_pass_rate", "value": 99}
            ]
        }
        md = format_postmortem_markdown(data)
        assert "# Incident: Test Incident" in md
        assert "# Severity: P1" in md
        assert "```graveyard" in md
        assert "- type: deploy_window" in md
        assert "- type: min_pass_rate" in md

    def test_learn_incident_save(self):
        tmpdir = tempfile.mkdtemp()
        try:
            sample_text = "Incident: Unscanned Container. We deployed a CVE vulnerability."
            result = learn_incident(sample_text, save_dir=tmpdir, auto_save=True)
            assert result["saved_to"] is not None
            assert os.path.exists(result["saved_to"])
            with open(result["saved_to"], "r") as f:
                content = f.read()
            assert "```graveyard" in content
            assert "security_scan" in content
        finally:
            shutil.rmtree(tmpdir)
