"""
Incident-Trained Deploy Check
Parses postmortem markdown files and enforces the deploy rules extracted from them.

Rules are extracted from fenced code blocks marked as `graveyard`:

    ```graveyard
    - type: deploy_window
      block_days: friday
      block_after: "16:00"
    ```

This is the differentiator — nobody else does postmortem-to-policy automation.
Your worst incidents become your strongest safeguards.
"""
import os
import re
import datetime


def _parse_rules_yaml(text):
    """
    Parse a minimal YAML-like list of rules from a fenced block.
    Each rule starts with '- type: <value>' and subsequent indented
    key: value pairs belong to that rule.
    
    This is intentionally NOT a full YAML parser. It handles the specific
    structure we define for graveyard rules, and handles edge cases like:
    - URLs with colons/ports (https://example.com:8080)
    - Quoted strings
    - Boolean and numeric values
    """
    rules = []
    current_rule = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # New rule: starts with "- type:"
        if stripped.startswith("- type:"):
            if current_rule:
                rules.append(current_rule)
            rule_type = stripped.replace("- type:", "").strip()
            current_rule = {"type": rule_type}
            continue

        # Property of current rule: "key: value"
        if current_rule and ":" in stripped:
            # Split on FIRST colon only, to handle URLs with ports
            key, value = stripped.split(":", 1)
            key = key.strip().lstrip("- ")
            value = value.strip()

            # Strip quotes
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]

            # Cast booleans
            if value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False
            else:
                # Cast numbers
                try:
                    if "." in value:
                        value = float(value)
                    else:
                        value = int(value)
                except (ValueError, TypeError):
                    pass  # Keep as string

            current_rule[key] = value

    if current_rule:
        rules.append(current_rule)

    return rules


def parse_incident_file(filepath):
    """
    Parse a single incident/postmortem markdown file.
    Extracts metadata from header comments and deploy rules from
    fenced ```graveyard code blocks.
    """
    with open(filepath, "r") as f:
        content = f.read()

    incident = {
        "file": os.path.basename(filepath),
        "date": None,
        "severity": None,
        "service": None,
        "title": None,
        "rules": [],
    }

    # Extract header metadata (# comments at the top)
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# Incident:"):
            incident["title"] = line.replace("# Incident:", "").strip()
        elif line.startswith("# Date:"):
            incident["date"] = line.replace("# Date:", "").strip()
        elif line.startswith("# Severity:"):
            incident["severity"] = line.replace("# Severity:", "").strip()
        elif line.startswith("# Service:"):
            incident["service"] = line.replace("# Service:", "").strip()

    # Extract rules from fenced ```graveyard blocks
    fenced_pattern = re.compile(
        r'```graveyard\s*\n(.*?)```',
        re.DOTALL
    )
    fenced_matches = fenced_pattern.findall(content)

    for block in fenced_matches:
        rules = _parse_rules_yaml(block)
        incident["rules"].extend(rules)

    # FALLBACK: If no fenced blocks found, try the old format
    # (lines under "## Deploy Rules" section) for backward compat
    if not incident["rules"]:
        rules_section = False
        rules_text = []
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.lower() == "## deploy rules":
                rules_section = True
                continue
            if rules_section:
                if stripped.startswith("## ") and stripped.lower() != "## deploy rules":
                    break
                rules_text.append(line)

        if rules_text:
            incident["rules"] = _parse_rules_yaml("\n".join(rules_text))

    return incident


def _get_git_diff_stats():
    """Attempt to get git diff stats (files, lines). Returns dict or None."""
    import subprocess
    try:
        is_git = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5
        )
        if is_git.returncode != 0:
            return None

        base_ref = os.environ.get("GITHUB_BASE_REF")
        target = f"origin/{base_ref}...HEAD" if base_ref else "HEAD~1"

        proc = subprocess.run(
            ["git", "diff", "--shortstat", target],
            capture_output=True, text=True, timeout=5
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                ["git", "diff", "--shortstat", "HEAD"],
                capture_output=True, text=True, timeout=5
            )
            if proc.returncode != 0:
                return None

        output = proc.stdout.strip()
        if not output:
            return {"files": 0, "lines": 0}

        files = 0
        lines = 0
        m_files = re.search(r'(\d+)\s+file', output)
        if m_files:
            files = int(m_files.group(1))
        m_ins = re.search(r'(\d+)\s+insertion', output)
        if m_ins:
            lines += int(m_ins.group(1))
        m_del = re.search(r'(\d+)\s+deletion', output)
        if m_del:
            lines += int(m_del.group(1))

        return {"files": files, "lines": lines}
    except Exception:
        return None


