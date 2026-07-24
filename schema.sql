-- schema.sql: database schema for the appointment-booking bot.
-- Apply with scripts/init_db.py (or psql -f schema.sql).
-- Uses IF NOT EXISTS so re-applying against an existing database is harmless.

CREATE TABLE IF NOT EXISTS services (
    id               serial PRIMARY KEY,
    name             text NOT NULL UNIQUE,
    duration_minutes int  NOT NULL,
    active           boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS slots (
    id         serial PRIMARY KEY,
    service_id int NOT NULL REFERENCES services (id),
    starts_at  timestamptz NOT NULL,
    is_booked  boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS appointments (
    id               serial PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    service_id       int NOT NULL REFERENCES services (id),
    slot_id          int NOT NULL UNIQUE REFERENCES slots (id),
    customer_name    text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    status           text NOT NULL DEFAULT 'confirmed'
);

CREATE TABLE IF NOT EXISTS conversation_state (
    telegram_user_id bigint PRIMARY KEY,
    state            text NOT NULL,
    context          jsonb NOT NULL DEFAULT '{}',
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Speeds up the most common query: available future slots for a service.
CREATE INDEX IF NOT EXISTS idx_slots_service_available
    ON slots (service_id, starts_at)
    WHERE is_booked = false;
