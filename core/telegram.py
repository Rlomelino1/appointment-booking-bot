# telegram.py: shared telebot glue helpers used by every bot's handlers.

from telebot.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove


def to_markup(keyboard):
    """Convert Reply.keyboard rows into a telebot markup.

    None means "remove any previous reply keyboard", not "leave it".
    """
    if keyboard is None:
        return ReplyKeyboardRemove()
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for row in keyboard:
        markup.row(*row)
    return markup


def display_name(message: Message) -> str:
    parts = [message.from_user.first_name, message.from_user.last_name]
    return " ".join(p for p in parts if p) or "Guest"