def enforce_rules(incidents, check_cfg):
    """
    Take all parsed incidents and evaluate their rules against current state.
    Returns a list of enforced rules with pass/fail status.
    """
    results = []
    now = datetime.datetime.now()
    current_day = now.strftime("%A").lower()
    current_hour = now.hour
    current_minute = now.minute

    for incident in incidents:
        source = incident.get("title") or incident["file"]
        severity = incident.get("severity", "unknown")

        for rule in incident.get("rules", []):
            rule_type = rule.get("type", "unknown")

            # ── Deploy Window check ──────────────────────────
            if rule_type == "deploy_window":
                block_days = str(rule.get("block_days", ""))
                block_after = str(rule.get("block_after", ""))

                day_blocked = False
                if block_days:
                    for day in block_days.lower().split(","):
                        if day.strip() in current_day:
                            day_blocked = True
                            break

                if day_blocked and block_after:
                    try:
                        parts = block_after.split(":")
                        block_h = int(parts[0])
                        block_m = int(parts[1]) if len(parts) > 1 else 0
                        if current_hour > block_h or (current_hour == block_h and current_minute >= block_m):
                            results.append({
                                "status": "FAIL",
                                "rule": f"No deploys on {block_days} after {block_after}",
                                "source": source,
                                "severity": severity,
                            })
                            continue
                    except (ValueError, IndexError):
                        pass
                elif day_blocked and not block_after:
                    results.append({
                        "status": "FAIL",
                        "rule": f"No deploys on {block_days}",
                        "source": source,
                        "severity": severity,
                    })
                    continue

                results.append({
                    "status": "PASS",
                    "rule": f"Deploy window OK (not blocked: {block_days} after {block_after})",
                    "source": source,
                    "severity": severity,
                })

            # ── Min pass rate override ───────────────────────
            elif rule_type == "min_pass_rate":
                value = rule.get("value", 95)
                results.append({
                    "status": "INFO",
                    "rule": f"Test pass rate must be ≥{value}%",
                    "source": source,
                    "severity": severity,
                    "override": {"check": "tests", "field": "min_pass_rate", "value": value},
                })

            # ── Min replicas override ────────────────────────
            elif rule_type == "min_replicas":
                value = rule.get("value", 2)
                results.append({
                    "status": "INFO",
                    "rule": f"Minimum {value} replicas required",
                    "source": source,
                    "severity": severity,
                    "override": {"check": "k8s", "field": "min_replicas", "value": value},
                })

            # ── Dependency check ─────────────────────────────
            elif rule_type == "dependency":
                url = rule.get("url", "")
                name = rule.get("name", url)
                if url:
                    results.append({
                        "status": "INFO",
                        "rule": f"Check dependency: {name} ({url})",
                        "source": source,
                        "severity": severity,
                        "extra_dep": {"name": name, "url": url},
                    })

            # ── Security scan required ───────────────────────
            elif rule_type == "security_scan":
                required = rule.get("required", True)
                if required:
                    results.append({
                        "status": "INFO",
                        "rule": "Security scan is mandatory (no exceptions)",
                        "source": source,
                        "severity": severity,
                        "override": {"check": "security", "field": "required", "value": True},
                    })
                block_on = rule.get("block_on")
                if block_on:
                    results.append({
                        "status": "INFO",
                        "rule": f"Block on {block_on} vulnerabilities",
                        "source": source,
                        "severity": severity,
                        "override": {"check": "security", "field": "block_on", "value": block_on},
                    })
                max_high = rule.get("max_high")
                if max_high is not None:
                    results.append({
                        "status": "INFO",
                        "rule": f"Max {max_high} HIGH vulnerabilities allowed",
                        "source": source,
                        "severity": severity,
                        "override": {"check": "security", "field": "max_high", "value": max_high},
                    })

            # ── Image tag policy ─────────────────────────────
            elif rule_type == "image_tag":
                if rule.get("block_latest", False):
                    results.append({
                        "status": "INFO",
                        "rule": "Block :latest image tag",
                        "source": source,
                        "severity": severity,
                        "override": {"check": "k8s", "field": "block_latest", "value": True},
                    })

            # ── Custom Command check ─────────────────────────
            elif rule_type == "custom_command":
                cmd = rule.get("run") or rule.get("command")
                name = rule.get("name") or cmd or "Custom check"
                timeout_val = rule.get("timeout", 30)
                try:
                    timeout_sec = int(timeout_val)
                except (ValueError, TypeError):
                    timeout_sec = 30

                if not cmd:
                    results.append({
                        "status": "WARN",
                        "rule": "custom_command missing 'run' or 'command' attribute",
                        "source": source,
                        "severity": severity,
                    })
                else:
                    import subprocess
                    try:
                        proc = subprocess.run(
                            cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=timeout_sec
                        )
                        if proc.returncode == 0:
                            results.append({
                                "status": "PASS",
                                "rule": f"Command '{name}' passed",
                                "source": source,
                                "severity": severity,
                            })
                        else:
                            snippet = (proc.stderr or proc.stdout or "").strip()
                            if snippet:
                                first_line = snippet.split("\n")[0][:80]
                                err_detail = f": {first_line}"
                            else:
                                err_detail = f" (exit code {proc.returncode})"
                            results.append({
                                "status": "FAIL",
                                "rule": f"Command '{name}' failed{err_detail}",
                                "source": source,
                                "severity": severity,
                            })
                    except subprocess.TimeoutExpired:
                        results.append({
                            "status": "FAIL",
                            "rule": f"Command '{name}' timed out after {timeout_sec}s",
                            "source": source,
                            "severity": severity,
                        })
                    except Exception as e:
                        results.append({
                            "status": "FAIL",
                            "rule": f"Command '{name}' error: {str(e)}",
                            "source": source,
                            "severity": severity,
                        })

            # ── Blast Radius check ───────────────────────────
            elif rule_type == "blast_radius":
                max_lines = rule.get("max_lines")
                max_files = rule.get("max_files")
                block_days = str(rule.get("block_days", ""))

                day_matched = True
                if block_days:
                    day_matched = False
                    for day in block_days.lower().split(","):
                        if day.strip() in current_day:
                            day_matched = True
                            break

                if not day_matched:
                    results.append({
                        "status": "PASS",
                        "rule": f"Blast radius check not active today (active on: {block_days})",
                        "source": source,
                        "severity": severity,
                    })
                else:
                    stats = _get_git_diff_stats()
                    if stats is None:
                        results.append({
                            "status": "INFO",
                            "rule": "Blast radius skipped (no git repository or diff available)",
                            "source": source,
                            "severity": severity,
                        })
                    else:
                        failed = False
                        reasons = []
                        if max_lines is not None:
                            try:
                                max_l = int(max_lines)
                                if stats["lines"] > max_l:
                                    failed = True
                                    reasons.append(f"{stats['lines']} lines changed (max: {max_l})")
                            except (ValueError, TypeError):
                                pass

                        if max_files is not None:
                            try:
                                max_f = int(max_files)
                                if stats["files"] > max_f:
                                    failed = True
                                    reasons.append(f"{stats['files']} files changed (max: {max_f})")
                            except (ValueError, TypeError):
                                pass

                        if failed:
                            results.append({
                                "status": "FAIL",
                                "rule": f"Blast radius exceeded: {', '.join(reasons)}",
                                "source": source,
                                "severity": severity,
                            })
                        else:
                            results.append({
                                "status": "PASS",
                                "rule": f"Blast radius OK ({stats['files']} files, {stats['lines']} lines changed)",
                                "source": source,
                                "severity": severity,
                            })

            # ── Environment Variable check ───────────────────
            elif rule_type == "env_check":
                raw_vars = rule.get("required_vars") or rule.get("required_var") or rule.get("required", "")
                if isinstance(raw_vars, list):
                    var_list = [str(v).strip() for v in raw_vars if str(v).strip()]
                else:
                    var_list = [v.strip() for v in str(raw_vars).split(",") if v.strip()]

                if not var_list:
                    results.append({
                        "status": "WARN",
                        "rule": "env_check missing required variables",
                        "source": source,
                        "severity": severity,
                    })
                else:
                    env_vals = dict(os.environ)
                    if os.path.exists(".env"):
                        try:
                            with open(".env", "r") as ef:
                                for eline in ef:
                                    eline = eline.strip()
                                    if eline and not eline.startswith("#") and "=" in eline:
                                        ek, ev = eline.split("=", 1)
                                        ek = ek.strip()
                                        if ek not in env_vals:
                                            env_vals[ek] = ev.strip()
                        except Exception:
                            pass

                    missing = [v for v in var_list if not env_vals.get(v)]
                    if missing:
                        results.append({
                            "status": "FAIL",
                            "rule": f"Missing required env vars: {', '.join(missing)}",
                            "source": source,
                            "severity": severity,
                        })
                    else:
                        results.append({
                            "status": "PASS",
                            "rule": f"Required env vars present ({len(var_list)} checked)",
                            "source": source,
                            "severity": severity,
                        })

            # ── Unknown rule type ────────────────────────────
            else:
                results.append({
                    "status": "WARN",
                    "rule": f"Unknown rule type: '{rule_type}'",
                    "source": source,
                    "severity": severity,
                })

    return results


