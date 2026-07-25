# Route-level tests for the protected cron endpoint in wsgi.py.
# Fake env vars are set before the app import; the assertions below only
# exercise the secret checks, which never touch the database or Telegram.

import os

for name, value in [
    ("APPOINTMENT_BOT_TOKEN", "123456:TEST-A"),
    ("WEIGHT_BOT_TOKEN", "123456:TEST-W"),
    ("DATABASE_URL", "postgresql://unit-test/none"),
    ("APPOINTMENT_WEBHOOK_SECRET", "appt-secret"),
    ("WEIGHT_WEBHOOK_SECRET", "weight-secret"),
    ("CRON_SECRET", "cron-secret"),
]:
    os.environ.setdefault(name, value)

import pytest  # noqa: E402

from wsgi import app  # noqa: E402


@pytest.fixture
def client():
    return app.test_client()


def test_checkin_route_rejects_wrong_secret(client):
    response = client.post("/tasks/weekly-checkin/wrong-secret")
    assert response.status_code == 403


def test_checkin_route_rejects_get(client):
    response = client.get("/tasks/weekly-checkin/cron-secret")
    assert response.status_code == 405


def test_weight_webhook_rejects_wrong_secret(client):
    response = client.post("/webhook-weight/wrong-secret", json={"update_id": 1})
    assert response.status_code == 403
