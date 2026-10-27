#!/usr/bin/env python3
"""
Graveyard CLI — Incident-Trained Deploy Gates.
Run `graveyard check` to verify if it's safe to deploy.
"""
import argparse
import os
import sys
import time

# Add the CLI directory to path so we can import config
CLI_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CLI_DIR)

from config import load_config, is_check_enabled, get_check_config


# ─── ANSI Colors ─────────────────────────────────────────────────────────
class C:
    BOLD    = '\033[1m'
    DIM     = '\033[2m'
    RED     = '\033[91m'
    GREEN   = '\033[92m'
    YELLOW  = '\033[93m'
    BLUE    = '\033[94m'
    CYAN    = '\033[96m'
    END     = '\033[0m'


def print_panel(title, subtitle=""):
    """Print a bordered panel header."""
    width = 52
    print(f"\n{C.BLUE}{'─' * width}{C.END}")
    print(f"{C.BLUE}│{C.END} {C.BOLD}{title:^{width - 4}}{C.END} {C.BLUE}│{C.END}")
    if subtitle:
        print(f"{C.BLUE}│{C.END} {C.DIM}{subtitle:^{width - 4}}{C.END} {C.BLUE}│{C.END}")
    print(f"{C.BLUE}{'─' * width}{C.END}\n")


# ─── Check Functions ─────────────────────────────────────────────────────

from checks.test_check import run_test_check


from checks.security_check import run_security_check


from checks.k8s_check import run_k8s_check


from checks.dependency_check import run_dependency_check


from checks.cost_check import run_cost_check
from checks.incident_check import run_incident_check
from ddr_writer import write_ddr


# ─── Display ─────────────────────────────────────────────────────────────

def display_result(check_name, result):
    """Print a single check result with appropriate formatting."""
    status = result["status"]
    msg = result["message"]

    icons = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌", "SKIP": "⏭️ "}
    colors = {"PASS": C.GREEN, "WARN": C.YELLOW, "FAIL": C.RED, "SKIP": C.DIM}

    icon = icons.get(status, "❓")
    color = colors.get(status, "")

    print(f"  {icon} {color}{C.BOLD}{check_name:14}{C.END} {msg}")


