# set_webhook.py: registers (or removes) every bot's Telegram webhook.
# Run from the project root:
#   python scripts/set_webhook.py            -> point Telegram at each bot's webhook URL
#   python scripts/set_webhook.py --delete   -> remove all webhooks (back to polling)
# Telegram allows either a webhook OR getUpdates polling per bot, never both —
# run --delete before starting run_polling.py locally.

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))  # allow package imports when run as a script

from bots.appointment.bot import bot as appointment_bot
from bots.weight.bot import bot as weight_bot
from core.config import (
    APPOINTMENT_WEBHOOK_SECRET,
    PUBLIC_URL,
    WEIGHT_WEBHOOK_SECRET,
)

# (name, bot, secret env var name, secret, webhook path prefix)
BOTS = [
    ("appointment", appointment_bot,
     "APPOINTMENT_WEBHOOK_SECRET", APPOINTMENT_WEBHOOK_SECRET, "/webhook"),
    ("weight", weight_bot,
     "WEIGHT_WEBHOOK_SECRET", WEIGHT_WEBHOOK_SECRET, "/webhook-weight"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="remove all webhooks so the bots can be run with polling again",
    )
    args = parser.parse_args()

    if args.delete:
        for name, bot, _, _, _ in BOTS:
            bot.delete_webhook()
            print(f"{name}: webhook removed — the bot can now be polled.")
        return

    missing = [var for _, _, var, secret, _ in BOTS if not secret]
    if not PUBLIC_URL:
        missing.insert(0, "PUBLIC_URL")
    if missing:
        sys.exit(f"Missing required environment variable(s): {', '.join(missing)}")

    for name, bot, _, secret, path in BOTS:
        url = f"{PUBLIC_URL.rstrip('/')}{path}/{secret}"
        bot.set_webhook(url=url)
        info = bot.get_webhook_info()
        masked = url.replace(secret, secret[:4] + "…")
        print(f"{name}: webhook set to {masked} "
              f"(pending updates: {info.pending_update_count})")


if __name__ == "__main__":
    main()
