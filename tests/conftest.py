import os

# Tests must never reach the real Telegram chat.
#
# `media_source.main` calls load_dotenv() + setup_logging() at import time, so a
# real token in .env would turn every ERROR logged by a test into an actual
# message (and make the suite wait on the network + the 3s send throttle).
#
# load_dotenv() does not override variables that are already set, so seeding
# these as empty here — conftest is imported before any test module — keeps the
# Telegram handler switched off no matter what .env contains.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
