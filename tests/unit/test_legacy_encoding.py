"""
Tests for reading files written by earlier versions in the Windows platform
encoding (CP1252), and for config isolation between runs.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "cli"))

import config as config_module
from config import load_config
from checks.incident_check import enforce_rules, run_incident_check
from fileio import read_text

INCIDENT = (
    "# Incident: Café outage\n"
    "# Date: 2025-01-01\n"
    "# Severity: P1\n"
    "\n"
    "```graveyard\n"
    "- type: min_replicas\n"
    "  value: 4\n"
    "```\n"
)

# Bytes that are invalid in UTF-8 and undefined in CP1252.
UNDECODABLE = b"project: caf\xe9 \x81\x8d\n"


def _env_rule(var):
    return [{
        "title": "Env", "file": "env.md", "severity": "P2",
        "rules": [{"type": "env_check", "required_vars": var}],
    }]


class TestLegacyEncoding:

    def test_read_text_utf8_and_bom(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_bytes(b"\xef\xbb\xbf# Caf\xc3\xa9\r\nline2\r\n")
        assert read_text(str(p)) == "# Café\nline2\n"

    def test_read_text_undecodable_raises(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_bytes(UNDECODABLE)
        with pytest.raises(UnicodeDecodeError):
            read_text(str(p))

    def test_cp1252_incident_still_enforced(self, tmp_path):
        incidents = tmp_path / "incidents"
        incidents.mkdir()
        (incidents / "cafe.md").write_bytes(INCIDENT.encode("cp1252"))

        result = run_incident_check(str(incidents), {})

        assert result["status"] == "PASS"
        assert result["enforced_rules"][0]["source"] == "Café outage"
        assert result["overrides"] == [
            {"check": "k8s", "field": "min_replicas", "value": 4}
        ]

    def test_cp1252_config_is_not_replaced_by_defaults(self, tmp_path):
        p = tmp_path / ".graveyard.yml"
        p.write_bytes(
            "# Café team config\nproject: cafe\nchecks:\n  tests:\n    min_pass_rate: 99\n"
            .encode("cp1252")
        )

        cfg, found = load_config(str(p))

        assert found is True
        assert cfg["project"] == "cafe"
        assert cfg["checks"]["tests"]["min_pass_rate"] == 99

    def test_undecodable_config_stops_the_check(self, tmp_path):
        p = tmp_path / ".graveyard.yml"
        p.write_bytes(UNDECODABLE)
        with pytest.raises(SystemExit) as exc:
            load_config(str(p))
        assert exc.value.code == 2

    def test_cp1252_env_file_is_read(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("GRAVEYARD_LEGACY_VAR", raising=False)
        (tmp_path / ".env").write_bytes("# café\nGRAVEYARD_LEGACY_VAR=é1\n".encode("cp1252"))

        results = enforce_rules(_env_rule("GRAVEYARD_LEGACY_VAR"), {})

        assert results[0]["status"] == "PASS"

    def test_undecodable_env_file_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("GRAVEYARD_LEGACY_VAR", raising=False)
        (tmp_path / ".env").write_bytes(b"GRAVEYARD_LEGACY_VAR=\x81\x8d\n")

        results = enforce_rules(_env_rule("GRAVEYARD_LEGACY_VAR"), {})

        assert results[0]["status"] == "FAIL"
        assert "UTF-8" in results[0]["rule"]


class TestConfigIsolation:

    def test_mutating_loaded_config_does_not_touch_defaults(self, tmp_path):
        p = tmp_path / ".graveyard.yml"
        p.write_text("checks:\n  dependencies:\n    enabled: true\n", encoding="utf-8")

        for path in (str(p), str(tmp_path / "missing.yml")):
            cfg, _ = load_config(path)
            cfg["checks"]["dependencies"]["urls"].append({"name": "x", "url": "http://x"})
            cfg["checks"]["k8s"]["min_replicas"] = 99

        assert config_module.DEFAULTS["checks"]["dependencies"]["urls"] == []
        assert config_module.DEFAULTS["checks"]["k8s"]["min_replicas"] == 2

    def test_demo_twice_reports_same_dependencies(self, tmp_path, monkeypatch, capsys):
        import argparse
        import graveyard

        monkeypatch.chdir(tmp_path)
        lines = []
        for _ in range(2):
            graveyard.cmd_demo(argparse.Namespace())
            out = capsys.readouterr().out
            lines.append([l for l in out.split("\n") if "would ping" in l])

        assert lines[0] and lines[0] == lines[1]
