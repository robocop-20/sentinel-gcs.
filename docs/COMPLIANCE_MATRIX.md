# Engineering-practice reference matrix

This matrix tracks relevant practices only. It is not a declaration of formal compliance, certification, or authority approval.

| Reference | Applicability | Current implementation/evidence | Remaining gap |
|---|---|---|---|
| NIST SP 800-207 | service/user trust boundaries | JWT/RBAC, service credentials, mTLS paths, isolated Docker networks, peer allowlist | identity governance, continuous policy evidence, independent assessment |
| NIST SP 800-218 SSDF | secure development/release | pinned images/dependencies, tests, threat model, checksum release gate | CI-enforced review, signed provenance/SBOM, vulnerability response evidence |
| IEC 62443 concepts | industrial control security | zones/conduits, least-privilege app containers, authenticated transport, audit | formal system/security levels, asset owner requirements, independent testing |
| ISO/IEC 27001 concepts | information-security management | key/file separation, RBAC, audit, retention/legal hold, incident findings | organizational ISMS, risk owners, policies, audit/certification |
| ISO/IEC 25010 | quality attributes | functional, performance, reliability, security, usability verification plans | executed target-hardware measurements and acceptance records |
| OWASP ASVS | web/API verification | TLS, JWT, RBAC, strict inputs, body/rate limits, CSP/security headers, no WS token URL | executed ASVS checklist/DAST and session tests |
| OWASP SAMM | software assurance maturity | threat model, verification ladder, release documentation | organization-wide governance and measured maturity review |
| CIS container guidance | container hardening | pinned bases, non-root app UID, read-only roots, cap drop, no-new-privileges, networks/secrets | scanner evidence, daemon/host benchmark, runtime policy |
| SLSA concepts | supply-chain provenance | model/source hashes, pinned container bases, planned release record | isolated CI builder, signed provenance, artifact registry enforcement |

Evidence references: `docs/THREAT_MODEL.md`, `docs/REQUIREMENTS_TRACEABILITY_MATRIX.md`, `docs/PERFORMANCE_BUDGET.md`, `reports/SECURITY_VERIFICATION.md`, Compose/Dockerfiles, and test sources. Any formal claim requires scope definition, current authoritative reference versions, independent review, and retained execution evidence.
