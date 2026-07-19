"""Tests for the logging setup and the Telegram handler.

Nothing here talks to Telegram. The background sender thread is replaced, so we
can look at what *would* have been sent.
"""

import logging
from unittest import mock

import pytest

from media_source import logging_setup
from media_source.logging_setup import TelegramHandler, setup_logging


def _record(
    level: int = logging.ERROR,
    name: str = "media_source.api.routes",
    message: str = "boom",
) -> logging.LogRecord:
    return logging.LogRecord(name, level, "file.py", 1, message, args=(), exc_info=None)


def _handler() -> TelegramHandler:
    """A handler whose background sender never starts, so the queue stays put."""
    with mock.patch.object(logging_setup.threading, "Thread"):
        handler = TelegramHandler("token", "chat")
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


@pytest.fixture(autouse=True)
def restore_root_logging():
    """setup_logging() replaces the root handlers; put pytest's back afterwards."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers = handlers
    root.setLevel(level)


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        "LOG_LEVEL",
        "TELEGRAM_LOG_LEVEL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(name, raising=False)


# --- reading levels from the environment ------------------------------------


def test_reads_a_level_by_name(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    assert logging_setup._level("LOG_LEVEL", logging.INFO) == logging.WARNING


def test_missing_value_falls_back(clean_env):
    assert logging_setup._level("LOG_LEVEL", logging.INFO) == logging.INFO


def test_typo_falls_back_instead_of_silencing_everything(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNINGG")
    assert logging_setup._level("LOG_LEVEL", logging.INFO) == logging.INFO


# --- the Telegram handler ---------------------------------------------------


def test_queues_a_message():
    handler = _handler()
    handler.emit(_record(message="yt-dlp died"))
    assert "yt-dlp died" in handler._outbox.get_nowait()


def test_message_says_the_level_and_where_it_came_from():
    handler = _handler()
    handler.emit(_record())
    text = handler._outbox.get_nowait()
    assert "ERROR" in text
    assert "media_source.api.routes" in text


def test_http_library_lines_are_never_forwarded():
    # Sending to Telegram uses httpx, which logs, which would send again...
    handler = _handler()
    handler.emit(_record(name="httpx"))
    handler.emit(_record(name="httpcore.connection"))
    handler.emit(_record(name=logging_setup.__name__))
    assert handler._outbox.empty()


def test_a_huge_message_is_truncated():
    handler = _handler()
    handler.emit(_record(message="x" * 99_999))
    assert len(handler._outbox.get_nowait()) < logging_setup._MAX_MESSAGE_CHARS + 100


def test_a_flood_is_dropped_rather_than_piling_up():
    handler = _handler()
    for _ in range(logging_setup._QUEUE_LIMIT + 50):
        handler.emit(_record())  # must not raise
    assert handler._outbox.qsize() == logging_setup._QUEUE_LIMIT


def test_telegram_being_down_is_not_our_problem():
    handler = _handler()
    client = mock.Mock()
    client.post.side_effect = OSError("no network")
    handler._send_one(client, "hello")  # must not raise


def test_a_logged_error_reaches_the_telegram_api():
    """The real background thread, with Telegram itself replaced by a mock."""
    client = mock.MagicMock()
    client.__enter__.return_value = client
    with (
        mock.patch.object(logging_setup.httpx, "Client", return_value=client),
        mock.patch.object(logging_setup, "_SECONDS_BETWEEN_SENDS", 0),
    ):
        handler = TelegramHandler("secret-token", "12345")
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_record(message="cookies expired"))
        handler.close()  # waits for the thread to drain

    (url,) = client.post.call_args.args
    payload = client.post.call_args.kwargs["json"]
    assert url == "https://api.telegram.org/botsecret-token/sendMessage"
    assert payload["chat_id"] == "12345"
    assert "cookies expired" in payload["text"]


# --- setup ------------------------------------------------------------------


def test_no_telegram_handler_without_a_token(clean_env):
    setup_logging()
    assert [type(h) for h in logging.getLogger().handlers] == [logging.StreamHandler]


def test_telegram_handler_is_added_when_configured(clean_env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("TELEGRAM_LOG_LEVEL", "WARNING")
    with mock.patch.object(logging_setup.threading, "Thread"):
        setup_logging()

    telegram = [
        h for h in logging.getLogger().handlers if isinstance(h, TelegramHandler)
    ]
    assert len(telegram) == 1
    assert telegram[0].level == logging.WARNING


def test_both_token_and_chat_id_are_required(clean_env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")  # chat id missing
    setup_logging()
    assert not any(
        isinstance(h, TelegramHandler) for h in logging.getLogger().handlers
    )


def test_calling_twice_does_not_double_the_handlers(clean_env):
    setup_logging()
    setup_logging()
    assert len(logging.getLogger().handlers) == 1


def test_root_is_verbose_enough_for_the_quieter_handler(clean_env, monkeypatch):
    # Console at WARNING must not swallow the DEBUG lines Telegram asked for.
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("TELEGRAM_LOG_LEVEL", "DEBUG")
    with mock.patch.object(logging_setup.threading, "Thread"):
        setup_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_httpx_is_kept_quiet_so_the_lastfm_key_stays_out_of_logs(clean_env, monkeypatch):
    # httpx logs whole request URLs at INFO, and our Last.fm calls carry the
    # api_key in the query string.
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    setup_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
