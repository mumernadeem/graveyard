# Incident: Database Connection Pool Exhaustion
# Date: 2025-03-15
# Severity: P1
# Service: billing-api

## What Happened

Deployed billing-api v2.3.1 to production at 14:32 UTC. Within 5 minutes,
the service started returning 503 errors. Investigation revealed the new
version opened 3x more database connections than the previous release,
exhausting the connection pool (max: 100).

Rollback completed at 14:51 UTC. Total downtime: 19 minutes.
Estimated revenue impact: $12,400.

## Root Cause

The ORM was configured to open a new connection per request instead of
using the connection pool. This passed all unit tests because the test
database has no connection limit.

## What We Should Have Checked

- Database health endpoint must be reachable before deploying
- Test pass rate must be above 98% (our usual 95% missed this edge case)
- At least 3 replicas must be running for billing-api

## Deploy Rules

```graveyard
- type: dependency
  url: https://db-health.internal:5432/status
  name: Billing DB Health

- type: min_pass_rate
  value: 98

- type: min_replicas
  value: 3
```
