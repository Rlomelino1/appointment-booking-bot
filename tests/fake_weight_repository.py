# fake_weight_repository.py: in-memory stand-in for bots/weight/repository.py.
# Same function surface, so it can be injected into the weight bot's dialogue.
# An internal clock advances one day per weigh-in so entries get distinct,
# ordered logged_at values without real time.

from copy import deepcopy
from datetime import datetime, timedelta, timezone


class FakeWeightRepository:
    def __init__(self):
        self.states = {}       # user_id -> {"state": str, "context": dict}
        self.subscribers = {}  # user_id -> subscriber row
        self.weigh_ins = []    # rows shaped like the weigh_ins table
        self._next_id = 1
        self._clock = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    def _tick(self):
        self._clock += timedelta(days=1)
        return self._clock

    # --- conversation state --------------------------------------------------

    def get_state(self, telegram_user_id):
        row = self.states.get(telegram_user_id)
        return deepcopy(row) if row else None

    def set_state(self, telegram_user_id, state, context=None):
        self.states[telegram_user_id] = {
            "state": state,
            "context": deepcopy(context or {}),
        }

    def clear_state(self, telegram_user_id):
        self.states.pop(telegram_user_id, None)

    # --- subscribers -----------------------------------------------------------

    def get_subscriber(self, telegram_user_id):
        row = self.subscribers.get(telegram_user_id)
        return deepcopy(row) if row else None

    def set_subscriber(self, telegram_user_id, active):
        row = self.subscribers.get(telegram_user_id)
        if row:
            row["active"] = active  # subscribed_at kept, like the real upsert
        else:
            self.subscribers[telegram_user_id] = {
                "telegram_user_id": telegram_user_id,
                "subscribed_at": self._tick(),
                "active": active,
            }

    def list_active_subscribers(self):
        return [uid for uid, row in sorted(self.subscribers.items())
                if row["active"]]

    # --- weigh-ins ---------------------------------------------------------------

    def add_weigh_in(self, telegram_user_id, weight_kg):
        row = {
            "id": self._next_id,
            "telegram_user_id": telegram_user_id,
            "weight_kg": weight_kg,
            "logged_at": self._tick(),
        }
        self._next_id += 1
        self.weigh_ins.append(row)
        return deepcopy(row)

    def last_weigh_in(self, telegram_user_id):
        rows = self.recent_weigh_ins(telegram_user_id, limit=1)
        return rows[0] if rows else None

    def recent_weigh_ins(self, telegram_user_id, limit=8):
        rows = sorted(
            (r for r in self.weigh_ins
             if r["telegram_user_id"] == telegram_user_id),
            key=lambda r: (r["logged_at"], r["id"]),
            reverse=True,
        )
        return deepcopy(rows[:limit])
