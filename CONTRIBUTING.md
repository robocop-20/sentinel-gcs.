# Contributing to Sentinel GCS

This is a private team repository. Contributions must preserve the system's
separation between deterministic safety rules and optional advisory services.

## Before you start

1. Read [Team setup](docs/TEAM_SETUP.md) and create your own local `.env`.
2. Make a branch for one focused change.
3. Do not add camera URLs, credentials, evidence, personal data, model output,
   training images, or generated database files to Git.

## Required checks

Run the checks relevant to your change before opening a pull request:

```powershell
python -m pytest -q
python -m ruff check app tests
python -m bandit -q -r app -x tests -ll
```

GitHub Actions is the final gate. Do not merge a failed CI run without first
understanding and correcting the failure.

## Change boundaries

- Keep critical detection, tracking, geofence, and risk outcomes deterministic.
- Treat LLM output as advisory input only; it must not issue automatic critical
  actions or change a detection result.
- Add or change models only with a documented evaluation and release record.
- Add tests for every defect fix and behavioural change.
- Update the operator/deployment documentation when configuration or workflow
  changes.

## Pull requests

Use the pull-request template, describe the operational impact, and include
the tests you ran. Small, reviewable pull requests are preferred.