def write_github_step_summary(project, environment, decision, results, ddr_path=None):
    """Write markdown summary to GITHUB_STEP_SUMMARY in GitHub Actions environments."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    try:
        icon_map = {"GO": "🟢", "CAUTION": "🟡", "BLOCK": "🔴"}
        status_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}

        with open(summary_file, "a") as f:
            f.write(f"## 🪦 Graveyard Deploy Gate: {icon_map.get(decision, '')} {decision}\n\n")
            f.write(f"- **Project:** `{project}`\n")
            f.write(f"- **Target Environment:** `{environment}`\n")
            f.write(f"- **Deploy Decision:** `{decision}`\n\n")

            f.write("### 🛡️ Checks Summary\n\n")
            f.write("| Check | Status | Details |\n")
            f.write("|---|---|---|\n")
            for name, res in results.items():
                st = res.get("status", "UNKNOWN")
                ic = status_icon.get(st, "❓")
                f.write(f"| {name} | {ic} {st} | {res.get('message', '')} |\n")

            incident_res = results.get("Incident Gates", {})
            enforced = incident_res.get("enforced_rules", [])
            if enforced:
                f.write("\n### 🧠 Incident-Trained Policies Enforced\n\n")
                f.write("| Policy | Source Incident | Severity | Status |\n")
                f.write("|---|---|---|---|\n")
                for r in enforced:
                    st = r.get("status", "INFO")
                    ic = status_icon.get(st, "ℹ️")
                    f.write(f"| {r.get('rule', '')} | {r.get('source', '')} | {r.get('severity', '-')} | {ic} {st} |\n")

            if ddr_path:
                f.write(f"\n> 📄 **Audit Trail:** Deploy Decision Record saved to `{ddr_path}`\n")
            f.write("\n---\n*Enforced automatically by [Graveyard](https://github.com/mumernadeem/graveyard) — Turn your past incidents into unbreakable deploy gates.*\n\n")
    except Exception:
        pass


# ─── Main ────────────────────────────────────────────────────────────────

def cmd_check(args):
    """Run all pre-deployment checks."""
    # Load configuration
    config, config_found = load_config(args.config)
    
    project = config.get("project", "unnamed")
    environment = config.get("environment", "production")

    k8s_dir = getattr(args, 'k8s_dir', None)

    results = {}
    has_errors = False
    has_warnings = False
    skipped = 0

    # 1. Run Incident-Trained Gates FIRST to gather policy overrides
    incident_cfg = get_check_config(config, "incidents")
    incidents_dir = incident_cfg.get("dir", "incidents")
    
    incident_result = run_incident_check(incidents_dir, incident_cfg)
    results["Incident Gates"] = incident_result
    
    if incident_result["status"] == "FAIL":
        has_errors = True
    elif incident_result["status"] == "SKIP":
        skipped += 1
        
    # Apply overrides to config from incidents
    overrides = incident_result.get("overrides", [])
    for override in overrides:
        check = override.get("check")
        field = override.get("field")
        val = override.get("value")
        if check and field:
            if "checks" not in config:
                config["checks"] = {}
            if check not in config["checks"]:
                config["checks"][check] = {}
            config["checks"][check][field] = val
            
    # Apply extra dependencies
    extra_deps = incident_result.get("extra_deps", [])
    if extra_deps:
        if "checks" not in config:
            config["checks"] = {}
        if "dependencies" not in config["checks"]:
            config["checks"]["dependencies"] = {"enabled": True, "urls": []}
        for dep in extra_deps:
            urls = config["checks"]["dependencies"].get("urls", [])
            urls.append(dep)
            config["checks"]["dependencies"]["urls"] = urls

    # Run all standard enabled checks
    checks_to_run = [
        ("Tests",        "tests",        lambda cfg: run_test_check(args.tests, cfg)),
        ("Security",     "security",     lambda cfg: run_security_check(args.image, cfg)),
        ("K8s Config",   "k8s",          lambda cfg: run_k8s_check(k8s_dir, cfg)),
        ("Dependencies", "dependencies", lambda cfg: run_dependency_check(cfg)),
        ("Cost Impact",  "cost",         lambda cfg: run_cost_check(k8s_dir, cfg)),
    ]

    for display_name, config_key, run_fn in checks_to_run:
        if not is_check_enabled(config, config_key):
            results[display_name] = {"status": "SKIP", "message": "Disabled in config"}
            skipped += 1
            continue

        check_cfg = get_check_config(config, config_key)
        result = run_fn(check_cfg)
        results[display_name] = result

        if result["status"] == "FAIL":
            has_errors = True
        elif result["status"] == "WARN":
            has_warnings = True
        elif result["status"] == "SKIP":
            skipped += 1

    # Summary
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    warned = sum(1 for r in results.values() if r["status"] == "WARN")
    failed = sum(1 for r in results.values() if r["status"] == "FAIL")

    # Prepare JSON output if requested
    if getattr(args, "output", "text") == "json":
        import json
        
        overall = "GO"
        if has_errors:
            overall = "BLOCK"
        elif has_warnings:
            overall = "CAUTION"
            
        ddr_path = write_ddr(project, environment, overall, results)
        write_github_step_summary(project, environment, overall, results, ddr_path)
        
        json_data = {
            "project": project,
            "environment": environment,
            "timestamp": time.time(),
            "overall_decision": overall,
            "summary": {
                "passed": passed,
                "warned": warned,
                "failed": failed,
                "skipped": skipped
            },
            "checks": results
        }
        print(json.dumps(json_data, indent=2))
        if has_errors:
            sys.exit(1)
        return

    # Display pretty results (Text mode)
    print_panel(
        "Graveyard — Deploy Check",
        f"{project} → {environment}"
    )

    if config_found:
        config_label = args.config if args.config else ".graveyard.yml"
        print(f"  {C.DIM}Config: {config_label}{C.END}")
    else:
        print(f"  {C.DIM}Config: using defaults (no .graveyard.yml found){C.END}")
    print()

    for name, result in results.items():
        display_result(name, result)
        time.sleep(0.05)

    print(f"\n  {'─' * 48}")
    print(f"  {C.DIM}Checks: {passed} passed, {warned} warned, {failed} failed, {skipped} skipped{C.END}\n")

    # Final Decision
    overall_decision = "GO"
    if has_errors:
        overall_decision = "BLOCK"
    elif has_warnings:
        overall_decision = "CAUTION"

    # Write audit trail
    ddr_path = write_ddr(project, environment, overall_decision, results)
    write_github_step_summary(project, environment, overall_decision, results, ddr_path)
    
    if ddr_path:
        print(f"  {C.CYAN}📄 DDR Saved:{C.END} {C.DIM}{ddr_path}{C.END}\n")

    if has_errors:
        print(f"  {C.RED}{C.BOLD}🛑 DEPLOY BLOCKED{C.END}")
        print(f"  {C.DIM}Critical policies failed. Fix issues and re-run.{C.END}")
        sys.exit(1)
    elif has_warnings:
        print(f"  {C.YELLOW}{C.BOLD}🟡 DEPLOY WITH CAUTION{C.END}")
        print(f"  {C.DIM}Non-critical warnings detected. Review before deploying.{C.END}")
    else:
        print(f"  {C.GREEN}{C.BOLD}✅ GO FOR DEPLOYMENT{C.END}")
        print(f"  {C.DIM}All checks passed.{C.END}")

    print()


def cmd_demo(args):
    """Run a built-in demo showing Graveyard in action with sample data."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    app_root = os.path.dirname(os.path.dirname(script_dir))

    # Find sample data
    sample_tests = os.path.join(app_root, "tests", "sample-results", "passing.xml")
    sample_k8s = os.path.join(app_root, "tests", "sample-k8s", "bad-deployment.yaml")

    print()
    print(f"  {C.CYAN}{C.BOLD}🪦 Graveyard Demo{C.END}")
    print(f"  {C.DIM}Showing what happens when your past incidents catch a bad deploy...{C.END}")
    print()

    # Build a demo namespace with default args
    demo_args = argparse.Namespace(
        config=None,
        tests=sample_tests if os.path.exists(sample_tests) else None,
        k8s_dir=sample_k8s if os.path.exists(sample_k8s) else None,
        image=None,
        namespace=None,
        output="text",
    )

    # Temporarily change to app root so incidents/ is found
    original_cwd = os.getcwd()
    os.chdir(app_root)
    try:
        cmd_check(demo_args)
    except SystemExit:
        pass  # Don't exit on BLOCK during demo
    finally:
        os.chdir(original_cwd)

    print(f"  {C.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.END}")
    print(f"  {C.BOLD}That's Graveyard.{C.END}")
    print("  Your team's past incidents just blocked a bad deploy.")
    print("  A Deploy Decision Record was saved to deploy-records/.")
    print()
    print(f"  {C.DIM}Next steps:{C.END}")
    print(f"  {C.DIM}  graveyard init    → Set up Graveyard in your project{C.END}")
    print(f"  {C.DIM}  graveyard check   → Run checks against your own code{C.END}")
    print()


