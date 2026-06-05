"""DB-free unit tests for lake + retry helpers."""

from __future__ import annotations

from botocore.exceptions import EndpointConnectionError

from de_playground.common.lake import s3a
from de_playground.common.retry import retry_until


def test_s3a_builds_uri():
    assert s3a("silver", "wwi", "sales_orders") == "s3a://silver/wwi/sales_orders"
    assert s3a("bronze") == "s3a://bronze"


def test_retry_until_returns_after_transient_errors():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise EndpointConnectionError(endpoint_url="http://seaweedfs:8333")
        return {"Buckets": []}

    result = retry_until(flaky, exceptions=(EndpointConnectionError,), attempts=5, delay=0)
    assert result == {"Buckets": []}
    assert calls["n"] == 3


def test_retry_until_honours_predicate():
    seq = iter([False, False, True])
    result = retry_until(lambda: next(seq), predicate=bool, attempts=5, delay=0)
    assert result is True


def test_retry_until_reraises_last_error():
    def always_fails():
        raise EndpointConnectionError(endpoint_url="http://seaweedfs:8333")

    try:
        retry_until(always_fails, exceptions=(EndpointConnectionError,), attempts=3, delay=0)
        raise AssertionError("expected EndpointConnectionError")
    except EndpointConnectionError:
        pass
