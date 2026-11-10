# Incident: Friday Evening Cache Stampede
# Date: 2025-06-20
# Severity: P2
# Service: user-api

## What Happened

Deployed user-api v4.1.0 at 17:45 on a Friday. The new version changed
the cache key format, effectively invalidating all cached user sessions.
This caused a cache stampede — 50,000 users hit the database simultaneously.

The database CPU spiked to 100%, causing cascading failures across
3 downstream services. Resolved at 19:22 UTC after scaling the database
and warming the cache manually.

## Root Cause

Cache key migration was not backward-compatible. The old keys expired
instantly when the new code couldn't read them.

## What We Should Have Checked

- Never deploy after 16:00 UTC on Fridays
- Redis must be reachable and responding under 50ms
- Deploy should be blocked if fewer than 2 senior engineers are online

## Deploy Rules

```graveyard
- type: dependency
  url: https://redis-health.internal/ping
  name: Redis Cache Health

- type: deploy_window
  block_days: friday
  block_after: "16:00"

- type: image_tag
  block_latest: true
```