def cmd_init(args):
    """Initialize Graveyard in the current project."""
    print()
    print(f"  {C.CYAN}{C.BOLD}🪦 Graveyard Init{C.END}")
    print()

    # Detect project structure
    detections = []

    if os.path.exists("requirements.txt") or os.path.exists("setup.py") or os.path.exists("pyproject.toml"):
        detections.append(("Python project", "pytest"))
    if os.path.exists("package.json"):
        detections.append(("Node.js project", "jest/vitest"))
    if os.path.exists("go.mod"):
        detections.append(("Go project", "go test"))

    # K8s manifests
    k8s_dirs = []
    for d in ["k8s", "kubernetes", "deploy", "manifests", "helm"]:
        if os.path.isdir(d):
            k8s_dirs.append(d)
            detections.append((f"K8s manifests in ./{d}/", "manifest validation"))

    # CI
    if os.path.exists(".github/workflows"):
        detections.append(("GitHub Actions", "CI integration"))
    if os.path.exists(".gitlab-ci.yml"):
        detections.append(("GitLab CI", "CI integration"))
    if os.path.exists("Jenkinsfile"):
        detections.append(("Jenkins", "CI integration"))

    # Dockerfile
    if os.path.exists("Dockerfile"):
        detections.append(("Dockerfile", "image scanning"))

    for name, detail in detections:
        print(f"  {C.GREEN}✓ Detected:{C.END} {name} ({detail})")

    if not detections:
        print(f"  {C.DIM}No specific project structure detected \u2014 using defaults.{C.END}")

    print()

    # Create .graveyard.yml
    if os.path.exists(".graveyard.yml"):
        print(f"  {C.YELLOW}⚠  .graveyard.yml already exists — skipping.{C.END}")
    else:
        project_name = os.path.basename(os.getcwd())
        k8s_section = ""
        if k8s_dirs:
            k8s_section = """
  k8s:
    enabled: true
    namespace: default
    require_limits: true
    require_probes: true
    min_replicas: 2"""

        config_content = f"""# Graveyard — Deploy Gate Configuration
# Docs: https://github.com/mumernadeem/graveyard
project: "{project_name}"
environment: "production"

checks:
  tests:
    enabled: true
    min_pass_rate: 90

  security:
    enabled: true
    block_on: CRITICAL
    max_high: 5{k8s_section}

  cost:
    enabled: true
    warn_threshold: 200
    provider: aws
"""
        with open(".graveyard.yml", "w") as f:
            f.write(config_content)
        print(f"  {C.GREEN}✓ Wrote{C.END} .graveyard.yml")

    # Create incidents/ directory
    if os.path.isdir("incidents"):
        print(f"  {C.YELLOW}⚠  incidents/ directory already exists — skipping.{C.END}")
    else:
        os.makedirs("incidents", exist_ok=True)
        template = """# Incident: [Title — What Broke]
# Date: YYYY-MM-DD
# Severity: P1
# Service: [service-name]

## What Happened

[Describe the incident timeline. When was it detected? How long was the impact?
What was the blast radius? How was it resolved?]

## Root Cause

[What was the underlying technical cause? Why did existing safeguards miss it?]

## What We Should Have Checked

- [List the checks that would have prevented this deploy]
- [Be specific — URLs, thresholds, conditions]

## Deploy Rules

```graveyard
# Example: Block deploys on Fridays after 4 PM
# - type: deploy_window
#   block_days: friday
#   block_after: "16:00"

# Example: Require a dependency to be healthy
# - type: dependency
#   url: https://your-service.internal/health
#   name: Your Service Health

# Example: Raise the test pass rate
# - type: min_pass_rate
#   value: 98
```
"""
        with open("incidents/TEMPLATE.md", "w") as f:
            f.write(template)
        print(f"  {C.GREEN}✓ Created{C.END} incidents/ with postmortem template")

    # Create deploy-records/
    os.makedirs("deploy-records", exist_ok=True)
    print(f"  {C.GREEN}✓ Created{C.END} deploy-records/ (audit trail)")

    print()
    print(f"  {C.BOLD}Done!{C.END} Next steps:")
    print(f"  {C.DIM}  1. Write your first postmortem in incidents/{C.END}")
    print(f"  {C.DIM}  2. Run: graveyard check --tests ./results{C.END}")
    print(f"  {C.DIM}  3. Run: graveyard demo  (to see it in action){C.END}")
    print()


