# Tracking and Detection Tuning

The live system uses a deliberate two-threshold policy:

| Stage | Score | Purpose |
|---|---:|---|
| YOLO candidate | 0.20 | Retain weaker boxes so ByteTrack can associate a temporarily blurred or partially occluded object to an existing anonymous ID. |
| ByteTrack association | 0.40 | Update established tracks with reliable observations. |
| New ByteTrack ID | 0.45 | Avoid creating a new ID from weak one-frame detections. |
| Publication | 3 recent observations | Do not send a tentative ID to the API, rules, storage, or V2X. |
| Person publication | 0.55 | Suppress weak person claims such as a 45% window-object false positive. |

The GPU deployment also uses image size `768`.  This is a measured compromise
for the available 4 GB GPU: it gives small distant objects more pixels than
`640` while retaining real-time headroom.  Watch `last_inference_ms` and
`inference_fps` in `/api/snapshot` before increasing it further.

## What this can and cannot fix

This policy reduces ID fragmentation caused by short occlusions and varying
detector confidence.  It cannot make the standard COCO YOLO model recognise a
class it was never trained for, nor can it distinguish two visually similar
objects after a long disappearance.  Use a validated port fine-tune only when
the ordinary person/vessel/vehicle classes are insufficient for the actual
camera environment.

An LLM is deliberately outside this path.  It cannot run at camera frame rate,
cannot improve YOLO recall, and must never create or replace a ByteTrack ID.
It may only provide an asynchronous advisory review after deterministic rules
have generated an event. The advisory layer is restricted to non-person
objects (`vessel`, `vehicle`, `container`) and never receives a person crop.
