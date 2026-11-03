import threading
import time
from urllib.parse import quote

import requests

from config import APP_NAME, APP_VERSION, TELNYX_BASE_URL


class TelnyxError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(TelnyxError):
    pass


class RateLimitError(TelnyxError):
    pass


class NetworkError(TelnyxError):
    pass


class APIError(TelnyxError):
    pass


class RateLimiter:
    def __init__(self, requests_per_second: float, clock=time.monotonic, sleep=time.sleep):
        self.interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            slot = max(now, self._next)
            self._next = slot + self.interval
        if slot > now:
            self._sleep(slot - now)

    def pause(self, seconds: float) -> None:
        with self._lock:
            self._next = max(self._next, self._clock() + seconds)


class TelnyxClient:
    RETRY_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, timeout: float = 15, max_retries: int = 3,
                 backoff: float = 1.0, rate_limiter: RateLimiter | None = None,
                 session: requests.Session | None = None, sleep=time.sleep,
                 base_url: str = TELNYX_BASE_URL):
        if not api_key:
            raise AuthenticationError("Telnyx API key is not configured")
        self._api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.rate_limiter = rate_limiter
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._local = threading.local()
        self._sleep = sleep

    def lookup(self, e164: str) -> dict:
        url = f"{self.base_url}/number_lookup/{quote(e164, safe='')}"
        return self._request(url, params={"type": "carrier"})

    def check_connection(self) -> dict:
        return self._request(f"{self.base_url}/balance")

    def _session_for_thread(self) -> requests.Session:
        if self._session is not None:
            return self._session
        if not hasattr(self._local, "session"):
            session = requests.Session()
            session.headers.update(self._headers())
            self._local.session = session
        return self._local.session

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        }

    def _request(self, url: str, params: dict | None = None) -> dict:
        attempt = 0
        while True:
            if self.rate_limiter:
                self.rate_limiter.wait()
            try:
                response = self._session_for_thread().get(
                    url, params=params, headers=self._headers(), timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.max_retries:
                    raise NetworkError(f"Network error: {exc.__class__.__name__}") from exc
                self._sleep(self._delay(attempt))
                attempt += 1
                continue
            except requests.RequestException as exc:
                raise NetworkError(f"Request failed: {exc.__class__.__name__}") from exc

            status = response.status_code
            if status in self.RETRY_STATUSES and attempt < self.max_retries:
                delay = self._retry_after(response) if status == 429 else None
                delay = delay if delay is not None else self._delay(attempt)
                if status == 429 and self.rate_limiter:
                    self.rate_limiter.pause(delay)
                self._sleep(delay)
                attempt += 1
                continue
            return self._handle(response)

    def _delay(self, attempt: int) -> float:
        return min(self.backoff * (2 ** attempt), 60.0)

    @staticmethod
    def _retry_after(response) -> float | None:
        value = response.headers.get("Retry-After") if response.headers else None
        try:
            return min(max(float(value), 0.0), 120.0) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _handle(response) -> dict:
        status = response.status_code
        if status >= 400:
            detail = _error_detail(response)
            if status in (401, 403):
                raise AuthenticationError(f"Authentication failed ({status}): {detail}", status)
            if status == 429:
                raise RateLimitError(f"Rate limit exceeded (429): {detail}", status)
            raise APIError(f"Telnyx API error ({status}): {detail}", status)
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError("Telnyx returned a non-JSON response", status) from exc
        if not isinstance(payload, dict):
            raise APIError("Telnyx returned an unexpected response shape", status)
        return payload


def _error_detail(response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.reason or "no details"
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        first = errors[0]
        return str(first.get("detail") or first.get("title") or first.get("code") or "no details")
    return getattr(response, "reason", None) or "no details"
