# Operations console UI/UX specification

Status: implemented structure with static verification; multi-resolution browser screenshots remain blocked until a local browser session permits localhost access.

## Navigation

The left rail exposes ten real workspaces and keyboard-safe navigation: `FLY`, `PLAN`, `CAM`, `TRACKS`, `ALERTS`, `SENSORS`, `SYSTEMS`, `ANALYZE`, `EVIDENCE`, and `SETTINGS`. Number keys switch workspaces only when focus is not in an input. `J` selects the next event and `A` opens—but never submits—the human-review dialog. No single key sends a vehicle command.

## Workspace contracts

| Workspace | Primary operator question | Required degraded state |
|---|---|---|
| FLY | Where is the vehicle/contact and what is fresh? | NO VEHICLE, NO FIX, camera age |
| PLAN | Is the versioned mission valid and for which vehicle? | local/unsaved, conflict, invalid, hardware unavailable |
| CAM | What is each linked sensor actually delivering? | NO SENSOR FRAME / NOT LINKED |
| TRACKS | Which anonymous tracks are active and with what evidence? | lifecycle, age, approximate geolocation |
| ALERTS | Which events need review and what state are they in? | forward-only state and justified transitions |
| SENSORS | Are GNSS, IMU, LiDAR, power, link, and camera fresh? | N/A rather than zero |
| SYSTEMS | Which software layers are ready/degraded? | explicit requirements and fail-safe banner |
| ANALYZE | What bounded track/event history is available? | no claim of replay when only live history exists |
| EVIDENCE | Do stored artifacts verify and what advisories exist? | integrity unavailable/fail, advisory-only labels |
| SETTINGS | What configuration boundary is authoritative? | read-only disclosure; server authorization required |

## Visual language

Typography uses a restrained sans/monospace instrument hierarchy. Borders, spacing, and alignment—not glow or decoration—carry structure. Semantic tokens include background/panel/control, hairline/strong borders, nominal/caution/breach/selected, and primary/muted text. Critical state always includes text and/or iconography; color is never the only signal. Confidence is labelled **MODEL CONFIDENCE**, not probability or accuracy.

## Freshness and truthfulness

No LIVE workspace may fabricate GPS, battery, link, telemetry, detection, sensor health, vehicle identity, or mission speed. Missing values render `N/A`, `NO FIX`, `OFFLINE`, `UNKNOWN`, or `STALE`. Simulation must display `SIMULATION / UI VERIFICATION`. Approximate locations identify their method and show `UNCERTAINTY UNBOUNDED` unless a validated error figure exists.

## Responsive behavior

- 2560×1440: full rail, map, docks, and dense tables.
- 1920×1080: full operational layout with reduced peripheral width.
- 1366×768: panels collapse/reflow, tables scroll inside their workspace, and controls remain keyboard reachable.
- Below 980 px is a maintenance/bench layout, not an asserted field-operator workstation.

Required visual acceptance checks are no horizontal page overflow, no clipped dialogs, minimum 44 px touch targets where touch is expected, visible focus, readable labels, stable map aspect, and no hidden critical state. These checks have not been marked passed because browser access was denied during this run.

## Permissions and human factors

Viewer/analyst/auditor access is read-only according to API RBAC. Operator/administrator roles may save missions and transition events. Legal holds and audit inspection use stronger roles. High-severity acknowledgement requires typed justification. LLM content is always rendered as `AI ADVISORY`; automatic actions remain disabled.

## Data and rendering performance

Backend data rate is independent from display refresh. Track/event histories are bounded, tactical-map redraw is coalesced with `requestAnimationFrame`, preview frames replace their predecessor, and WebSocket reconnect uses bounded exponential delay. Performance must be measured in the target browser before release; no 60 FPS claim is made.
