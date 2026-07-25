# conftest.py: pin environment the tests depend on BEFORE any test module
# (or the app code it imports) reads it.
#
# The dialogue tests assert Sao Paulo-rendered timestamps, but importing
# core.config anywhere in the suite runs load_dotenv(), which would pull a
# developer's local .env (e.g. BUSINESS_TIMEZONE=America/New_York) into the
# process. Setting the variable here wins: conftest is imported first, and
# load_dotenv never overrides variables that are already set.

import os

os.environ["BUSINESS_TIMEZONE"] = "America/Sao_Paulo"
