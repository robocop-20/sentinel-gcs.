# Security policy

## Reporting a vulnerability

Do not include secrets, camera locations, live footage, credentials, or
exploit details in a public issue. Use the repository's private security
advisory channel or contact the repository owner directly with:

- affected component and version/commit;
- a minimal reproduction path;
- impact assessment; and
- proposed mitigation, if known.

## Operational secrets

The following must remain local and must never be committed or pasted into a
pull request, issue, log, or screenshot:

- `.env` and all API, broker, and V2X secrets;
- camera source URLs and device credentials;
- operator accounts and authentication material;
- evidence, video frames, databases, and logs; and
- biometric reference material or identity data.

Security patches should include a regression test where practical and must pass
the repository's lint, test, static-analysis, and dependency-audit gates.
