# dialogue.py: the weight bot's conversation logic.
# Pure, like the appointment bot's: receives (user_id, text, repo), returns a
# Reply; no telebot imports, no SQL. Only two states exist — idle (default,
# no row) and awaiting_weight — kept in the weight bot's own state table so a
# user chatting with both bots never has one bot clobber the other's state.

import logging
import re

from core.reply import Reply

logger = logging.getLogger(__name__)

MIN_KG = 20
MAX_KG = 400

EXPLAIN = (
    "Hi! I'm your weight check-in bot. Every Saturday I'll message you to ask "
    "your weight — reply with a number like 84,2 and I'll track it.\n"
    "Commands:\n"
    "• /log — record a weigh-in anytime\n"
    "• /history — your recent entries\n"
    "• /stop — pause the check-ins"
)
ASK_WEIGHT = "What's your weight today, in kg? (e.g. 84,2)"

# number with an optional comma or dot decimal part, optional "kg" suffix
_WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:kg)?", re.IGNORECASE)


def handle_message(user_id, text, repo):
    """Route one incoming message, return a Reply."""
    state_before = _current_state(repo, user_id)
    reply = _dispatch(user_id, text, repo)
    state_after = _current_state(repo, user_id)
    logger.info("user %s: state %s -> %s", user_id, state_before, state_after)
    return reply


def _current_state(repo, user_id):
    row = repo.get_state(user_id)
    return row["state"] if row else "idle"


def _dispatch(user_id, text, repo):
    text = (text or "").strip()
    lowered = text.lower()

    if lowered == "/start":
        return _subscribe(user_id, repo)
    if lowered == "/stop":
        return _pause(user_id, repo)
    if lowered == "/log":
        repo.set_state(user_id, "awaiting_weight", {})
        return Reply(ASK_WEIGHT)
    if lowered == "/history":
        return _history(user_id, repo)

    if _current_state(repo, user_id) == "awaiting_weight":
        return _handle_weight_reply(user_id, text, repo)

    return Reply(
        "Send /log to record a weigh-in, /history for your recent entries, "
        "or /stop to pause the weekly check-ins."
    )


# --- subscription ---------------------------------------------------------------

def _subscribe(user_id, repo):
    repo.clear_state(user_id)
    existing = repo.get_subscriber(user_id)
    repo.set_subscriber(user_id, active=True)
    if existing and not existing["active"]:
        return Reply("Welcome back! You'll get your Saturday check-ins again.")
    return Reply(EXPLAIN)


def _pause(user_id, repo):
    repo.clear_state(user_id)
    repo.set_subscriber(user_id, active=False)
    return Reply(
        "Check-ins paused. Your history is kept — send /start anytime to resume."
    )


# --- weigh-ins ------------------------------------------------------------------

def _handle_weight_reply(user_id, text, repo):
    weight = _parse_weight(text)
    if weight is None:
        return Reply("I just need a number in kg, like 84,2 — try again.")
    if not MIN_KG <= weight <= MAX_KG:
        return Reply(
            f"That doesn't look like a weight in kg — I can log values "
            f"between {MIN_KG} and {MAX_KG}. Try again."
        )

    previous = repo.last_weigh_in(user_id)  # before storing the new one
    repo.add_weigh_in(user_id, weight)
    repo.clear_state(user_id)

    if previous is None:
        return Reply("Weight logged. See you next week.")
    diff = round(weight - round(float(previous["weight_kg"]), 1), 1)
    if diff < 0:
        return Reply(f"You're down {_fmt(-diff)} kg — good job, keep it up.")
    if diff > 0:
        return Reply(f"Up {_fmt(diff)} kg — lock in.")
    return Reply("Same as last week — steady.")


def _parse_weight(text):
    """Parse kg accepting comma or dot decimals; None if not a number."""
    match = _WEIGHT_RE.fullmatch(text.strip())
    if not match:
        return None
    return round(float(match.group(1).replace(",", ".")), 1)


def _history(user_id, repo):
    rows = repo.recent_weigh_ins(user_id, limit=8)
    if not rows:
        return Reply("No weigh-ins yet — send /log to record your first.")
    lines = [
        f"{r['logged_at'].day} {r['logged_at']:%b %Y} — "
        f"{_fmt(float(r['weight_kg']))} kg"
        for r in rows
    ]
    return Reply("Your last weigh-ins:\n" + "\n".join(lines))


# --- weekly check-in (driven by the cron route, not by a user message) ----------

def weekly_checkin(repo):
    """Build the Saturday prompt for every ACTIVE subscriber.

    Returns [(user_id, Reply), ...] and puts each recipient into
    awaiting_weight, so their next plain-number message is logged.
    """
    return [(uid, checkin_prompt(uid, repo))
            for uid in repo.list_active_subscribers()]


def checkin_prompt(user_id, repo):
    repo.set_state(user_id, "awaiting_weight", {})
    text = "Good morning! Weekly check-in — what's your weight today?"
    last = repo.last_weigh_in(user_id)
    if last is not None:
        text += f"\nLast week: {_fmt(float(last['weight_kg']))} kg"
    return Reply(text)


# --- helpers --------------------------------------------------------------------

def _fmt(value):
    """One decimal, comma as the decimal separator: 84.2 -> '84,2'."""
    return f"{value:.1f}".replace(".", ",")
