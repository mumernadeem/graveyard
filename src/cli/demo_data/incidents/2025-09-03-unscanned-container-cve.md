# Incident: Unscanned Container with Critical CVE
# Date: 2025-09-03
# Severity: P1
# Service: payment-gateway

## What Happened

A security audit on 2025-09-10 discovered that payment-gateway v3.0.2,
deployed on September 3rd, contained CVE-2025-29017 (critical RCE in
libcurl). The image was never scanned before deployment because the
Trivy step was commented out during a "quick hotfix."

The vulnerability was exploitable and the service handles PCI-scoped data.
Emergency patch deployed September 10th. Reported to PCI auditor.

## Root Cause

Developer commented out the security scan step in CI to speed up a hotfix.
No guardrail prevented deploying an unscanned image.

## What We Should Have Checked

- Container image MUST be scanned — no exceptions for hotfixes
- Block any image with CRITICAL vulnerabilities
- Payment services require zero HIGH vulnerabilities

## Deploy Rules

```graveyard
- type: security_scan
  required: true
  block_on: CRITICAL
  max_high: 0

- type: min_pass_rate
  value: 95
```
