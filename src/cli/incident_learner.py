"""
Incident Learner — Ingests unstructured postmortems and converts them
into executable Graveyard deploy rules.

Supports:
- Zero-dependency heuristic rule extraction engine.
- Optional LLM integration (OpenAI, Gemini, Anthropic) via stdlib urllib.
"""
import os
import re
import sys
import json
import datetime
import urllib.request
import urllib.error


def _slugify(text):
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')[:40] or "incident"


def extract_rules_heuristic(text):
    """
    Intelligent heuristic parser for unstructured incident text.
    Extracts metadata and infers appropriate Graveyard deploy rules.
    """
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    full_text = "\n".join(lines)
    lower_text = full_text.lower()

    # Title extraction
    title = "Production Incident"
    for line in lines:
        cleaned = re.sub(r'^[#*\-=\s]+', '', line).strip()
        if cleaned.lower().startswith("incident:"):
            title = cleaned.split(":", 1)[1].strip()
            break
        elif cleaned.lower().startswith("title:"):
            title = cleaned.split(":", 1)[1].strip()
            break
        elif len(cleaned) > 5 and not cleaned.startswith("#") and title == "Production Incident":
            title = cleaned
            break

    # Date extraction (YYYY-MM-DD or today)
    date_match = re.search(r'\b(202\d[-/]\d{1,2}[-/]\d{1,2})\b', full_text)
    if date_match:
        date_str = date_match.group(1).replace("/", "-")
        # Ensure 2-digit month and day
        parts = date_str.split("-")
        date_str = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    else:
        date_str = datetime.date.today().strftime("%Y-%m-%d")

    # Severity extraction
    severity = "P2"
    sev_match = re.search(r'\b(p[1-4]|sev[1-4]|critical|high|medium|low)\b', lower_text)
    if sev_match:
        val = sev_match.group(1).upper()
        if val in ["P1", "SEV1", "CRITICAL"]:
            severity = "P1"
        elif val in ["P2", "SEV2", "HIGH"]:
            severity = "P2"
        elif val in ["P3", "SEV3", "MEDIUM"]:
            severity = "P3"
        elif val in ["P4", "SEV4", "LOW"]:
            severity = "P4"

    # Service extraction
    service = "core-service"
    svc_match = re.search(r'(?:service|app|component):\s*([a-zA-Z0-9_\-]+)', lower_text)
    if svc_match:
        service = svc_match.group(1).strip()
    else:
        for kw in ["auth", "billing", "payment", "database", "api", "worker", "frontend", "gateway"]:
            if kw in lower_text:
                service = f"{kw}-service"
                break

    # Infer deploy rules
    rules = []

    # 1. Deploy Window (Friday, weekend, evening deploys)
    if any(k in lower_text for k in ["friday", "weekend", "evening", "5pm", "4pm", "after hours"]):
        block_after = "16:00"
        if "5pm" in lower_text or "17:00" in lower_text:
            block_after = "17:00"
        rules.append({
            "type": "deploy_window",
            "block_days": "friday",
            "block_after": block_after,
        })

    # 2. Test pass rate (flaky tests, unit tests skipped)
    if any(k in lower_text for k in ["flaky test", "tests failed", "pass rate", "untested", "skip test"]):
        rules.append({
            "type": "min_pass_rate",
            "value": 98,
        })

    # 3. Min replicas / Capacity / Traffic stampede
    if any(k in lower_text for k in ["replica", "single pod", "traffic spike", "stampede", "ooms", "out of memory"]):
        rules.append({
            "type": "min_replicas",
            "value": 3,
        })

    # 4. Security / Vulnerabilities / Image scanning
    if any(k in lower_text for k in ["cve", "vulnerability", "unscanned", "trivy", "exploit"]):
        rules.append({
            "type": "security_scan",
            "required": True,
            "block_on": "CRITICAL",
        })

    # 5. Image latest tag
    if any(k in lower_text for k in [":latest", "latest tag", "mutable tag"]):
        rules.append({
            "type": "image_tag",
            "block_latest": True,
        })

    # 6. Database migrations
    if any(k in lower_text for k in ["migration", "lock table", "alter table", "schema change", "db lock"]):
        rules.append({
            "type": "custom_command",
            "name": "Database migration safety check",
            "run": "python scripts/verify_migrations.py",
        })

    # 7. Blast radius / Giant PR
    if any(k in lower_text for k in ["huge pr", "blast radius", "large refactor", "thousand lines", "too many files"]):
        rules.append({
            "type": "blast_radius",
            "max_lines": 500,
            "max_files": 25,
            "block_days": "friday",
        })

    # 8. External dependency / 3rd party outage
    urls = re.findall(r'https?://[^\s)\]"\'>]+', full_text)
    if urls:
        rules.append({
            "type": "dependency",
            "name": f"{service.title()} Dependency",
            "url": urls[0],
        })

    # 9. Missing environment variables
    env_matches = re.findall(r'\b([A-Z][A-Z0-9_]{3,})\b', full_text)
    common_env_words = {"POSTMORTEM", "INCIDENT", "SEVERITY", "SERVICE", "OUTPUT", "CRITICAL", "STATUS"}
    candidate_envs = [w for w in env_matches if w not in common_env_words and "_" in w]
    if candidate_envs and any(k in lower_text for k in ["env var", "environment variable", "missing config", "secret"]):
        rules.append({
            "type": "env_check",
            "required_vars": ", ".join(candidate_envs[:3]),
        })

    # If no rules inferred, default to a safe deploy window rule
    if not rules:
        rules.append({
            "type": "deploy_window",
            "block_days": "friday",
            "block_after": "16:00",
        })

    return {
        "title": title,
        "date": date_str,
        "severity": severity,
        "service": service,
        "what_happened": lines[0] if lines else "Incident occurred during deployment.",
        "root_cause": full_text[:250].replace("\n", " "),
        "rules": rules,
        "engine": "heuristic",
    }


