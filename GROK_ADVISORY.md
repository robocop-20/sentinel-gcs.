# Grok Advisory Object Review

The implementation supports xAI Grok as an optional LLM provider for one
bounded task: cross-checking a YOLO object crop and producing a short,
structured incident rationale. It does **not** identify a person, compare or
match faces, create facial embeddings, search a face gallery, or influence an
alert decision.

## Activate

Create your own xAI API key. In `C:\Users\ASUS\Downloads\fpv\.env`, set the following locally and
keep the key out of source control and chat messages:

```ini
ENABLE_EVIDENCE_CAPTURE=true
ENABLE_LLM_VERIFICATION=true
LLM_PROVIDER=xai
LLM_MODEL=grok-4.5
XAI_API_KEY=your-xai-api-key
# Required separate consent gate for sending an object crop to xAI.
ENABLE_EXTERNAL_LLM_EGRESS=true
```

Then restart the API and vision worker:

```powershell
$env:PATH = 'D:\Docker\Desktop\resources\bin;' + $env:PATH
cd C:\Users\ASUS\Downloads\fpv
docker compose --profile vision up -d --build api vision
```

Grok receives only the bounded current YOLO object crop for a high-risk event.
The adapter requests structured `confirmed`, `contradicted`, or `inconclusive`
evidence and uses `store=false`. The result is advisory and expires with its
evidence request. If Grok is unreachable, delayed, or rate-limited, the core
OpenCV -> YOLO11 -> ByteTrack -> geofence/risk -> V2X pipeline continues.

xAI API access requires an xAI API key and is billed by xAI; it is distinct
from consumer Grok chat access. Review xAI's current privacy, retention, and
billing terms before sending any camera imagery.
