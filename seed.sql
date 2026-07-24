-- seed.sql: sample data for local development.
-- 3 services and 10 future slots spread over the next 7 days.
-- Idempotent: services upsert by name; slots are only inserted when the
-- slots table is empty, so re-running never duplicates data.

INSERT INTO services (name, duration_minutes) VALUES
    ('Haircut',      30),
    ('Consultation', 60),
    ('Massage',      45)
ON CONFLICT (name) DO NOTHING;

-- Slot times are relative to today, so seeded data is always in the future.
INSERT INTO slots (service_id, starts_at)
SELECT s.id, slot.starts_at
FROM (VALUES
    ('Haircut',      CURRENT_DATE + interval '1 day 10 hours'),
    ('Consultation', CURRENT_DATE + interval '1 day 15 hours'),
    ('Massage',      CURRENT_DATE + interval '2 days 11 hours'),
    ('Haircut',      CURRENT_DATE + interval '2 days 16 hours 30 minutes'),
    ('Consultation', CURRENT_DATE + interval '3 days 9 hours 30 minutes'),
    ('Haircut',      CURRENT_DATE + interval '4 days 10 hours'),
    ('Massage',      CURRENT_DATE + interval '4 days 14 hours'),
    ('Consultation', CURRENT_DATE + interval '5 days 13 hours'),
    ('Massage',      CURRENT_DATE + interval '6 days 11 hours 30 minutes'),
    ('Haircut',      CURRENT_DATE + interval '7 days 10 hours')
) AS slot (service_name, starts_at)
JOIN services s ON s.name = slot.service_name
WHERE NOT EXISTS (SELECT 1 FROM slots);
