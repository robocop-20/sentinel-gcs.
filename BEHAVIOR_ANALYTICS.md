# Anonymous Behaviour Analytics

This deterministic layer uses only the existing ByteTrack ID, object class,
timestamp, and a geolocated camera observation. It does not use a face, an
embedding, an identity, or an LLM decision.

## Rules

- **Loitering:** an anonymous track stays within `LOITER_RADIUS_M` for at
  least `LOITER_WINDOW_S`.
- **Proximity warning:** a `person` is within
  `PROXIMITY_WARNING_DISTANCE_M` of a `vehicle` or `vessel`.

Events are throttled per track/pair using `BEHAVIOR_EVENT_COOLDOWN_S` and
stale histories expire after `BEHAVIOR_TRACK_TTL_S`.

## Preconditions

Both rules require valid geolocation, which requires fresh drone/camera GPS +
IMU telemetry (and calibrated camera geometry for reliable distances). Without
that input, the layer deliberately produces no positional behaviour event
rather than guessing from image pixels.

These are operator alerts, not enforcement decisions. The optional LLM can
only request additional evidence or provide an advisory explanation; it cannot
change the rules, severity, or dispatch an alert.
