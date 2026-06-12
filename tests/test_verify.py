"""Pure-function tests for the source-vs-Bronze verify report (WS5).

`_build_report` is fully pure (no DB, no S3) — it computes OK/APPEND/DIFF status from two
dict-of-int inputs.
"""

from __future__ import annotations

from unittest.mock import patch

from de_playground.extract.tables import WWI_TABLES
from de_playground.extract.verify import _build_report


def test_build_report_no_source_returns_bronze_only():
    bronze = {spec.resource_name: 10 for spec in WWI_TABLES}
    report = _build_report(bronze, source=None)
    tables = report["tables"]
    assert all("source" not in row for row in tables)
    assert all(row["bronze"] == 10 for row in tables)


def test_build_report_status_ok_when_counts_match():
    bronze = {spec.resource_name: 50 for spec in WWI_TABLES}
    source = {spec.resource_name: 50 for spec in WWI_TABLES}
    report = _build_report(bronze, source=source)
    assert all(row["status"] == "OK" for row in report["tables"])


def test_build_report_status_append_when_bronze_greater():
    bronze = {spec.resource_name: 60 for spec in WWI_TABLES}
    source = {spec.resource_name: 50 for spec in WWI_TABLES}
    report = _build_report(bronze, source=source)
    assert all(row["status"] == "APPEND" for row in report["tables"])


def test_build_report_status_diff_when_bronze_less_than_source():
    bronze = {spec.resource_name: 30 for spec in WWI_TABLES}
    source = {spec.resource_name: 50 for spec in WWI_TABLES}
    report = _build_report(bronze, source=source)
    assert all(row["status"] == "DIFF" for row in report["tables"])


def test_build_report_uses_settings_bucket_name():
    """The report carries the bronze bucket name so consumers can disambiguate envs.

    The verify module now calls `get_settings()` at-use; swap it via the factory rather
    than a module-level alias — exactly the testability win the WS4 6b refactor was for.
    """
    from de_playground.config import get_settings

    fake = type("S", (), {"bronze_bucket": "bronze-test-env"})()
    with patch("de_playground.extract.verify.get_settings", return_value=fake):
        report = _build_report({}, None)
    assert report["bronze_bucket"] == "bronze-test-env"
    # The real cached instance is unaffected — verify get_settings() didn't get swapped
    # in the lru_cache itself.
    get_settings.cache_clear()  # ensure no test bleed-through
