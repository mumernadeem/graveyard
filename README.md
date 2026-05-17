# 🪦 Graveyard

<p align="center">
  <img src="assets/logo.png" alt="Graveyard Logo" width="120" />
</p>

<p align="center">
  <strong>Turn your past incidents into unbreakable deploy gates.</strong><br/>
  <em>Your worst days become your strongest safeguards.</em>
</p>

<p align="center">
  <a href="https://github.com/mumernadeem/graveyard/actions/workflows/tests.yml"><img src="https://github.com/mumernadeem/graveyard/actions/workflows/tests.yml/badge.svg" alt="Tests" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9%2B-blue.svg" alt="Python: 3.9+" /></a>
  <a href="#"><img src="https://img.shields.io/badge/dependencies-zero-brightgreen.svg" alt="Zero Dependencies" /></a>
</p>

---

Graveyard reads your postmortem markdown files, extracts the *"What we should have checked"* rules, and enforces them as actual deploy policies — every deploy, automatically.

<p align="center">
  <img src="assets/terminal-demo.png" alt="Graveyard Terminal Demo" width="700" />
</p>

---

## ⚡ See it in action (30 seconds)

```bash
git clone https://github.com/mumernadeem/graveyard.git
cd graveyard
python3 src/cli/graveyard.py demo
```

You'll see Graveyard load 3 sample incidents, enforce 10 rules learned from them, catch 5 problems in a bad K8s manifest, and write a Deploy Decision Record. **No setup, no config, no dependencies — runs on Python stdlib only.**

---

## 🤔 "Why not just use OPA / Checkov / Trivy?"

| Capability | Graveyard | OPA / Gatekeeper | Checkov | Trivy | GitHub Actions |
|---|---|---|---|---|---|
| **Learns from your incidents** | ✅ **Core feature** | ❌ | ❌ | ❌ | ❌ |
| Postmortems → enforced rules | ✅ Automatic | ❌ | ❌ | ❌ | ❌ |
| Deploy-window blocking (no-Friday-deploys) | ✅ | ❌ | ❌ | ❌ | Manual |
| Audit trail per deploy (DDR) | ✅ Built-in | ❌ | ❌ | ❌ | ❌ |
| K8s manifest validation | ✅ | ✅ | ✅ | ❌ | ❌ |
| Container security scan | ✅ via Trivy | ❌ | ❌ | ✅ | ❌ |
| Test pass-rate gates | ✅ | ❌ | ❌ | ❌ | Manual |
| Cloud cost estimation | ✅ | ❌ | ✅ | ❌ | ❌ |
| Single unified GO/CAUTION/BLOCK | ✅ | ❌ | ❌ | ❌ | ❌ |

**The difference:** Other tools check *what's in your code*. Graveyard checks *what your team has learned the hard way*. Every postmortem you write becomes a permanent guard rail.

---

## 📦 Install

### Option 1 — Run the script directly (zero deps)
```bash
curl -O https://raw.githubusercontent.com/mumernadeem/graveyard/master/src/cli/graveyard.py
chmod +x graveyard.py
./graveyard.py --help
```

### Option 2 — Docker
```bash
docker run --rm -v $(pwd):/project ghcr.io/mumernadeem/graveyard:latest check
```

### Option 3 — Clone (recommended for now, until v1.0 is published)
```bash
git clone https://github.com/mumernadeem/graveyard.git
cd graveyard
python3 src/cli/graveyard.py demo
```

> **PyPI / Homebrew packages coming with v1.0.** For now the CLI is a single Python file — `pip install` is intentionally not required.

---

## 🚀 Quick Start

```bash
# 1. Initialize Graveyard in your project (auto-detects stack)
graveyard init

# 2. Add a postmortem to incidents/
cat > incidents/2025-06-20-cache-stampede.md << 'EOF'
# Incident: Friday Cache Stampede
# Date: 2025-06-20
# Severity: P2

## What Happened
We deployed Friday at 5pm. The cache schema change caused a stampede on Postgres.

## Deploy Rules

```graveyard
- type: deploy_window
  block_days: friday
  block_after: "16:00"

- type: min_pass_rate
  value: 98
```
EOF

# 3. Validate that your incident files are well-formed
graveyard validate

# 4. Run pre-deploy checks
graveyard check \
  --tests ./test-results/ \
  --image my-app:v1.2.3 \
  --k8s-dir ./k8s/
```

**Example output:**

```text
────────────────────────────────────────────────────
│             Graveyard — Deploy Check             │
│              my-project → staging                │
────────────────────────────────────────────────────

  Config: .graveyard.yml

  ✅ Incident Gates 1 incidents → 2 rules enforced
  ✅ Tests          142/142 passed (100% — threshold: 98%)
  ✅ Security       0 critical, 2 medium vulns (block on: CRITICAL)
  ✅ K8s Config     namespace=staging — limits ✓, probes ✓
  ✅ Cost Impact    Estimated $19.78/mo [AWS]

  ────────────────────────────────────────────────
  Checks: 5 passed, 0 warned, 0 failed, 0 skipped

  📄 DDR Saved: deploy-records/20260430-153022-my-project-staging-go.md

  ✅ GO FOR DEPLOYMENT
```