def cmd_validate(args):
    """Validate .graveyard.yml and incident files for errors."""
    from checks.incident_check import parse_incident_file

    print()
    print(f"  {C.CYAN}{C.BOLD}🪦 Graveyard Validate{C.END}")
    print()

    errors = []
    warnings = []
    ok_count = 0

    # Validate .graveyard.yml
    config_path = args.config or ".graveyard.yml"
    if os.path.exists(config_path):
        config, found = load_config(config_path)
        if found:
            # Check for common mistakes
            checks = config.get("checks", {})
            for check_name in ["tests", "security", "k8s", "cost", "dependencies"]:
                cfg = checks.get(check_name, {})
                if check_name == "tests":
                    rate = cfg.get("min_pass_rate", 95)
                    if isinstance(rate, (int, float)) and (rate < 0 or rate > 100):
                        errors.append(f"{config_path}: min_pass_rate must be 0–100, got {rate}")
                    else:
                        ok_count += 1
                if check_name == "security":
                    block = cfg.get("block_on", "CRITICAL")
                    valid_sev = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
                    if isinstance(block, str) and block.upper() not in valid_sev:
                        errors.append(f"{config_path}: block_on must be one of {valid_sev}, got '{block}'")
                    else:
                        ok_count += 1
                if check_name == "cost":
                    provider = cfg.get("provider", "blended")
                    valid_providers = ["aws", "gcp", "azure", "hetzner", "digitalocean", "linode", "blended"]
                    if isinstance(provider, str) and provider.lower() not in valid_providers:
                        warnings.append(f"{config_path}: unknown provider '{provider}' — will use blended rates")
                    else:
                        ok_count += 1
            print(f"  {C.GREEN}✓{C.END} {config_path} — parsed OK")
        else:
            warnings.append(f"{config_path} exists but could not be parsed")
    else:
        warnings.append(f"No {config_path} found — will use defaults")

    # Validate incident files
    incidents_dir = "incidents"
    if os.path.isdir(incidents_dir):
        valid_types = [
            "deploy_window", "min_pass_rate", "min_replicas",
            "dependency", "security_scan", "image_tag",
            "custom_command", "blast_radius", "env_check"
        ]
        type_suggestions = {}
        for vt in valid_types:
            # Generate common typos
            type_suggestions[vt.replace("_", "")] = vt
            type_suggestions[vt.replace("_", "-")] = vt

        md_files = [f for f in os.listdir(incidents_dir) if f.endswith(".md") and f != "TEMPLATE.md"]

        for filename in sorted(md_files):
            filepath = os.path.join(incidents_dir, filename)
            incident = parse_incident_file(filepath)

            if not incident["rules"]:
                warnings.append(f"{filepath}: no Deploy Rules found (missing ```graveyard block?)")
                continue

            file_ok = True
            for i, rule in enumerate(incident["rules"], 1):
                rule_type = rule.get("type", "")
                if rule_type not in valid_types:
                    suggestion = type_suggestions.get(rule_type.replace("_", "").replace("-", ""), "")
                    hint = f' (did you mean "{suggestion}"?)' if suggestion else ""
                    errors.append(f"{filepath}:rule#{i} — unknown type: '{rule_type}'{hint}")
                    file_ok = False
                else:
                    # Type-specific validation
                    if rule_type == "deploy_window":
                        if not rule.get("block_days"):
                            warnings.append(f"{filepath}:rule#{i} — deploy_window missing 'block_days'")
                    if rule_type == "dependency":
                        url = rule.get("url", "")
                        if not url.startswith("http"):
                            errors.append(f"{filepath}:rule#{i} — dependency url must start with http(s)://")
                            file_ok = False
                    if rule_type == "min_pass_rate":
                        val = rule.get("value", 0)
                        if isinstance(val, (int, float)) and (val < 0 or val > 100):
                            errors.append(f"{filepath}:rule#{i} — min_pass_rate must be 0–100, got {val}")
                            file_ok = False
                    if rule_type == "custom_command":
                        cmd = rule.get("run") or rule.get("command")
                        if not cmd:
                            errors.append(f"{filepath}:rule#{i} — custom_command requires 'run' or 'command'")
                            file_ok = False
                    if rule_type == "blast_radius":
                        if not rule.get("max_lines") and not rule.get("max_files"):
                            warnings.append(f"{filepath}:rule#{i} — blast_radius should specify 'max_lines' or 'max_files'")
                    if rule_type == "env_check":
                        if not (rule.get("required_vars") or rule.get("required_var") or rule.get("required")):
                            errors.append(f"{filepath}:rule#{i} — env_check requires 'required_vars'")
                            file_ok = False

            if file_ok:
                ok_count += len(incident["rules"])
                print(f"  {C.GREEN}✓{C.END} {filepath} — {len(incident['rules'])} rules valid")
            else:
                print(f"  {C.RED}✗{C.END} {filepath} — has errors")
    else:
        warnings.append("No incidents/ directory found")

    # Summary
    print()
    if errors:
        for e in errors:
            print(f"  {C.RED}❌ ERROR:{C.END} {e}")
    if warnings:
        for w in warnings:
            print(f"  {C.YELLOW}⚠  WARN:{C.END}  {w}")

    print()
    total = ok_count + len(errors)
    if errors:
        print(f"  {C.RED}{C.BOLD}Validation failed:{C.END} {len(errors)} errors, {len(warnings)} warnings ({ok_count}/{total} checks OK)")
        sys.exit(1)
    elif warnings:
        print(f"  {C.YELLOW}{C.BOLD}Validation passed with warnings:{C.END} {len(warnings)} warnings ({ok_count} checks OK)")
    else:
        print(f"  {C.GREEN}{C.BOLD}All validations passed:{C.END} {ok_count} checks OK")
    print()