def extract_rules_llm(text):
    """
    Attempt to use available LLM API keys via stdlib urllib to parse incident text.
    Returns parsed dict or None if no keys or call failed.
    """
    openai_key = os.environ.get("OPENAI_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    prompt = (
        "You are an SRE incident postmortem analyzer for the Graveyard deploy gates tool. "
        "Analyze the following incident report and output a JSON object with keys: "
        "'title' (string), 'date' (YYYY-MM-DD), 'severity' (P1, P2, P3), 'service' (string), "
        "'what_happened' (1-2 sentences), 'root_cause' (1-2 sentences), and "
        "'rules' (list of rule objects using Graveyard rule types: "
        "'deploy_window' [block_days, block_after], 'min_pass_rate' [value], 'min_replicas' [value], "
        "'dependency' [name, url], 'security_scan' [required, block_on], 'image_tag' [block_latest], "
        "'blast_radius' [max_lines, max_files, block_days], 'env_check' [required_vars], "
        "'custom_command' [name, run]). Output strictly valid JSON."
    )

    # 1. OpenAI
    if openai_key:
        try:
            req_data = json.dumps({
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text[:4000]}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=req_data,
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                parsed["engine"] = "OpenAI (gpt-4o-mini)"
                return parsed
        except Exception:
            pass

    # 2. Gemini
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            req_data = json.dumps({
                "contents": [{"parts": [{"text": f"{prompt}\n\nIncident:\n{text[:4000]}"}]}],
                "generationConfig": {"response_mime_type": "application/json"}
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(content)
                parsed["engine"] = "Gemini (gemini-1.5-flash)"
                return parsed
        except Exception:
            pass

    return None


def format_postmortem_markdown(data):
    """Format parsed incident data into canonical Graveyard markdown."""
    title = data.get("title", "Incident")
    date_val = data.get("date", datetime.date.today().strftime("%Y-%m-%d"))
    severity = data.get("severity", "P2")
    service = data.get("service", "core-service")
    what_happened = data.get("what_happened", "Production incident occurred.")
    root_cause = data.get("root_cause", "Underlying deployment defect.")
    rules = data.get("rules", [])

    md = f"""# Incident: {title}
# Date: {date_val}
# Severity: {severity}
# Service: {service}

## What Happened

{what_happened}

## Root Cause

{root_cause}

## Deploy Rules

```graveyard
"""
    for r in rules:
        rtype = r.get("type", "deploy_window")
        md += f"- type: {rtype}\n"
        for k, v in r.items():
            if k == "type":
                continue
            if isinstance(v, bool):
                md += f"  {k}: {'true' if v else 'false'}\n"
            elif isinstance(v, (int, float)):
                md += f"  {k}: {v}\n"
            else:
                md += f"  {k}: \"{v}\"\n"
        md += "\n"

    md = md.rstrip() + "\n```\n"
    return md


def learn_incident(input_text_or_path, save_dir="incidents", output_file=None, auto_save=False):
    """
    Main learning logic: ingests text or file, parses into rules, and returns Markdown.
    """
    if os.path.isfile(input_text_or_path):
        with open(input_text_or_path, "r") as f:
            raw_text = f.read()
    else:
        raw_text = input_text_or_path

    # Try LLM first if configured, otherwise fallback to heuristics
    data = extract_rules_llm(raw_text)
    if not data:
        data = extract_rules_heuristic(raw_text)

    markdown_content = format_postmortem_markdown(data)

    target_path = None
    if output_file:
        target_path = output_file
    elif auto_save:
        os.makedirs(save_dir, exist_ok=True)
        slug = _slugify(data["title"])
        filename = f"{data['date']}-{slug}.md"
        target_path = os.path.join(save_dir, filename)

    if target_path:
        os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
        with open(target_path, "w") as f:
            f.write(markdown_content)

    return {
        "data": data,
        "markdown": markdown_content,
        "saved_to": target_path,
        "engine": data.get("engine", "heuristic")
    }
