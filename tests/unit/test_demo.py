"""
Tests for the built-in `graveyard demo` command.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "cli"))

import graveyard


class TestDemo:
    """The demo must work from any directory and never touch the network."""

    def test_demo_blocks_bad_deploy_offline(self, tmp_path, monkeypatch, capsys):
        def _no_network(*args, **kwargs):
            raise AssertionError("demo must not make network calls")

        monkeypatch.setattr(graveyard, "run_dependency_check", _no_network)
        monkeypatch.setattr("urllib.request.urlopen", _no_network)

        # Run from an empty directory, like a fresh `pip install` user would.
        monkeypatch.chdir(tmp_path)
        graveyard.cmd_demo(argparse.Namespace())

        out = capsys.readouterr().out
        assert "3 incidents" in out
        assert "DEPLOY BLOCKED" in out
        assert "Offline mode" in out

        # Nothing is written into the user's working directory.
        assert os.listdir(tmp_path) == []
        assert os.getcwd() == str(tmp_path)

    def test_demo_data_is_bundled(self):
        demo_data = os.path.join(graveyard.CLI_DIR, "demo_data")
        assert os.path.isfile(os.path.join(demo_data, "demo-config.yml"))
        assert os.path.isfile(os.path.join(demo_data, "k8s", "bad-deployment.yaml"))
        assert os.path.isfile(os.path.join(demo_data, "test-results", "passing.xml"))
        incidents = os.listdir(os.path.join(demo_data, "incidents"))
        assert len([f for f in incidents if f.endswith(".md")]) == 3
