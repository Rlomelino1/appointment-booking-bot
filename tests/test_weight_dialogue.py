# Unit tests for the weight bot's dialogue (bots/weight/dialogue.py),
# using tests/fake_weight_repository.py — no database, no Telegram.

import pytest

from bots.weight.dialogue import checkin_prompt, handle_message, weekly_checkin
from tests.fake_weight_repository import FakeWeightRepository

USER = 111
OTHER = 222


@pytest.fixture
def repo():
    return FakeWeightRepository()


def send(repo, text, user_id=USER):
    return handle_message(user_id, text, repo)


def state_of(repo, user_id=USER):
    row = repo.get_state(user_id)
    return row["state"] if row else "idle"


def log(repo, value, user_id=USER):
    send(repo, "/log", user_id)
    return send(repo, value, user_id)


# --- decimal parsing --------------------------------------------------------

@pytest.mark.parametrize("text,stored", [
    ("84,2", 84.2),   # comma decimal
    ("84.2", 84.2),   # dot decimal
    ("90", 90.0),     # integer
    ("84,2 kg", 84.2),  # unit suffix tolerated
])
def test_parses_comma_and_dot_decimals(repo, text, stored):
    reply = log(repo, text)
    assert repo.weigh_ins[-1]["weight_kg"] == stored
    assert reply.text == "Weight logged. See you next week."
    assert state_of(repo) == "idle"


@pytest.mark.parametrize("garbage", ["abc", "84,2,3", "", "kg", "12abc"])
def test_unparseable_input_reprompts(repo, garbage):
    send(repo, "/log")
    reply = send(repo, garbage)
    assert "84,2" in reply.text  # shows an example of what's expected
    assert repo.weigh_ins == []
    assert state_of(repo) == "awaiting_weight"  # can just try again


# --- range validation ---------------------------------------------------------

@pytest.mark.parametrize("out_of_range", ["19,9", "400.1", "1000", "0"])
def test_out_of_range_reprompts(repo, out_of_range):
    send(repo, "/log")
    reply = send(repo, out_of_range)
    assert "between 20 and 400" in reply.text
    assert repo.weigh_ins == []
    assert state_of(repo) == "awaiting_weight"


@pytest.mark.parametrize("boundary,stored", [("20", 20.0), ("400", 400.0)])
def test_boundaries_accepted(repo, boundary, stored):
    log(repo, boundary)
    assert repo.weigh_ins[-1]["weight_kg"] == stored


# --- first / down / up / equal messages ---------------------------------------

def test_first_weigh_in_message(repo):
    reply = log(repo, "84,2")
    assert reply.text == "Weight logged. See you next week."


def test_down_message_with_comma_diff(repo):
    log(repo, "85,5")
    reply = log(repo, "84,2")
    assert reply.text == "You're down 1,3 kg — good job, keep it up."


def test_up_message_with_comma_diff(repo):
    log(repo, "84,2")
    reply = log(repo, "84,7")
    assert reply.text == "Up 0,5 kg — lock in."


def test_equal_message(repo):
    log(repo, "84,2")
    reply = log(repo, "84.2")  # same value, other decimal separator
    assert reply.text == "Same as last week — steady."


# --- weekly check-in ------------------------------------------------------------

def test_checkin_prompt_mentions_last_weigh_in_and_sets_state(repo):
    log(repo, "84,2")
    reply = checkin_prompt(USER, repo)
    assert "Last week: 84,2 kg" in reply.text
    assert state_of(repo) == "awaiting_weight"


def test_checkin_prompt_without_history(repo):
    reply = checkin_prompt(USER, repo)
    assert "Last week" not in reply.text
    assert state_of(repo) == "awaiting_weight"


def test_weekly_checkin_skips_inactive_subscribers(repo):
    repo.set_subscriber(USER, active=True)
    repo.set_subscriber(OTHER, active=False)

    prompts = weekly_checkin(repo)

    assert [uid for uid, _ in prompts] == [USER]
    assert state_of(repo, USER) == "awaiting_weight"
    assert state_of(repo, OTHER) == "idle"  # untouched


def test_reply_to_checkin_logs_weight(repo):
    checkin_prompt(USER, repo)
    reply = send(repo, "84,2")  # plain number, no /log needed
    assert reply.text == "Weight logged. See you next week."
    assert repo.weigh_ins[-1]["weight_kg"] == 84.2


# --- subscription lifecycle -----------------------------------------------------

def test_start_subscribes_and_explains(repo):
    reply = send(repo, "/start")
    assert "/log" in reply.text and "/stop" in reply.text  # explains itself
    assert repo.subscribers[USER]["active"] is True


def test_stop_then_start_roundtrip_keeps_history(repo):
    send(repo, "/start")
    log(repo, "84,2")

    reply = send(repo, "/stop")
    assert "paused" in reply.text.lower()
    assert "/start" in reply.text
    assert repo.subscribers[USER]["active"] is False
    assert len(repo.weigh_ins) == 1  # history kept

    reply = send(repo, "/start")
    assert reply.text == "Welcome back! You'll get your Saturday check-ins again."
    assert repo.subscribers[USER]["active"] is True
    assert "84,2 kg" in send(repo, "/history").text  # history intact


def test_log_works_while_paused(repo):
    send(repo, "/start")
    send(repo, "/stop")
    reply = log(repo, "84,2")
    assert reply.text == "Weight logged. See you next week."
    assert repo.weigh_ins[-1]["weight_kg"] == 84.2


# --- /history --------------------------------------------------------------------

def test_history_empty(repo):
    assert "No weigh-ins yet" in send(repo, "/history").text


def test_history_caps_at_eight_newest_first(repo):
    for i in range(10):
        log(repo, str(80 + i))
    reply = send(repo, "/history")
    lines = [l for l in reply.text.splitlines() if "kg" in l]
    assert len(lines) == 8
    assert "89,0 kg" in lines[0]  # newest first
    assert "82,0 kg" in lines[-1]  # entries 80 and 81 fell off


def test_idle_fallback_points_at_commands(repo):
    reply = send(repo, "hello?")
    assert "/log" in reply.text and "/history" in reply.text
