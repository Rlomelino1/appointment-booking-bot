# Appointment Booking Bot

A Telegram bot for booking appointments, built with pyTelegramBotAPI and backed by PostgreSQL. Users interact with the bot through a guided conversation to pick a service, choose an available date and time, and confirm their booking. It runs in long-polling mode for local development (`run_polling.py`) and as a Flask webhook app served by gunicorn in production (`wsgi.py`).

## Setup

```powershell
# Create and activate a virtual environment (Windows PowerShell)
python -m venv venv
venv\Scripts\Activate.ps1

# macOS / Linux
# python3 -m venv venv
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
copy .env.example .env   # then edit .env and fill in BOT_TOKEN and DATABASE_URL
```

The `venv/` directory is git-ignored — do not commit it.
