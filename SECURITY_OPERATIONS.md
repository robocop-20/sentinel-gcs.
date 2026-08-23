# Security operations baseline

Sentinel is engineered toward high-assurance operational use. It is not a
certified military, aviation, port-security, safety or identity system.

## Secret handling

Keep `.env` outside source control and restrict it to the service operator.
Never place API keys, camera credentials, database passwords, V2X keys or
certificate private keys in screenshots, tickets, logs or chat. Committed
`.env.example` values are placeholders only.

Before a field deployment:

1. Generate unique database, MQTT, V2X and bridge secrets with an approved
   cryptographic generator and credential vault.
2. Rotate the existing development Postgres credential as a coordinated
   database operation; updating only `DATABASE_URL` will lock the API out.
3. Use different credentials for each site and environment.
4. Revoke and replace previously shared LLM/API keys.
5. Record the owner, purpose, creation, expiry and last rotation for every
   credential without recording the secret itself.
6. Prefer Docker/Kubernetes secret mounts or an organisation vault in
   production. The local Compose profile mounts ignored `secrets/` files; it
   does not bake them into images.

## First authenticated start

Run this from a private terminal before the H2 cutover:

```powershell
cd C:\Users\ASUS\Downloads\fpv
python .\scripts\bootstrap_security.py --rotate-operator
```

The prompt requires at least 14 characters. It writes only an Argon2id hash;
the plaintext operator password is neither printed nor stored.
`--rotate-operator` is mandatory for the first live cutover because the
isolated validation used an intentionally unknown temporary password.

Then start the TLS stack and open `https://localhost:8443/`:

```powershell
docker compose --profile vision -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Import `secrets\tls\ca-cert.pem` only into a dedicated development trust store
or browser profile. It is a local engineering CA, not production PKI.
Production certificates must come from the approved organisational CA/HSM
process with monitored expiry and revocation.

## Authentication and roles

- Viewer: read-only operational APIs and WebSocket.
- Operator: Viewer access plus event acknowledgement and geofence updates.
- Analyst/Auditor: human review and evidence oversight; no watchlist or identity
  endpoints exist under the current privacy architecture.
- System-Admin: audit verification and all administrative operations.
- Service: bounded ingestion routes used by vision, telemetry and V2X.

Access tokens expire after 15 minutes by default and are kept in browser
session storage, not persistent local storage. Service tokens refresh through
the client-credentials endpoint. Emergency account revocation must also rotate
the signing key and restart the API if existing tokens cannot be allowed to
reach normal expiry.

## Evidence and audit integrity

Evidence capture requires its encryption-key secret. Missing or invalid key
material stops evidence writing instead of falling back to plaintext. Historic
pre-H2 `.jpg` files are not automatically trusted or transmitted; handle them
through an approved offline migration/retention process.

`GET /api/audit/verify` requires System-Admin and checks each hash-chain link.
The database trigger rejects UPDATE and DELETE against `audit_log`. Because a
database owner remains a privileged trust boundary, production audit exports
should also be sent to an independently controlled immutable store.

New evidence uses a unique immutable encrypted artifact, SHA-256, and an
HMAC-signed manifest registered in PostGIS. `evidence-retention` enforces the
configured deadline while exempting legal holds. System-Admin legal-hold
changes and Operator event reviews require justification and enter the audit
chain. The complete procedure and limitations are in `EVIDENCE_CUSTODY.md`.

## Health semantics

- `/healthz` answers only whether a service process can serve requests.
- `/readyz` returns 503 until its critical dependencies are usable.
- `/api/readiness` remains a separate measured field-acceptance report. It must
  not be substituted for authorisation, certification or mission approval.
- A vision worker without current frames is alive but not ready. This is an
  intentional fail-visible state.

## Durable delivery and recovery

MQTT and PostgreSQL delivery use the local outbox at
`/var/lib/sentinel/durable-queue.sqlite3`. The Compose `api_state` volume must
be included in host-volume monitoring and disaster recovery. Never delete that
volume merely to clear an alert: inspect `/api/health` as an authorised Viewer
and allow the backlog to drain after the dependency recovers.

Critical MQTT records use QoS 2. A record that exhausts its normal delivery
attempts is atomically moved to `sentinel/dead-letter/events`; it still remains
durable until the broker acknowledges the dead-letter envelope. Treat any
non-zero dead-letter count as an operator incident requiring review.

Database backup and tested recovery steps are documented in
`DATABASE_RECOVERY.md`. The destructive restore command requires an explicit
switch and deliberately leaves the API stopped for post-restore verification.

## Logging

Logs are one JSON object per line. Send them to an access-controlled central
collector with immutable retention appropriate to the operator's policy. A
correlation ID may be supplied using `X-Correlation-ID`; invalid IDs are
replaced and the accepted ID is returned in the response header.

Application logs must not include:

- request/response bodies or image data;
- secrets, bearer tokens, signed URLs or camera endpoints;
- biometric templates or watchlist information;
- exact location data unless an approved audit policy explicitly requires it.

## CI and releases

The H1 workflow provides an initial automated gate. Protected branches should
require it. H7 must add hash-locked release dependencies, SBOM generation,
artifact signing, container vulnerability policy, provenance attestations and
independent penetration/field test evidence before a release is promoted.
