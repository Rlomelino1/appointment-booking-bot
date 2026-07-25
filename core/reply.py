# reply.py: the bot-agnostic reply shape every dialogue module returns.
# Pure data — no telebot imports — so dialogue modules stay importable
# without any Telegram dependency.

from dataclasses import dataclass


@dataclass
class Reply:
    text: str
    keyboard: list[list[str]] | None = None
