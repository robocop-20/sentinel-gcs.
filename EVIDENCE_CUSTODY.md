# Evidence integrity, retention and provenance

This control set is engineered toward defense-grade rigor; it is not a
certification or an authorisation to deploy.

## Artifact lifecycle

Evidence capture remains opt-in and excludes people. Each accepted non-person
crop is JPEG-encoded in memory, encrypted with AES-256-GCM and written under a
unique, immutable evidence ID. The encrypted envelope is never reused or
overwritten. The worker then creates a canonical JSON manifest containing the
artifact SHA-256, size, creation time, anonymous track ID and encryption format.
An HMAC-SHA-256 over that manifest detects metadata tampering.

The API registers each artifact independently in `evidence_records`; evidence
records are never coalesced with ordinary track-state writes. Registration
includes the model release/version and model-weights SHA-256, source camera,
source-frame timestamp, retention deadline and legal-hold state.

Use the authenticated integrity check:

```text
GET /api/evidence/{evidence_id}/verify
```

It recomputes the encrypted artifact hash and manifest HMAC, and compares the
result with the independent database hash. A successful result does not prove
that an object classification is correct; it proves only that the registered
artifact and metadata have not changed since capture.

## Retention and legal hold

`evidence-retention` is a dedicated non-root service with read/write access to
the evidence directory and mTLS-only database access. The API keeps evidence
read-only. The retention worker deletes only records that are both beyond
`EVIDENCE_RETENTION_DAYS` and not on legal hold. It resolves every target path
and rejects paths outside `EVIDENCE_DIR` before deletion.

Only System-Admin may change a legal hold:

```text
POST /api/evidence/{evidence_id}/legal-hold
{"legal_hold":true,"justification":"case or incident reference"}
```

Every change requires a justification and is written to the append-only audit
chain. Purging removes the encrypted artifact and signed manifest, then records
`purged_at`; the database custody record remains.

## Event provenance and review

Every local event carries:

- source camera and source-frame/capture timestamps;
- detector name, release version, weights SHA-256 and release-integrity state;
- raw detector confidence;
- content-addressed geofence version;
- linked evidence ID and SHA-256 when evidence exists;
- operator-reviewed state, reviewer and review timestamp.

Event acknowledgement requires a human justification. It updates the event
provenance and persistent review fields and appends an audit-chain record. LLM
advice remains separate and cannot set any of these human-review fields.

## Operator controls

- Set `ENABLE_EVIDENCE_CAPTURE=true` only under an approved collection policy.
- Set `EVIDENCE_RETENTION_DAYS` to the approved site retention period.
- Monitor the `evidence-retention` readiness endpoint and filesystem capacity.
- Place production evidence and database storage on encrypted managed volumes.
- Export custody records to independently controlled immutable storage where
  policy requires it.
- Never treat a passing hash check as model accuracy, identity, or legal proof
  without the applicable investigative process.
