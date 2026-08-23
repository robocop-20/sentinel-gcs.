# Sentinel GCS operator interface

The root URL serves a map-first ground-control workstation with four operator
workspaces:

- **Flight** shows the local tactical map, restricted zones, anonymous tracks,
  connected-vehicle position, flight instruments, primary EO preview, alerts,
  V2X peers, and software-layer state.
- **Plan** enables local waypoint placement. New, Undo, Clear, zoom, route
  distance, estimated time, maximum range, and JSON Export operate locally in
  the browser. The draft is marked unsent and the vehicle Upload control stays
  disabled until an authorised MAVLink mission service is commissioned.
- **Sensors** provides a four-channel wall. EO-01 is the real annotated preview;
  IR-01, PORT-02, and VEH-01 deliberately show Not Linked until corresponding
  RTSP/VMS/V2X endpoints exist.
- **Systems** expands all API-reported layers and their current readiness,
  dependency, scope, or authority boundary.

Mission drafts use the `sentinel-mission/1` JSON schema and remain local. They
do not modify geofences, alert rules, flight controllers, or connected V2X
devices. Imported plans and vehicle upload require a separate reviewed API.

The bundled map is an offline vector operations grid, so the interface remains
usable without an internet tile provider. A deployment can later connect an
authority-hosted MapProxy/offline-tile service after map licensing, cache,
availability, and cybersecurity requirements are defined.

Visual tokens and component rules are maintained in `UI_DESIGN_SYSTEM.md` so
new workspaces and sensor adapters preserve the same operator-oriented design.
