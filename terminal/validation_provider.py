"""Optional carrier-grade validation providers, used as a fallback for the offline validator.

The offline validator (free_validate.py) is primary and free. If a super-admin has configured
a fallback provider, it is consulted only when the offline validator is unavailable or errors.

IMPORTANT: carrier / line-type lookups from these providers are PAID (Twilio Lookup line-type
intelligence and Telnyx number lookup both bill per query). "Free" applies to the offline
validator only. Provider credentials belong to the operator/super-admin and are passed in here;
they are never stored in the app or shown to end users.
"""
from dataclasses import dataclass
from urllib.parse import quote

import requests

# provider line-type label -> PHONEINTEL classification hint
_LINE_TYPE_HINT = {
    "landline": "LANDLINE", "fixed line": "LANDLINE", "fixedline": "LANDLINE",
    "mobile": "MOBILE", "wireless": "MOBILE",
    "voip": "OTHER_VOIP", "nonfixedvoip": "NON_FIXED_VOIP", "fixedvoip": "FIXED_VOIP",
    "tollfree": "TOLL_FREE", "toll free": "TOLL_FREE", "premium": "OTHER",
    "unknown": "UNKNOWN",
}


class ProviderError(Exception):
    pass


@dataclass
class ProviderResult:
    valid: bool
    e164: str | None
    line_type: str | None
    classification_hint: str | None
    carrier: str | None
    source: str
    error: str | None = None


def _hint(line_type: str | None) -> str:
    if not line_type:
        return "UNKNOWN"
    key = "".join(ch for ch in line_type.lower() if ch.isalpha() or ch == " ").strip()
    return _LINE_TYPE_HINT.get(key, _LINE_TYPE_HINT.get(key.replace(" ", ""), "OTHER"))


def lookup_twilio(e164: str, account_sid: str, auth_token: str, timeout: float = 15,
                  session: requests.Session | None = None) -> ProviderResult:
    if not account_sid or not auth_token:
        raise ProviderError("Twilio credentials are not configured")
    url = f"https://lookups.twilio.com/v2/PhoneNumbers/{quote(e164, safe='')}"
    http = session or requests.Session()
    try:
        resp = http.get(url, params={"Fields": "line_type_intelligence"},
                        auth=(account_sid, auth_token), timeout=timeout)
    except requests.RequestException as exc:
        raise ProviderError(f"Twilio network error: {exc.__class__.__name__}") from exc
    if resp.status_code == 404:
        return ProviderResult(False, e164, None, "INVALID", None, "twilio", "Not found")
    if resp.status_code >= 400:
        raise ProviderError(f"Twilio lookup error ({resp.status_code})")
    data = resp.json() if resp.content else {}
    if data.get("valid") is False:
        return ProviderResult(False, data.get("phone_number"), None, "INVALID", None, "twilio")
    lti = data.get("line_type_intelligence") or {}
    line_type = lti.get("type")
    return ProviderResult(True, data.get("phone_number") or e164, line_type, _hint(line_type),
                          lti.get("carrier_name"), "twilio")


def lookup_telnyx(e164: str, api_key: str, timeout: float = 15,
                  session: requests.Session | None = None) -> ProviderResult:
    if not api_key:
        raise ProviderError("Telnyx credentials are not configured")
    url = f"https://api.telnyx.com/v2/number_lookup/{quote(e164, safe='')}"
    http = session or requests.Session()
    try:
        resp = http.get(url, params={"type": "carrier"},
                        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                        timeout=timeout)
    except requests.RequestException as exc:
        raise ProviderError(f"Telnyx network error: {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        raise ProviderError(f"Telnyx lookup error ({resp.status_code})")
    data = (resp.json() or {}).get("data", {}) if resp.content else {}
    if data.get("valid_number") is False:
        return ProviderResult(False, data.get("phone_number"), None, "INVALID", None, "telnyx")
    carrier = data.get("carrier") or {}
    line_type = carrier.get("type")
    return ProviderResult(True, data.get("phone_number") or e164, line_type, _hint(line_type),
                          carrier.get("name"), "telnyx")


def lookup(provider: str, e164: str, credentials: dict, session: requests.Session | None = None) -> ProviderResult:
    provider = (provider or "none").lower()
    if provider == "twilio":
        return lookup_twilio(e164, credentials.get("account_sid", ""),
                             credentials.get("auth_token", ""), session=session)
    if provider == "telnyx":
        return lookup_telnyx(e164, credentials.get("api_key", ""), session=session)
    raise ProviderError(f"No fallback provider configured ({provider})")
