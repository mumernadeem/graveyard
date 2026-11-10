"""
Tests for the DDR (Deploy Decision Record) writer.
"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "cli"))

from ddr_writer import write_ddr


class TestDDRWriter:
    """Test Deploy Decision Record generation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def teardown_method(self):
        os.chdir(self.original_cwd)
        shutil.rmtree(self.tmpdir)

    def test_creates_file(self):
        results = {"Tests": {"status": "PASS", "message": "All passed"}}
        path = write_ddr("test-project", "staging", "GO", results)
        assert path is not None
        assert os.path.exists(path)

    def test_file_contains_project_name(self):
        results = {"Tests": {"status": "PASS", "message": "All passed"}}
        path = write_ddr("my-app", "production", "GO", results)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "my-app" in content
        assert "production" in content

    def test_file_contains_decision(self):
        results = {"Tests": {"status": "FAIL", "message": "50% failed"}}
        path = write_ddr("app", "prod", "BLOCK", results)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "`BLOCK`" in content

    def test_file_contains_check_results(self):
        results = {
            "Tests": {"status": "PASS", "message": "100/100"},
            "Security": {"status": "FAIL", "message": "3 CRITICAL CVEs"},
        }
        path = write_ddr("app", "prod", "BLOCK", results)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "100/100" in content
        assert "3 CRITICAL CVEs" in content

    def test_filename_format(self):
        results = {"Tests": {"status": "PASS", "message": "ok"}}
        path = write_ddr("demo", "staging", "GO", results)
        filename = os.path.basename(path)
        assert "demo" in filename
        assert "staging" in filename
        assert "go" in filename
        assert filename.endswith(".md")

    def test_incident_policies_section(self):
        results = {
            "Incident Gates": {
                "status": "PASS",
                "message": "2 rules enforced",
                "enforced_rules": [
                    {"status": "PASS", "rule": "Deploy window OK", "source": "Cache Incident", "severity": "P2"},
                    {"status": "INFO", "rule": "Min 3 replicas", "source": "DB Incident", "severity": "P1"},
                ],
            },
        }
        path = write_ddr("app", "prod", "GO", results)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Deploy window OK" in content
        assert "Cache Incident" in content

    def test_creates_deploy_records_dir(self):
        # Remove the auto-created dir
        ddr_dir = os.path.join(self.tmpdir, "deploy-records")
        if os.path.exists(ddr_dir):
            shutil.rmtree(ddr_dir)

        results = {"Tests": {"status": "PASS", "message": "ok"}}
        write_ddr("app", "prod", "GO", results)
        assert os.path.isdir("deploy-records")

    def test_generated_by_graveyard(self):
        results = {"Tests": {"status": "PASS", "message": "ok"}}
        path = write_ddr("app", "prod", "GO", results)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Graveyard CLI" in content
