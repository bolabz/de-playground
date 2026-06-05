"""One small retry helper, so every "wait for a service to come up" reads the same way.

Used by the S3 (SeaweedFS) and Elasticsearch readiness checks. Containers take a few seconds
to start listening; rather than four ad-hoc loops, callers express "retry this call until it
works (or returns something truthy)".
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry_until(
    fn: Callable[[], T],
    *,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    predicate: Callable[[T], bool] | None = None,
    attempts: int = 30,
    delay: float = 2.0,
) -> T:
    """Call `fn` until it returns (and `predicate`, if given, holds). Retries on `exceptions`.

    Raises the last exception, or TimeoutError if it kept returning a falsy/rejected value.
    """
    last_err: BaseException | None = None
    for _ in range(attempts):
        try:
            result = fn()
            if predicate is None or predicate(result):
                return result
        except exceptions as err:
            last_err = err
        time.sleep(delay)
    if last_err is not None:
        raise last_err
    raise TimeoutError(f"condition not met after {attempts} attempts")