---

## 🧠 The Postmortem Rules Language

Graveyard parses any markdown file in `incidents/` that contains a fenced ` ```graveyard ` code block. Six rule types are supported today:

````markdown
## Deploy Rules

```graveyard
# Block deployments on specific days/times
- type: deploy_window
  block_days: friday, saturday, sunday
  block_after: "16:00"

# Override the global test pass-rate requirement
- type: min_pass_rate
  value: 99

# Require a third-party dependency to be healthy
- type: dependency
  url: https://api.stripe.com/healthcheck
  name: Stripe External API

# Enforce minimum replicas for high availability
- type: min_replicas
  value: 3

# Block insecure container configurations
- type: image_tag
  block_latest: true

# Force security scanning thresholds
- type: security_scan
  required: true
  block_on: CRITICAL
  max_high: 0
```
````

> **Looking for inspiration?** See [`examples/famous-incidents/`](./examples/famous-incidents/) for reconstructions of real-world public incidents (Knight Capital $460M loss, GitLab DB deletion, Cloudflare 2019, AWS S3, Facebook BGP, Atlassian 14-day outage) — each with the Deploy Rules that would have prevented them.

---

## 🛠 Configuration (`.graveyard.yml`)

`graveyard init` writes a sensible default for you. Or write your own:

```yaml
project: "my-app"
environment: "production"

checks:
  tests:
    enabled: true
    min_pass_rate: 90       # Incident rules can push this higher

  security:
    enabled: true
    block_on: CRITICAL

  k8s:
    enabled: true
    namespace: default
    require_limits: true
    require_probes: true
    min_replicas: 2

  cost:
    enabled: true
    warn_threshold: 100
    provider: aws           # aws | gcp | azure | hetzner | digitalocean | linode
```

Incident rules from `incidents/*.md` **override** these baselines on a per-deploy basis.

---

## 📜 Deploy Decision Records (DDRs)

Every `graveyard check` writes an immutable Markdown record to `deploy-records/`. This is your audit trail.

```markdown
# Deploy Decision Record: my-project → staging

## 📝 Metadata
- **Date:** 2026-04-30T15:30:22Z
- **Decision:** `GO`
- **Triggered By:** umer@srv670486
- **Commit:** `abc123d` (Branch: `main`)

## 🛡️ Checks Executed
| Check | Status | Details |
|---|---|---|
| Tests | ✅ PASS | 142/142 passed (100.0% — threshold: 98%) |

## 🧠 Incident-Trained Policies Enforced
| Policy | Source | Severity | Result |
|---|---|---|---|
| No deploys on friday after 16:00 | Friday Cache Stampede | P2 | ✅ |
```

Commit these to git, upload as CI artifacts, or pipe to your SOC 2 evidence system. They're plain Markdown — your auditors will love you.

---

## 🔌 CI/CD Integration

### GitHub Actions

```yaml
- uses: actions/checkout@v4
- name: Run Graveyard Deploy Gates
  uses: mumernadeem/graveyard@master
  with:
    config: .graveyard.yml
    tests: test-results/
    k8s-dir: k8s/
```

### GitLab CI

```yaml
include:
  - remote: 'https://raw.githubusercontent.com/mumernadeem/graveyard/master/gitlab-ci-template.yml'
```

### Anywhere else (raw script)

```bash
curl -O https://raw.githubusercontent.com/mumernadeem/graveyard/master/src/cli/graveyard.py
python3 graveyard.py check --tests ./results --k8s-dir ./k8s --output json
```

JSON output (`--output json`) is non-zero exit on BLOCK, perfect for any pipeline.

---

## 🧪 Built-in CLI Commands

| Command | What it does |
|---|---|
| `graveyard check` | Run all enabled checks against the current project |
| `graveyard demo` | 30-second demo using built-in sample data — zero setup |
| `graveyard init` | Detect your stack (Python/Node/Go, K8s, GitHub Actions, etc.) and write a starter config |
| `graveyard validate` | Lint `.graveyard.yml` and all incident files for typos, unknown rule types, invalid values |

---

## 📚 Documentation

- [Client Onboarding Guide](CLIENT_ONBOARDING_GUIDE.md) — full walkthrough for first-time users
- [Examples: Famous Incidents](examples/famous-incidents/) — real-world postmortems with Deploy Rules
- [Contributing](CONTRIBUTING.md) — how to add rule types, fix bugs, or contribute new incident reconstructions
- [Architecture](CONTRIBUTING.md#architecture) — how the codebase is organised

---

## 🔧 Dependencies

Graveyard's CLI runs on **Python 3.9+ standard library**. That's it.

Optional integrations (only used if you enable the corresponding check):
- **Trivy** — for `security` checks against container images. Install: [aquasecurity/trivy](https://github.com/aquasecurity/trivy)
- **PyYAML** — preferred over the bundled minimal YAML parser if installed (`pip install pyyaml`)

---

## 🤝 Contributing

PRs welcome — especially new rule types, postmortem-format improvements, and reconstructions of public incidents. See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📄 License

MIT — see [LICENSE](LICENSE).
