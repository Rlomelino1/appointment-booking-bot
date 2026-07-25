# set_webhook.py: registers (or removes) the bot's Telegram webhook.
# Run from the project root:
#   python scripts/set_webhook.py            -> point Telegram at PUBLIC_URL/webhook/<secret>
#   python scripts/set_webhook.py --delete   -> remove the webhook (back to polling)
# Telegram allows either a webhook OR getUpdates polling, never both — run
# --delete before starting run_polling.py locally.

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))  # allow `from app...` when run as a script

from app.bot import bot
from app.config import PUBLIC_URL, WEBHOOK_SECRET


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="remove the webhook so the bot can be run with polling again",
    )
    args = parser.parse_args()

    if args.delete:
        bot.delete_webhook()
        print("Webhook removed — the bot can now be run with run_polling.py.")
        return

    missing = [
        name for name, value in
        [("PUBLIC_URL", PUBLIC_URL), ("WEBHOOK_SECRET", WEBHOOK_SECRET)]
        if not value
    ]
    if missing:
        sys.exit(f"Missing required environment variable(s): {', '.join(missing)}")

    url = f"{PUBLIC_URL.rstrip('/')}/webhook/{WEBHOOK_SECRET}"
    bot.set_webhook(url=url)
    info = bot.get_webhook_info()
    masked = url.replace(WEBHOOK_SECRET, WEBHOOK_SECRET[:4] + "…")
    print(f"Webhook set to {masked}")
    print(f"Pending updates on Telegram's side: {info.pending_update_count}")


if __name__ == "__main__":
    main()
