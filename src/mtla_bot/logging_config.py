"""Logging configuration that keeps application secrets out of log output."""

from __future__ import annotations

import logging
from collections.abc import Iterable


DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
REDACTED_VALUE = "[REDACTED]"


def _normalize_secrets(secrets: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(secret for secret in secrets if secret))


class SecretRedactingFormatter(logging.Formatter):
    """Wrap another formatter and redact secrets from its complete output."""

    def __init__(
        self,
        formatter: logging.Formatter,
        secrets: Iterable[str | None],
    ) -> None:
        super().__init__()
        self._formatter = formatter
        self._secrets = _normalize_secrets(secrets)

    def add_secrets(self, secrets: Iterable[str | None]) -> None:
        self._secrets = _normalize_secrets((*self._secrets, *secrets))

    def format(self, record: logging.LogRecord) -> str:
        output = self._formatter.format(record)
        for secret in self._secrets:
            output = output.replace(secret, REDACTED_VALUE)
        return output


def configure_logging(secrets: Iterable[str | None] = ()) -> None:
    """Configure application logging and redact secrets at handler output."""

    logging.basicConfig(format=DEFAULT_LOG_FORMAT, level=logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for handler in root_logger.handlers:
        if isinstance(handler.formatter, SecretRedactingFormatter):
            handler.formatter.add_secrets(secrets)
            continue

        formatter = handler.formatter or logging.Formatter(DEFAULT_LOG_FORMAT)
        handler.setFormatter(SecretRedactingFormatter(formatter, secrets))

    # HTTPX logs full request URLs at INFO. Telegram embeds the bot token in
    # the URL path, so keep routine HTTP client traffic out of application logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
