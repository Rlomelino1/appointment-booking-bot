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

-- Per-user preferences; a row exists only once the user has set something.
CREATE TABLE IF NOT EXISTS user_settings (
    telegram_user_id bigint PRIMARY KEY,
    timezone         text NOT NULL
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

-- Weight bot -----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS weight_subscribers (
    telegram_user_id bigint PRIMARY KEY,
    subscribed_at    timestamptz NOT NULL DEFAULT now(),
    active           boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS weigh_ins (
    id               serial PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    weight_kg        numeric(5,1) NOT NULL,
    logged_at        timestamptz NOT NULL DEFAULT now()
);

-- Speeds up "most recent weigh-ins for a user", the bot's hottest query.
CREATE INDEX IF NOT EXISTS idx_weigh_ins_user_time
    ON weigh_ins (telegram_user_id, logged_at DESC);

-- Same shape as conversation_state, but per bot: a user chatting with both
-- bots must not have one bot's state clobber the other's.
CREATE TABLE IF NOT EXISTS weight_conversation_state (
    telegram_user_id bigint PRIMARY KEY,
    state            text NOT NULL,
    context          jsonb NOT NULL DEFAULT '{}',
    updated_at       timestamptz NOT NULL DEFAULT now()
);
