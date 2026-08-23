# V2X Device Connection Runbook

Sentinel connects peers through an authenticated network gateway. The current
wire profile is `sentinel-v2x/1` over MQTT QoS 1. It is an integration profile,
not a claim of SAE J2735, ETSI ITS-G5, C-V2X or defence certification.

## Device paths

| Device | Physical/network adapter | Sentinel role |
|---|---|---|
| Drone | Flight controller to MAVLink; companion computer to MQTT/mTLS | Publishes telemetry through the MAVLink adapter and receives signed advisory events. |
| IP camera | Camera RTSP/HTTPS to a hardened edge gateway | Gateway publishes heartbeat and fulfils approved evidence requests; the camera does not receive commands. |
| Patrol vehicle | Vehicle computer or rugged tablet to MQTT/mTLS | Publishes heartbeat and displays verified events for an operator. |
| Port infrastructure | Existing VMS/PLC/PSIM integration gateway | Translates authorised alarms into the site protocol; safety PLC actions stay deterministic and separate. |

## Production trust boundary

1. Place an MQTT gateway behind an authenticated VPN/private APN.
2. Issue one client certificate and broker ACL per device; do not share a
   fleet-wide certificate.
3. Set `MQTT_TLS_ENABLED=true`, the CA path, and the device certificate/key.
4. Restrict each device to `sentinel/v2x/events` and
   `sentinel/v2x/heartbeats` as appropriate.
5. Provision a unique device ID and rotate the HMAC secret through a secrets
   manager. The included shared-secret baseline should be replaced with
   per-device keys or signed tokens before multi-organisation deployment.
6. Verify clock synchronisation, certificate revocation, replay rejection,
   offline timeout, and broker failover in field trials.

## Peer agent

Run the reference adapter on a companion computer or gateway with:

```text
ENABLE_V2X=true
V2X_DEVICE_ID=patrol-vehicle-07
V2X_DEVICE_TYPE=vehicle
V2X_DEVICE_CAPABILITIES=event-receiver,gps
MQTT_HOST=your-private-gateway
MQTT_PORT=8883
MQTT_TLS_ENABLED=true
MQTT_CA_CERT=/certs/ca.crt
MQTT_CLIENT_CERT=/certs/patrol-vehicle-07.crt
MQTT_CLIENT_KEY=/certs/patrol-vehicle-07.key
```

Then start `python -m app.v2x_peer`. The peer publishes signed heartbeats and
accepts only fresh, correctly signed events. It does not control actuators,
flight systems, barriers, sirens or weapons.
