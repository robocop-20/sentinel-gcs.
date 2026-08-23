# Sentinel operator visual system

This guide keeps future interface work consistent with the ground-control
application rather than drifting into decorative dashboard styling.

## Principles

1. The map, video, current vehicle state, and alerts are the visual priorities.
2. Neutral surfaces carry structure. Blue indicates selection; green, amber,
   and red are reserved for operational state.
3. Use sentence case for titles. Uppercase is limited to short avionics labels
   and identifiers.
4. Prefer spacing, alignment, and subtle surface changes over glowing borders,
   gradients, scan lines, or decorative reticles.
5. Never display simulated sensor data as live. Unconfigured channels must say
   `Not linked` or `No signal`.

## Core tokens

| Role | Value |
|---|---|
| Navigation | `#222b32` |
| Application background | `#dfe4e7` |
| Panel | `#ffffff` / `#f8fafb` |
| Primary text | `#1d2932` |
| Secondary text | `#687985` |
| Selection | `#1779ad` |
| Healthy | `#25845b` |
| Caution | `#a96d18` |
| Critical | `#b93c47` |

Typography uses Segoe UI Variable with Segoe UI and Arial fallbacks. Monospace
type is reserved for machine identifiers and coordinate values.

## Layout rules

- Desktop: 56 px navigation rail, flexible mission workspace, 370 px context
  dock, and a 104 px flight-instrument strip.
- The context dock follows the active workflow: payload and tracks for Flight,
  tracks and V2X for Plan, payload for Sensors, and V2X/advisory context for
  Systems.
- Do not repeat subsystem inventories in the workspace and side dock.
- Use one compact instrument strip; do not turn every telemetry value into an
  individual card.
- Prefer alignment and separators over rounded containers and decorative
  shadows.
- Compact: retain the map as the first surface and move context panels below it.
- Mobile: use a bottom workspace switcher and avoid horizontal status tables.
- Minimum interactive target: 32 px desktop and 44 px touch layouts.

Vehicle upload remains visually and functionally disabled until an authorised
MAVLink mission service is connected.