def run_incident_check(incidents_dir, check_cfg):
    """
    Main entry point for the incident-trained check.
    Reads postmortem files, extracts rules, enforces deploy-time policies.
    """
    if not incidents_dir:
        incidents_dir = "incidents"

    if not os.path.exists(incidents_dir):
        return {
            "status": "SKIP",
            "message": "No incidents/ directory found. Add postmortems to enable incident-trained gates.",
            "enforced_rules": [],
            "overrides": [],
            "extra_deps": [],
        }

    # Find all markdown files
    incident_files = []
    for root, _, files in os.walk(incidents_dir):
        for f in files:
            if f.endswith(".md"):
                incident_files.append(os.path.join(root, f))

    if not incident_files:
        return {
            "status": "SKIP",
            "message": "No postmortem files found in incidents/",
            "enforced_rules": [],
            "overrides": [],
            "extra_deps": [],
        }

    # Parse all incidents
    incidents = []
    for filepath in sorted(incident_files):
        incident = parse_incident_file(filepath)
        if incident["rules"]:
            incidents.append(incident)

    if not incidents:
        return {
            "status": "SKIP",
            "message": f"Found {len(incident_files)} postmortems but none contain Deploy Rules",
            "enforced_rules": [],
            "overrides": [],
            "extra_deps": [],
        }

    # Enforce rules
    enforced = enforce_rules(incidents, check_cfg)

    # Collect results
    total_rules = len(enforced)
    failed_rules = [r for r in enforced if r["status"] == "FAIL"]
    warn_rules = [r for r in enforced if r["status"] == "WARN"]

    # Collect overrides for other checks to consume
    overrides = [r.get("override") for r in enforced if r.get("override")]
    extra_deps = [r.get("extra_dep") for r in enforced if r.get("extra_dep")]

    # Build message
    msg_parts = []
    msg_parts.append(f"{len(incidents)} incidents → {total_rules} rules enforced")

    if failed_rules:
        for fr in failed_rules:
            msg_parts.append(f"BLOCKED: {fr['rule']} (from: {fr['source']})")

    if warn_rules:
        for wr in warn_rules:
            msg_parts.append(f"WARNING: {wr['rule']} (from: {wr['source']})")

    if failed_rules:
        return {
            "status": "FAIL",
            "message": " | ".join(msg_parts),
            "enforced_rules": enforced,
            "overrides": overrides,
            "extra_deps": extra_deps,
        }

    return {
        "status": "PASS",
        "message": " | ".join(msg_parts),
        "enforced_rules": enforced,
        "overrides": overrides,
        "extra_deps": extra_deps,
    }
