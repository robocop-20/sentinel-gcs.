ALTER TABLE events ADD COLUMN IF NOT EXISTS state TEXT NOT NULL DEFAULT 'NEW';
-- sentinel:statement
ALTER TABLE events ADD COLUMN IF NOT EXISTS vehicle_id TEXT;
-- sentinel:statement
ALTER TABLE events ADD COLUMN IF NOT EXISTS camera_id TEXT;
-- sentinel:statement
ALTER TABLE events ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;
-- sentinel:statement
ALTER TABLE events ADD COLUMN IF NOT EXISTS rule_id TEXT;
-- sentinel:statement
ALTER TABLE events ADD COLUMN IF NOT EXISTS rule_version TEXT;
-- sentinel:statement
ALTER TABLE events ADD COLUMN IF NOT EXISTS uncertainty_m DOUBLE PRECISION;
-- sentinel:statement
ALTER TABLE events ADD COLUMN IF NOT EXISTS correlation_id TEXT;

-- sentinel:statement
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'events_state_valid'
    ) THEN
        ALTER TABLE events ADD CONSTRAINT events_state_valid
        CHECK (state IN ('NEW', 'ACKNOWLEDGED', 'UNDER_REVIEW', 'RESOLVED', 'DISMISSED'));
    END IF;
END $$;

-- sentinel:statement
CREATE INDEX IF NOT EXISTS events_state_occurred_idx
ON events (state, occurred_at DESC);

-- sentinel:statement
CREATE TABLE IF NOT EXISTS missions (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    state TEXT NOT NULL,
    document JSONB NOT NULL,
    route geometry(LineString, 4326),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    updated_by TEXT NOT NULL,
    CONSTRAINT missions_state_valid CHECK (
        state IN ('DRAFT', 'VALID', 'INVALID', 'READY_TO_UPLOAD',
                  'UPLOADING', 'UPLOADED', 'UPLOAD_FAILED')
    )
);

-- sentinel:statement
CREATE INDEX IF NOT EXISTS missions_vehicle_updated_idx
ON missions (vehicle_id, updated_at DESC);

-- sentinel:statement
CREATE INDEX IF NOT EXISTS missions_route_idx ON missions USING GIST (route);

-- sentinel:statement
CREATE TABLE IF NOT EXISTS mission_waypoints (
    mission_id UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    waypoint_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    command TEXT NOT NULL,
    altitude_m DOUBLE PRECISION NOT NULL CHECK (altitude_m >= 0),
    speed_mps DOUBLE PRECISION,
    hold_time_s DOUBLE PRECISION,
    location geometry(Point, 4326) NOT NULL,
    PRIMARY KEY (mission_id, waypoint_id),
    UNIQUE (mission_id, sequence)
);

-- sentinel:statement
CREATE INDEX IF NOT EXISTS mission_waypoints_location_idx
ON mission_waypoints USING GIST (location);
