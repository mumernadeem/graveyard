"""
Tests for the configuration loader (config.py)
"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "cli"))

from config import load_config, get_check_config, is_check_enabled


class TestLoadConfig:
    """Test configuration loading and merging."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def teardown_method(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.tmpdir)

    def test_defaults_when_no_config(self):
        config, found = load_config(None)
        assert found is False
        assert "checks" in config

    def test_loads_config_file(self):
        with open(".graveyard.yml", "w", encoding="utf-8") as f:
            f.write('project: "test-project"\nenvironment: "staging"\n')
        config, found = load_config(".graveyard.yml")
        assert found is True
        assert config["project"] == "test-project"

    def test_merge_with_defaults(self):
        with open(".graveyard.yml", "w", encoding="utf-8") as f:
            f.write('project: "my-app"\nchecks:\n  tests:\n    min_pass_rate: 80\n')
        config, found = load_config(".graveyard.yml")
        assert config["project"] == "my-app"
        # Should have merged with default checks
        assert "checks" in config


class TestCheckConfig:
    """Test check-specific config helpers."""

    def test_get_check_config_exists(self):
        config = {"checks": {"tests": {"min_pass_rate": 90, "enabled": True}}}
        cfg = get_check_config(config, "tests")
        assert cfg["min_pass_rate"] == 90

    def test_get_check_config_missing_returns_disabled(self):
        """A check that doesn't exist in config should be treated as disabled."""
        config = {"checks": {}}
        cfg = get_check_config(config, "nonexistent")
        # Missing check returns a sentinel disabled-config so downstream code
        # can safely call is_check_enabled() and skip cleanly.
        assert cfg.get("enabled") is False

    def test_is_check_enabled_default(self):
        config = {"checks": {"tests": {"enabled": True}}}
        assert is_check_enabled(config, "tests") is True

    def test_is_check_disabled(self):
        config = {"checks": {"tests": {"enabled": False}}}
        assert is_check_enabled(config, "tests") is False

    def test_is_check_missing_returns_disabled(self):
        """Missing check in config is treated as disabled (safe default — won't run unknown checks)."""
        config = {"checks": {}}
        assert is_check_enabled(config, "tests") is False

    def test_is_check_enabled_when_flag_implicit(self):
        """If the check exists but has no explicit 'enabled' key, default to enabled=True."""
        config = {"checks": {"tests": {"min_pass_rate": 90}}}
        assert is_check_enabled(config, "tests") is True
