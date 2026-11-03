import pytest
import requests

from telnyx_client import (APIError, AuthenticationError, NetworkError, RateLimiter, RateLimitError,
                           TelnyxClient)
from tests.conftest import lookup_payload


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, text_body=False):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.reason = "reason"
        self._text_body = text_body

    def json(self):
        if self._text_body:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.requests.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client_with(outcomes, **kwargs):
    session = FakeSession(outcomes)
    sleeps = []
    client = TelnyxClient("KEY_TEST_1234567890abcdef", session=session, sleep=sleeps.append, **kwargs)
    return client, session, sleeps


def test_successful_lookup_sends_bearer_and_carrier_type():
    client, session, _ = client_with([FakeResponse(200, lookup_payload("+16502530000"))])
    payload = client.lookup("+16502530000")
    assert payload["data"]["phone_number"] == "+16502530000"
    req = session.requests[0]
    assert req["url"] == "https://api.telnyx.com/v2/number_lookup/%2B16502530000"
    assert req["params"] == {"type": "carrier"}
    assert req["headers"]["Authorization"] == "Bearer KEY_TEST_1234567890abcdef"


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_not_retried(status):
    body = {"errors": [{"code": "10009", "title": "Authentication failed", "detail": "bad key"}]}
    client, session, sleeps = client_with([FakeResponse(status, body)])
    with pytest.raises(AuthenticationError, match="bad key"):
        client.lookup("+16502530000")
    assert len(session.requests) == 1 and not sleeps


def test_rate_limit_retries_with_retry_after():
    client, session, sleeps = client_with(
        [FakeResponse(429, {}, {"Retry-After": "2"}), FakeResponse(200, lookup_payload("+16502530000"))])
    assert client.lookup("+16502530000")["data"]
    assert sleeps == [2.0] and len(session.requests) == 2


def test_rate_limit_exhausted_raises():
    client, _, sleeps = client_with([FakeResponse(429, {})] * 3, max_retries=2, backoff=0.5)
    with pytest.raises(RateLimitError):
        client.lookup("+16502530000")
    assert sleeps == [0.5, 1.0]


def test_rate_limit_pauses_shared_limiter():
    limiter = RateLimiter(100, clock=lambda: 0.0, sleep=lambda s: None)
    client, _, _ = client_with([FakeResponse(429, {}, {"Retry-After": "5"}),
                                FakeResponse(200, lookup_payload("+16502530000"))], rate_limiter=limiter)
    client.lookup("+16502530000")
    assert limiter._next >= 5.0


def test_server_errors_retried_then_succeed():
    client, session, sleeps = client_with([FakeResponse(503, {}), FakeResponse(500, {}),
                                           FakeResponse(200, lookup_payload("+16502530000"))])
    client.lookup("+16502530000")
    assert len(session.requests) == 3 and sleeps == [1.0, 2.0]


@pytest.mark.parametrize("exc", [requests.ConnectionError("down"), requests.Timeout("slow")])
def test_network_failures_retry_then_raise(exc):
    client, session, sleeps = client_with([exc, exc, exc], max_retries=2)
    with pytest.raises(NetworkError):
        client.lookup("+16502530000")
    assert len(session.requests) == 3 and len(sleeps) == 2


def test_network_failure_recovers():
    client, _, _ = client_with([requests.ConnectionError("down"),
                                FakeResponse(200, lookup_payload("+16502530000"))])
    assert client.lookup("+16502530000")["data"]["phone_number"] == "+16502530000"


@pytest.mark.parametrize("response", [FakeResponse(200, text_body=True), FakeResponse(200, ["list"])])
def test_invalid_json_raises_api_error(response):
    client, _, _ = client_with([response])
    with pytest.raises(APIError):
        client.lookup("+16502530000")


def test_client_error_not_retried():
    body = {"errors": [{"title": "Invalid phone number"}]}
    client, session, _ = client_with([FakeResponse(422, body)])
    with pytest.raises(APIError, match="Invalid phone number") as info:
        client.lookup("+16502530000")
    assert info.value.status_code == 422 and len(session.requests) == 1


def test_missing_key_rejected():
    with pytest.raises(AuthenticationError):
        TelnyxClient("")


def test_check_connection_uses_balance_endpoint():
    client, session, _ = client_with([FakeResponse(200, {"data": {"balance": "10.00"}})])
    assert client.check_connection()["data"]["balance"] == "10.00"
    assert session.requests[0]["url"].endswith("/v2/balance")


def test_rate_limiter_spaces_requests():
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(round(seconds, 3))

    limiter = RateLimiter(4, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        limiter.wait()
    assert slept == [0.25, 0.5]