def cmd_rules(args):
    """List all active incident rules extracted from postmortems."""
    from checks.incident_check import parse_incident_file

    incidents_dir = getattr(args, "dir", "incidents") or "incidents"
    if not os.path.isdir(incidents_dir):
        print(f"\n  {C.YELLOW}⚠ No incidents directory found at ./{incidents_dir}{C.END}\n")
        return

    files = [f for f in sorted(os.listdir(incidents_dir)) if f.endswith(".md") and f != "TEMPLATE.md"]
    if not files:
        print(f"\n  {C.DIM}No incident postmortems found in ./{incidents_dir}{C.END}\n")
        return

    all_rules = []
    for f in files:
        path = os.path.join(incidents_dir, f)
        incident = parse_incident_file(path)
        for r in incident.get("rules", []):
            all_rules.append({
                "rule": r,
                "title": incident.get("title") or f,
                "severity": incident.get("severity") or "P3",
                "file": f,
            })

    print_panel("Graveyard — Active Incident Rules", f"{len(files)} postmortems → {len(all_rules)} deploy rules")

    if not all_rules:
        print(f"  {C.DIM}No rules found in postmortems.{C.END}\n")
        return

    print(f"  {C.BOLD}{'Rule Type / Details':<42} {'Source Incident':<26} {'Severity':<8}{C.END}")
    print(f"  {C.DIM}{'─' * 78}{C.END}")

    for item in all_rules:
        r = item["rule"]
        rtype = r.get("type", "unknown")
        detail = ""
        if rtype == "deploy_window":
            detail = f"block {r.get('block_days', '')} after {r.get('block_after', 'all day')}"
        elif rtype == "min_pass_rate":
            detail = f"min pass rate: {r.get('value')}%"
        elif rtype == "dependency":
            detail = f"healthcheck: {r.get('name') or r.get('url')}"
        elif rtype == "min_replicas":
            detail = f"min replicas: {r.get('value')}"
        elif rtype == "image_tag":
            detail = "block :latest tag"
        elif rtype == "security_scan":
            detail = f"block on {r.get('block_on', 'CRITICAL')}"
        elif rtype == "custom_command":
            detail = f"run: {r.get('name') or r.get('run') or r.get('command')}"
        elif rtype == "blast_radius":
            detail = f"max lines: {r.get('max_lines', '-')} files: {r.get('max_files', '-')}"
        elif rtype == "env_check":
            detail = f"require: {r.get('required_vars') or r.get('required')}"
        else:
            detail = str(r)

        display_text = f"{rtype}: {detail}"[:40]
        title = item["title"][:24]
        sev = item["severity"]
        sev_color = C.RED if sev == "P1" else C.YELLOW if sev == "P2" else C.CYAN

        print(f"  {C.BOLD}{display_text:<42}{C.END} {title:<26} {sev_color}{sev:<8}{C.END}")

    print(f"\n  {C.DIM}Run 'graveyard check' to enforce these rules against your deploy.{C.END}\n")


