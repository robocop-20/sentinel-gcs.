# OpenRouter Free Vision Advisory Layer

This project can optionally send a **local YOLO object crop** to OpenRouter's
`openrouter/free` router for a short visual cross-check. It is intended for
low-volume prototype use only: free-model availability, latency, and model
selection can vary. It is not used for person identification.

## Enable it only after review

1. Create an OpenRouter API key in your own account and understand its current
   data-handling and billing/rate-limit terms.
2. In `C:\Users\ASUS\Downloads\fpv\.env`, add the key locally; do not commit or share it:

   ```ini
   ENABLE_LLM_VERIFICATION=true
   ENABLE_EVIDENCE_CAPTURE=true
   ENABLE_EXTERNAL_LLM_EGRESS=true
   ENABLE_LLM_DETECTION_ADVISORY=true
   LLM_PROVIDER=openrouter
   LLM_API_KEY=your-key-here
   LLM_MODEL=openrouter/free
   ```

3. Restart the two relevant services:

   ```powershell
   $env:PATH = 'D:\Docker\Desktop\resources\bin;' + $env:PATH
   cd C:\Users\ASUS\Downloads\fpv
   docker compose up -d --build api
   docker compose --profile vision up -d --build vision
   Invoke-RestMethod http://localhost:8080/api/health
   ```

The vision worker saves at most one current JPEG object crop per ByteTrack ID
in `C:\Users\ASUS\Downloads\fpv\evidence`; it bounds crop size and refreshes each ID at the chosen
interval. The API mounts this directory read-only. Object crops may contain
personal or sensitive imagery, so protect and retain/delete them according to
your deployment policy.

## Safety boundary

The review prompt asks only whether the visible object supports the YOLO class.
It explicitly prohibits face/person identification. Its outputs are limited to
`confirmed`, `contradicted`, `inconclusive`, or `unavailable`, with a rationale.
They are recorded as advisory evidence only. They cannot change a detection,
track ID, geofence result, deterministic risk score, event severity, V2X
message, or critical alert. If the provider is down, slow, or rate-limited, the
bounded LLM queue drops only review work and the core pipeline continues.

The Systems workspace reports the selected provider, model, key-presence flag,
egress consent, disabled reason, and OpenRouter adapter state. It never exposes
the API-key value.

Additional camera evidence remains an asynchronous MQTT `ground/evidence/requests`
message. A trusted gateway can submit its own advisory result to
`POST /api/evidence/verifications` before the request expires.
