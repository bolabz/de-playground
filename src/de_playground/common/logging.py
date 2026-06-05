"""Structured logging factory.

Replaces ad-hoc `print()` across the pipeline with `logging` + a per-run correlation id, so
extract/transform/index lines from the same run can be grouped after the fact (OTel logs in
Kibana, JSON logs piped to a collector, etc.).

Output format auto-detects: **pretty** single-line text when stderr is a TTY (human-friendly
for `make extract`), **JSON** when piped or non-interactive (machine-friendly for the OTel
collector and Airflow task logs). Override with `DE_LOG_FORMAT=json|pretty`; set the level via
`DE_LOG_LEVEL=INFO|DEBUG|...`.

Usage:
    from de_playground.common.logging import get_logger, set_correlation_id

    log = get_logger(__name__)

    def run() -> None:
        set_correlation_id()  # one id for the whole run; logs across modules share it
        log.info("extract complete", extra={"rows": 73_595, "table": "sales_orders"})
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

_correlation_id: ContextVar[str] = ContextVar("de_correlation_id", default="")

# LogRecord built-in attribute names — anything in record.__dict__ NOT in this set is treated
# as a structured `extra` field and emitted as its own JSON/pretty key.
_LOGRECORD_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def set_correlation_id(cid: str | None = None) -> str:
    """Set (or generate) the run-scoped correlation id. Returns the id."""
    cid = cid or uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid


def _current_correlation_id() -> str:
    cid = _correlation_id.get()
    if not cid:
        cid = set_correlation_id()
    return cid


def _structured_extras(record: logging.LogRecord) -> dict[str, object]:
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _LOGRECORD_RESERVED and not k.startswith("_")
    }


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": _current_correlation_id(),
            **_structured_extras(record),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _PrettyFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        cid = _current_correlation_id()
        head = f"{ts} {record.levelname:5s} [{cid}] {record.name}: {record.getMessage()}"
        extras = _structured_extras(record)
        if extras:
            tail = " ".join(f"{k}={v!r}" for k, v in extras.items())
            head = f"{head}  {tail}"
        if record.exc_info:
            head += "\n" + self.formatException(record.exc_info)
        return head


def _resolve_format() -> str:
    explicit = os.environ.get("DE_LOG_FORMAT", "").strip().lower()
    if explicit in {"json", "pretty"}:
        return explicit
    return "pretty" if sys.stderr.isatty() else "json"


_CONFIGURED = False


def _configure_root() -> None:
    """Idempotent root configuration. Called by get_logger; safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    fmt = _resolve_format()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonFormatter() if fmt == "json" else _PrettyFormatter())
    root = logging.getLogger("de_playground")
    root.handlers[:] = [handler]
    root.setLevel(os.environ.get("DE_LOG_LEVEL", "INFO").upper())
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the `de_playground` namespace. Pass `__name__` by convention.

    Defensive: when a module is invoked via `python -m de_playground.x`, Python sets `__name__`
    to `"__main__"` from the start, so a naive `getLogger(__name__)` would return the top-level
    `__main__` logger — outside the `de_playground.*` namespace, so the configured handler
    wouldn't apply and logs would silently disappear. We re-anchor such names here so any
    runner module's `get_logger(__name__)` reaches the configured handler.
    """
    _configure_root()
    if name == "__main__" or not (name == "de_playground" or name.startswith("de_playground.")):
        name = f"de_playground.{name}"
    return logging.getLogger(name)
