# Future deployment and cutover procedure

**Not executed.** This is an operator-controlled future procedure. The old installation at `D:\fpv` was not inspected, modified, synchronized, overwritten, or deployed to during this engineering task.

## Preconditions

- Approved change window, named change owner, rollback owner, and acceptance authority.
- Independent backup of old application, configuration, database, certificates, keys, evidence metadata/artifacts, and audit chain; hashes verified.
- Production secrets provisioned outside source control with least privilege and rotation/revocation plan.
- Production camera/sensors/peers and network routes approved.
- Candidate release manifest includes source revision (or explicitly records unavailable Git provenance), build time, artifact/container digests, SBOM, migrations, model/calibration hashes, and test evidence.
- Candidate has passed the selected bench/HIL/controlled-field release level. `docker compose config` alone is not acceptance.

## Compare without merging blindly

Create a redacted inventory of old and candidate service versions, environment variable names, volumes, schemas, certificate subjects/expiry, ports, firewall rules, resource limits, models, calibration files, retention policy, camera-source authority, and monitoring routes. Never copy `.env`, keys, database files, or evidence trees over one another. Resolve each difference through a reviewed migration decision.

The candidate camera source remains single-authority `config/camera-source.txt`. Do not introduce a duplicate phone/IP value in `.env`, the database, or Compose.

## Staged procedure

1. Freeze writes or take an application-consistent database/evidence snapshot according to the approved window.
2. Verify backup checksum and perform an isolated restoration rehearsal before touching the live instance.
3. Build/pull artifacts by immutable digest; verify signatures/SBOM/policy results.
4. Create a separate candidate deployment path and separate volumes. Do not overwrite `D:\fpv` in place.
5. Run migration dry-run/compatibility checks on a restored copy; record row/schema/PostGIS/evidence-manifest checks.
6. Start dependencies, then API/workers/gateway. Require health and readiness, not merely running containers.
7. Authenticate and execute negative RBAC checks; verify TLS/mTLS identity and certificate dates.
8. Exercise disconnected/stale states before attaching live sources.
9. Connect controlled camera/telemetry, verify frame freshness and no fake LIVE data, then mission/GIS/event/evidence/audit/V2X paths.
10. Measure acceptance budgets and monitor an agreed observation period before declaring service.

## Acceptance checklist

All ten workspaces load; authentication/RBAC negative tests pass; dynamic camera change/reconnect passes; telemetry stale/offline behavior is explicit; mission validation and prepare-only boundary pass; geofence/risk stay deterministic; event lifecycle is auditable; evidence corruption is detected; audit chain verifies; MQTT/V2X/LLM outages degrade safely; no CRITICAL/HIGH unresolved security finding exists; backups restore in isolation; monitoring/alerts reach operators; rollback remains viable.

## Rollback

Stop candidate writes, preserve logs/evidence, capture failure state, restore routing to the untouched prior installation, and verify prior health/data. Never reverse a database migration in place unless its reviewed down-migration and restored-data test passed. Prefer restoring the pre-cutover snapshot into isolated prior-version volumes. Record trigger, timestamps, data reconciliation, integrity results, and incident review.

## Required record

Change ticket, approvals, exact commands, hashes/digests, redacted environment comparison, backup/restore evidence, migration logs, health checks, security tests, operator workflow results, performance results, incidents, rollback decision, and final acceptance signature.
