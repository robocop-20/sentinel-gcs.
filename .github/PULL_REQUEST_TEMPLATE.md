## Summary

Describe the problem and the change in a few direct sentences.

## Operational impact

- [ ] No operational impact
- [ ] Configuration or deployment documentation updated
- [ ] Detection/tracking/rule behaviour changed
- [ ] Model or model threshold changed and release evidence is attached

## Validation

- [ ] `python -m pytest -q`
- [ ] `python -m ruff check app tests`
- [ ] `python -m bandit -q -r app -x tests -ll`
- [ ] Relevant Docker Compose profile starts successfully

## Security and data handling

- [ ] No credentials, camera URLs, evidence, databases, logs, or personal data are included.
- [ ] Any LLM change remains advisory and cannot control critical outcomes.
