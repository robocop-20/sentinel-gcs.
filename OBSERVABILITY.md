# Engineering observability

The engineering observability plane is separate from the operator console. It
is for maintenance, capacity, SLA and incident review; it must not be used to
issue flight or enforcement commands.

## Start

After the authenticated TLS stack has been bootstrapped:

```powershell
docker compose --profile ops up -d --build
```

Local-only endpoints are:

- Grafana: `http://127.0.0.1:3001`
- Prometheus: `http://127.0.0.1:9090`
- Alertmanager: `http://127.0.0.1:9093`

The Grafana account is `sentinel-admin`; its generated password is the ignored
Docker secret `secrets/grafana-admin-password`. Retrieve it through the site's
approved secret-access process. Do not put it in screenshots or tickets.

## Security boundary

Prometheus scrapes `https://api:8080/metrics` with its own mTLS certificate.
The edge gateway explicitly returns 404 for `/metrics`, so the scrape surface
is not part of the browser/API boundary. Grafana anonymous access and sign-up
are disabled. All three engineering ports bind to loopback only.

## Signals

The provisioned `Sentinel Engineering Operations` dashboard covers:

- dependency/service availability;
- inference and end-to-end p50/p95/p99 latency;
- capture and inference FPS plus frame drop ratio;
- anonymous track-ID churn;
- pipeline and durable-outbox depth/age;
- critical dead letters and circuit-breaker state;
- security event rate and advisory-only LLM latency.

W3C `traceparent` and `X-Correlation-ID` are accepted and returned by the API.
The vision worker derives a stable trace ID from each detection batch, and the
background fusion worker binds that same trace and correlation identity to its
structured JSON logs. Pixels, camera URLs and tokens are not trace attributes.

## Alerts

Eight rules cover service loss, p95 vision latency, frame drops, track churn,
queue backpressure, stalled durable delivery, dead letters and open circuits.
The default receiver keeps alerts inside the isolated Alertmanager console.
External webhook delivery is intentionally not enabled without site approval
because alert metadata may reveal operational state.

After approval, adapt
`infra/alertmanager/alertmanager-webhook.example.yml`, mount an
`alert-webhook-url` secret, validate with `amtool check-config`, and record the
recipient, retention and revocation owner. Deterministic rules remain the alert
authority; an LLM never suppresses or raises these infrastructure alarms.

