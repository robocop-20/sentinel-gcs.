# V2X and Advisory LLM Evidence Layer

The existing perception chain is unchanged:

```text
OpenCV -> YOLO11 -> ByteTrack -> geolocation -> geofence -> deterministic risk/event rules
```

After a local event, the optional V2X layer signs and publishes a
`sentinel-v2x/1` envelope. Its `observation` contains object type, original
model class, track ID, detector confidence, source camera ID, event location,
observation time, heading, velocity, altitude, bounding box, and geofence
transition. It is a documented Sentinel project schema, not a substitute for
SAE J2735, ETSI ITS, port-authority, aviation, or other regulated V2X profile.

`ENABLE_V2X=true` requires a unique source ID, non-empty shared secret, and an
authenticated TLS/mTLS production gateway. The included HMAC/MQTT bridge is
only a local integration baseline.

## Advisory LLM evidence flow

Set `ENABLE_LLM_VERIFICATION=true` only after an external provider, credentials,
image-retention policy, and camera gateway are approved. A local event at or
above `LLM_VERIFICATION_MIN_RISK` emits a bounded `ground/evidence/requests`
message naming any configured `EVIDENCE_CAMERA_IDS`.

An external LLM/camera adapter may obtain an authorised keyframe or additional
camera evidence and POST one of these advisory verdicts to
`/api/evidence/verifications`:

```text
confirmed | contradicted | inconclusive | unavailable
```

The API records and broadcasts that result but deliberately cannot alter a
geofence state, risk score, event severity, or critical alert. Deterministic
safety rules and operators remain responsible for alerts and action.

## Live V2X peer registry

The V2X profile now exchanges signed `sentinel-v2x/1` heartbeats on the
configured heartbeat topic. Each heartbeat contains a unique device ID, device
type, capabilities, firmware version, monotonic sequence number, and timestamp.
The API rejects invalid signatures, stale messages, and replayed sequences. A
peer is marked offline when it misses the configured heartbeat window.

Run the V2X gateway with:

```powershell
.\configure_v2x.ps1
docker compose -f docker-compose.yml --profile v2x up -d --build api v2x
```

Inspect authenticated peers at `GET /api/v2x/devices`. The mission cockpit at
`http://localhost:8080/` displays the same registry, current link state, device
role, transport, and last-seen age.

For a new drone, patrol vehicle, fixed camera, or port-infrastructure adapter,
start from `app/v2x_peer.py` and the commissioning procedure in
`V2X_DEVICE_ADAPTER.md`. The reference interface is event-only and intentionally
contains no vehicle or actuator command endpoint.

The bundled broker remains a host-local integration profile. Before field
deployment, use an authority-operated broker over a private APN/VPN, issue a
separate mTLS certificate and ACL to every device, rotate keys, synchronize
clocks, exercise offline/replay failover, and validate the chosen SAE/ETSI or
port-authority message adapter. Passing the local health checks is not a
certification or operational approval.
## Implemented optional external review adapter

The advisory evidence request now has an optional OpenRouter `openrouter/free`
vision adapter. It receives only a bounded, local YOLO object crop when the
operator explicitly enables evidence capture and supplies an API key. Its
result is asynchronous review evidence; it cannot mutate the OpenCV -> YOLO11
-> ByteTrack -> Geolocation -> Geofence -> Event/Risk path or signed V2X
payload. See `LLM_OPENROUTER.md` for the activation and privacy boundary.