def cmd_learn(args):
    """Ingest a postmortem file or text and extract Graveyard deploy rules."""
    from incident_learner import learn_incident

    source = args.source
    if not source:
        print(f"\n  {C.RED}❌ ERROR: Please provide an incident file or text to analyze.{C.END}")
        print(f"  {C.DIM}Usage: graveyard learn path/to/postmortem.md [--save]{C.END}\n")
        return

    print_panel("Graveyard — Incident Rule Learner", "Converting postmortem into deploy gates")

    result = learn_incident(
        source,
        save_dir="incidents",
        output_file=args.out,
        auto_save=args.save
    )

    data = result["data"]
    rules = data.get("rules", [])
    engine_name = result["engine"]

    print(f"  {C.CYAN}Analysis Engine:{C.END} {engine_name}")
    print(f"  {C.CYAN}Incident Title:{C.END}  {C.BOLD}{data.get('title')}{C.END}")
    print(f"  {C.CYAN}Date & Severity:{C.END} {data.get('date')} ({data.get('severity')})")
    print(f"  {C.CYAN}Service Target:{C.END}  {data.get('service')}")
    print(f"  {C.CYAN}Extracted Rules:{C.END} {len(rules)} rule(s) inferred\n")

    print(f"  {C.DIM}Generated Postmortem & Deploy Rules:{C.END}")
    print(f"  {C.DIM}{'─' * 52}{C.END}")
    for line in result["markdown"].split("\n"):
        print(f"    {line}")
    print(f"  {C.DIM}{'─' * 52}{C.END}\n")

    if result.get("saved_to"):
        print(f"  {C.GREEN}✓ Saved to:{C.END} {result['saved_to']}")
        print(f"  {C.DIM}Run 'graveyard validate' to verify rules.{C.END}\n")
    else:
        print(f"  {C.YELLOW}Tip:{C.END} Pass {C.BOLD}--save{C.END} to automatically write this to {C.BOLD}incidents/{C.END}\n")


