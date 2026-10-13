"""Bounded retry with exponential backoff. Sleep and clock are injectable so tests are exact and fast.

Timeout semantics: the wrapped call is expected to enforce its own network timeout and raise
TimeoutError (or a type listed in retry_on). In addition, `per_call_timeout_s` is checked against the
injected clock after each attempt (a call that returns/raises later than that is treated as timed out),
and `total_timeout_s` bounds the whole retry loop. Exhaustion raises TransferTimeoutError carrying the
attempt count.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from robotevalops.errors import TransferTimeoutError

T = TypeVar("T")

DEFAULT_RETRY_ON: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4  # total calls, including the first
    base_delay_s: float = 0.5
    factor: float = 2.0
    max_delay_s: float = 8.0
    per_call_timeout_s: float | None = None
    total_timeout_s: float | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

    def delay_before_retry(self, failed_attempts: int) -> float:
        """Delay after the Nth failed attempt (N>=1): base * factor**(N-1), capped."""
        return min(self.max_delay_s, self.base_delay_s * self.factor ** (failed_attempts - 1))


class _CallTimedOut(TimeoutError):
    pass


def call_with_retry(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    retry_on: tuple[type[BaseException], ...] = DEFAULT_RETRY_ON,
    is_retryable: Callable[[BaseException], bool] | None = None,
    what: str = "transfer",
) -> tuple[T, int]:
    """Call fn up to policy.max_attempts times. Returns (result, attempts_used).

    Non-retryable exceptions propagate immediately. Retryable ones are retried with backoff; after the
    last attempt (or when total_timeout_s would be exceeded) TransferTimeoutError(attempts=N) is raised.
    """
    pol = policy or RetryPolicy()
    start = clock()
    last: BaseException | None = None
    attempts = 0
    while attempts < pol.max_attempts:
        attempts += 1
        t0 = clock()
        try:
            result = fn()
            if pol.per_call_timeout_s is not None and clock() - t0 > pol.per_call_timeout_s:
                raise _CallTimedOut(f"{what} exceeded per-call timeout {pol.per_call_timeout_s}s")
            return result, attempts
        except BaseException as exc:
            retryable = isinstance(exc, retry_on) or (is_retryable is not None and is_retryable(exc))
            if not retryable:
                raise
            last = exc
        if attempts >= pol.max_attempts:
            break
        delay = pol.delay_before_retry(attempts)
        if pol.total_timeout_s is not None and clock() - start + delay > pol.total_timeout_s:
            break
        sleep(delay)
    err = TransferTimeoutError(
        f"{what} failed after {attempts} attempt(s): {type(last).__name__}: {last}. Check connectivity "
        "and credentials, then re-run; completed artifacts are skipped on resume"
    )
    err.attempts = attempts  # type: ignore[attr-defined]
    raise err from last
