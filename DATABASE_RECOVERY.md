# Database backup and recovery runbook

This runbook covers the Sentinel ground-station PostgreSQL/PostGIS database.
It does not cover flight-controller state or aircraft firmware. Backups contain
operational security data and must be stored in an access-controlled encrypted
repository approved by the data owner.

## Recovery objectives

- Target backup interval: 15 minutes during active operations and once after a
  mission is closed.
- Engineering target RPO: 15 minutes, subject to successful scheduled backups.
- Engineering target RTO: 30 minutes on replacement ground-station hardware,
  subject to image/model availability and operator approval.
- A backup is not accepted until its SHA-256 checksum and isolated restore test
  have passed.

These are engineering targets, not availability guarantees or certification.

## Create and validate a backup

Run from a private PowerShell terminal while the stack is online:

```powershell
cd C:\Users\ASUS\Downloads\fpv
.\scripts\backup_postgres.ps1
.\scripts\test_restore_postgres.ps1 -BackupPath .\backups\sentinel-YYYYMMDDTHHMMSSZ.dump
```

The backup script produces a PostgreSQL custom archive, an SHA-256 sidecar and
JSON metadata. The validation script restores to a randomly named isolated
database, checks core tables, and deletes only that validation database.

## Approved recovery

1. Record the incident/change ticket and obtain the data owner's approval.
2. Preserve the failed database volume and current logs before changing it.
3. Verify the selected archive's provenance and checksum.
4. Run the isolated restore test above.
5. Invoke the destructive restore explicitly:

```powershell
.\scripts\restore_postgres.ps1 `
  -BackupPath .\backups\sentinel-YYYYMMDDTHHMMSSZ.dump `
  -ConfirmDatabaseReplacement
```

The script stops the API and leaves it stopped. Verify event, track and audit
counts, then restart the API/gateway under the approved change procedure.
After restart, call `/readyz`, verify the audit chain as System-Admin, and
confirm that MQTT outbox depth is draining before declaring recovery complete.

## Scheduling and retention

Use an organisation-managed scheduler and encrypted backup target. Do not put
archives in Git. Retention and deletion require the authority defined for the
site; legal-hold enforcement is delivered separately in H5.