def main():
    parser = argparse.ArgumentParser(
        prog="graveyard",
        description="Graveyard — Incident-Trained Deploy Gates.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── check command ──
    check_parser = subparsers.add_parser("check", help="Run all pre-deployment checks")
    check_parser.add_argument("--config", help="Path to .graveyard.yml config file")
    check_parser.add_argument("--k8s-dir", dest="k8s_dir", help="Path to K8s deployment YAML files or directory")
    check_parser.add_argument("--tests", help="Path to test results directory (JUnit XML)")
    check_parser.add_argument("--image", help="Container image to scan")
    check_parser.add_argument("--namespace", help="Override K8s namespace from config")
    check_parser.add_argument("--output", choices=["text", "json"], default="text", help="Output format")

    # ── demo command ──
    subparsers.add_parser("demo", help="Run a built-in demo with sample data")

    # ── init command ──
    subparsers.add_parser("init", help="Initialize Graveyard in the current project")

    # ── validate command ──
    validate_parser = subparsers.add_parser("validate", help="Validate config and incident files")
    validate_parser.add_argument("--config", help="Path to .graveyard.yml config file")

    # ── rules command ──
    rules_parser = subparsers.add_parser("rules", help="List all active rules extracted from postmortems")
    rules_parser.add_argument("--dir", default="incidents", help="Path to incidents directory (default: incidents)")

    # ── learn command ──
    learn_parser = subparsers.add_parser("learn", help="Convert an incident postmortem into deploy rules")
    learn_parser.add_argument("source", help="Path to postmortem file or raw incident description")
    learn_parser.add_argument("--save", action="store_true", help="Automatically save to incidents/ directory")
    learn_parser.add_argument("--out", help="Specific destination filepath for the generated postmortem")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check(args)
    elif args.command == "demo":
        cmd_demo(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "rules":
        cmd_rules(args)
    elif args.command == "learn":
        cmd_learn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

