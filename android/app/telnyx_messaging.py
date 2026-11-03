"""Telnyx messaging / number-hosting client for the SMS hosting feature.

This is the operator-side integration that text-enables a business line the user has
proven they control, so inbound SMS to it can be received. The operator (not the app user)
holds the Telnyx credentials; users never see or enter an API key.

Network calls are isolated here so the hosting logic can be unit-tested with a fake client.
Going live requires a real Telnyx account, a messaging profile, a public inbound webhook,
and the Letter of Authorization that Telnyx requires to host/text-enable a number.
"""
from urllib.parse import quote

import requests

from config import APP_NAME, APP_VERSION

BASE_URL = "https://api.telnyx.com/v2"


class MessagingError(Exception):
    pass


class TelnyxMessagingClient:
    def __init__(self, api_key: str, messaging_profile_id: str | None = None,
                 timeout: float = 20, session: requests.Session | None = None,
                 base_url: str = BASE_URL):
        if not api_key:
            raise MessagingError("Telnyx messaging API key is not configured")
        self._api_key = api_key
        self.messaging_profile_id = messaging_profile_id
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json",
                "Content-Type": "application/json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"}

    def enable_messaging(self, e164: str) -> dict:
        """Text-enable / host a number for inbound SMS. Requires a valid LOA on the Telnyx side."""
        url = f"{self.base_url}/messaging_hosted_numbers"
        payload = {"phone_numbers": [e164]}
        if self.messaging_profile_id:
            payload["messaging_profile_id"] = self.messaging_profile_id
        try:
            resp = self._session.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise MessagingError(f"Network error contacting Telnyx: {exc.__class__.__name__}") from exc
        if resp.status_code >= 400:
            raise MessagingError(f"Telnyx messaging error ({resp.status_code})")
        try:
            return resp.json()
        except ValueError as exc:
            raise MessagingError("Telnyx returned a non-JSON response") from exc
