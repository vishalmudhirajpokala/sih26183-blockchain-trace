"""
Shared HTTP client for every chain adapter.

All provider traffic goes through this module so that retry policy, throttling,
caching, deadline enforcement and provider-fallback bookkeeping are written once
and behave identically for TRON, EVM and Bitcoin.

Design notes
------------
* Throttling uses a per-provider `threading.Lock` AND a monotonic last-request
  clock. The previous implementation mutated a bare float with no lock, which
  meant two concurrent /trace calls could both read the same stale timestamp and
  fire simultaneously, defeating the spacing guarantee.

* Caching is per-TraceContext, not global. A global cache would go stale and
  would leak one investigation's data into another's results; live network
  endpoints deliberately bypass it.

* Retry covers the transient set (429, 5xx, timeouts, connection errors), not
  just 429. Backoff is bounded and jittered, and Retry-After is honoured.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import requests

from models.schemas import Availability, ProviderUsage

# ============================================================
# TUNABLES
# ============================================================

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 8.0
RETRY_AFTER_MAX_SECONDS = 10.0
MIN_REQUEST_INTERVAL_SECONDS = 0.35


class ProviderThrottle:
    """Per-provider request spacing, safe under FastAPI's threadpool."""

    def __init__(self, min_interval: float = MIN_REQUEST_INTERVAL_SECONDS) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_request = 0.0

    def acquire(self, deadline: Optional[float] = None) -> float:
        """
        Block until this provider may be called. Returns the seconds slept.

        The lock is held across the sleep. That is intentional: it converts a
        thundering herd of concurrent callers into a serialized queue that
        respects the spacing, which is the only way to guarantee the interval
        under a threadpool.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            wait_for = self._min_interval - elapsed

            if wait_for > 0:
                if deadline is not None and now + wait_for > deadline:
                    raise TimeoutError(
                        "Provider throttle would exceed the trace deadline."
                    )
                time.sleep(wait_for)
                slept = wait_for
            else:
                slept = 0.0

            self._last_request = time.monotonic()
            return slept


# Throttle registry, keyed by provider name.
_THROTTLES: Dict[str, ProviderThrottle] = {}
_THROTTLES_LOCK = threading.Lock()


def get_throttle(provider: str) -> ProviderThrottle:
    with _THROTTLES_LOCK:
        if provider not in _THROTTLES:
            _THROTTLES[provider] = ProviderThrottle()
        return _THROTTLES[provider]


# ============================================================
# CACHE
# ============================================================


@dataclass
class RequestCache:
    """
    Per-investigation request cache.

    Deliberately scoped to one trace so a repeat investigation still re-fetches
    (correct for a forensic tool that must not show stale chain state) while a
    single multi-hop traversal never asks the same provider the same question
    twice.
    """

    _store: Dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    hits: int = 0
    misses: int = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._store:
                self.hits += 1
                return self._store[key]
            self.misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = value

    def stats(self) -> Dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "size": len(self._store)}


# ============================================================
# RESULT
# ============================================================


@dataclass
class HttpResult:
    """A provider call outcome. `data` is None whenever anything went wrong."""

    ok: bool
    data: Optional[Any] = None
    status_code: Optional[int] = None
    error: Optional[str] = None
    provider: str = ""
    latency_ms: int = 0
    retries: int = 0
    from_cache: bool = False
    availability: Availability = Availability.AVAILABLE
    reason: Optional[str] = None

    def to_usage(self) -> ProviderUsage:
        return ProviderUsage(
            provider=self.provider,
            ok=self.ok,
            status_code=self.status_code,
            latency_ms=self.latency_ms,
            retries=self.retries,
            error=self.error,
            from_cache=self.from_cache,
        )


# ============================================================
# CLIENT
# ============================================================


class HttpClient:
    """
    One client instance per trace, sharing a cache and a usage log.

    Adapters construct this and use `.get_json()` / `.post_json()`. The client
    records every attempt in `self.usage` so the API can report which provider
    actually served the data.
    """

    def __init__(
        self,
        cache: Optional[RequestCache] = None,
        deadline: Optional[float] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self.cache = cache if cache is not None else RequestCache()
        self.deadline = deadline
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.usage: list[ProviderUsage] = []
        self._session = requests.Session()
        self._min_interval = min_interval
        self._throttles: Dict[str, ProviderThrottle] = {}

    # --------------------------------------------------------
    # internals
    # --------------------------------------------------------

    def _throttle_for(self, provider: str) -> ProviderThrottle:
        if provider not in self._throttles:
            # Share throttles process-wide so two concurrent investigations
            # cannot together exceed a provider's limit.
            throttle = get_throttle(provider)
            throttle._min_interval = self._min_interval
            self._throttles[provider] = throttle
        return self._throttles[provider]

    def _remaining(self) -> Optional[float]:
        if self.deadline is None:
            return None
        return self.deadline - time.monotonic()

    def _effective_timeout(self) -> float:
        remaining = self._remaining()
        if remaining is None:
            return self.timeout
        return max(0.5, min(self.timeout, remaining))

    def _check_deadline(self) -> None:
        remaining = self._remaining()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("Overall tracing deadline reached.")

    def _parse_retry_after(self, response: requests.Response) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return min(float(header), RETRY_AFTER_MAX_SECONDS)
            except (TypeError, ValueError):
                pass
        return 0.0

    def _sleep_for(self, attempt: int, retry_after: float) -> None:
        if retry_after > 0:
            wait = retry_after
        else:
            # Bounded exponential with jitter. Jitter matters: without it, every
            # client that got a 429 at the same moment retries at the same
            # moment, and the provider gets hit again just as hard.
            ceiling = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** attempt))
            wait = random.uniform(BACKOFF_BASE_SECONDS, ceiling)

        remaining = self._remaining()
        if remaining is not None and wait > remaining:
            raise TimeoutError("Backoff would exceed the trace deadline.")

        time.sleep(wait)

    # --------------------------------------------------------
    # public
    # --------------------------------------------------------

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        provider: str = "unknown",
        use_cache: bool = True,
    ) -> HttpResult:
        return self._request(
            "GET", url, params=params, headers=headers,
            provider=provider, use_cache=use_cache,
        )

    def post_json(
        self,
        url: str,
        body: Any = None,
        headers: Optional[Dict[str, str]] = None,
        provider: str = "unknown",
        use_cache: bool = True,
    ) -> HttpResult:
        """
        POST helper for RPC-style calls.

        `use_cache` defaults to True so the signature matches `get_json`; every
        adapter passes `use_cache=False` for a POST, because the cache is keyed
        by request body and a cached RPC answer is a stale chain state.
        """
        return self._request(
            "POST", url, body=body, headers=headers,
            provider=provider, use_cache=use_cache,
        )

    def _cache_key(
        self, method: str, url: str, params: Any, body: Any,
    ) -> str:
        return f"{method}|{url}|{sorted((params or {}).items()) if isinstance(params, dict) else params}|{body}"

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        body: Any = None,
        headers: Optional[Dict[str, str]] = None,
        provider: str = "unknown",
        use_cache: bool = True,
    ) -> HttpResult:
        key = self._cache_key(method, url, params, body)

        if use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                return HttpResult(
                    ok=True,
                    data=cached,
                    provider=provider,
                    from_cache=True,
                    latency_ms=0,
                )

        started = time.monotonic()
        attempts = 0
        last_error = "unknown error"
        last_status: Optional[int] = None

        while attempts < self.max_attempts:
            try:
                self._check_deadline()
            except TimeoutError as exc:
                self.usage.append(
                    ProviderUsage(provider, False, error=str(exc), latency_ms=0,
                                  retries=attempts)
                )
                return HttpResult(
                    ok=False, provider=provider, error=str(exc),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    retries=attempts, availability=Availability.UNAVAILABLE,
                    reason="deadline_exceeded",
                )

            try:
                self._throttle_for(provider).acquire(self.deadline)
                self._check_deadline()

                if method == "GET":
                    response = self._session.get(
                        url, params=params, headers=headers,
                        timeout=self._effective_timeout(),
                    )
                else:
                    response = self._session.post(
                        url, json=body, headers=headers,
                        timeout=self._effective_timeout(),
                    )

            except requests.exceptions.Timeout as exc:
                last_error = f"timeout: {exc}"
                attempts += 1
                if attempts >= self.max_attempts:
                    break
                self._sleep_for(attempts - 1, 0.0)
                continue

            except requests.exceptions.RequestException as exc:
                last_error = f"network error: {exc}"
                attempts += 1
                if attempts >= self.max_attempts:
                    break
                self._sleep_for(attempts - 1, 0.0)
                continue

            last_status = response.status_code

            if response.status_code in RETRYABLE_STATUS:
                retry_after = self._parse_retry_after(response)
                last_error = f"HTTP {response.status_code}"
                attempts += 1
                if attempts >= self.max_attempts:
                    break
                try:
                    self._sleep_for(attempts - 1, retry_after)
                except TimeoutError as exc:
                    last_error = str(exc)
                    break
                continue

            if response.status_code >= 400:
                # Non-retryable client error: this is a real answer, not a blip.
                self.usage.append(
                    ProviderUsage(
                        provider, False, response.status_code,
                        int((time.monotonic() - started) * 1000),
                        attempts, f"HTTP {response.status_code}",
                    )
                )
                return HttpResult(
                    ok=False, provider=provider,
                    status_code=response.status_code,
                    error=f"HTTP {response.status_code}",
                    latency_ms=int((time.monotonic() - started) * 1000),
                    retries=attempts, availability=Availability.UNAVAILABLE,
                    reason="client_error",
                )

            try:
                data = response.json()
            except ValueError as exc:
                self.usage.append(
                    ProviderUsage(
                        provider, False, response.status_code,
                        int((time.monotonic() - started) * 1000),
                        attempts, f"invalid json: {exc}",
                    )
                )
                return HttpResult(
                    ok=False, provider=provider,
                    status_code=response.status_code,
                    error=f"invalid json: {exc}",
                    latency_ms=int((time.monotonic() - started) * 1000),
                    retries=attempts, availability=Availability.UNAVAILABLE,
                    reason="invalid_json",
                )

            latency = int((time.monotonic() - started) * 1000)
            self.usage.append(
                ProviderUsage(provider, True, response.status_code, latency, attempts)
            )

            if use_cache:
                self.cache.set(key, data)

            return HttpResult(
                ok=True, data=data, provider=provider,
                status_code=response.status_code, latency_ms=latency,
                retries=attempts,
            )

        latency = int((time.monotonic() - started) * 1000)
        self.usage.append(
            ProviderUsage(provider, False, last_status, latency, attempts, last_error)
        )

        reason = "timeout" if "timeout" in last_error else "network_error"
        if last_status in RETRYABLE_STATUS:
            reason = "rate_limited" if last_status == 429 else "server_error"

        return HttpResult(
            ok=False, provider=provider, status_code=last_status,
            error=last_error, latency_ms=latency, retries=attempts,
            availability=Availability.UNAVAILABLE, reason=reason,
        )

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # pragma: no cover - defensive
            pass

    def usage_summary(self) -> Tuple[list, Dict[str, int]]:
        return list(self.usage), self.cache.stats()
