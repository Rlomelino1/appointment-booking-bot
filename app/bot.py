# bot.py: creates the single shared telebot (pyTelegramBotAPI) instance.
# Import `bot` from here everywhere else; never instantiate TeleBot twice.

import telebot

from app.config import BOT_TOKEN

bot = telebot.TeleBot(BOT_TOKEN)
