"""Super-admin configuration: fallback validation provider and SMS hosting pricing.

These values are meant to be editable only by a super-admin (via the admin portal, or the
bundled admin_tool.py). They are stored as hashed-free key/value rows in `admin_settings`.
Provider API credentials are NOT stored here - only which provider is selected; secrets stay
in the operator's secure store / environment, never in the app or the database.

Pricing model (all editable):
  billable = provider_cost * (1 + margin_percent / 100)
Defaults: receiving SMS carries a 110% margin, sending (if offered) a 200% margin.
"""
from dataclasses import dataclass

VALIDATION_PROVIDERS = ("none", "twilio", "telnyx")

DEFAULTS = {
    "fallback_validation_provider": "none",      # used only if the offline validator fails
    "sms_send_enabled": "false",
    "currency": "USD",
    "provider_cost_receive": "0.0",              # operator's wholesale cost per inbound SMS
    "provider_cost_send": "0.0",                 # operator's wholesale cost per outbound SMS
    "margin_receive_percent": "110",
    "margin_send_percent": "200",
}

_BOOL = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_admin_setting(key: str, value: str) -> str:
    value = str(value).strip()
    if key not in DEFAULTS:
        raise ValueError(f"Unknown admin setting: {key}")
    if key == "fallback_validation_provider":
        if value.lower() not in VALIDATION_PROVIDERS:
            raise ValueError(f"Provider must be one of {', '.join(VALIDATION_PROVIDERS)}")
        return value.lower()
    if key == "sms_send_enabled":
        if value.lower() not in _BOOL:
            raise ValueError("sms_send_enabled must be true or false")
        return "true" if _BOOL[value.lower()] else "false"
    if key == "currency":
        if not value.isalpha() or len(value) != 3:
            raise ValueError("currency must be a 3-letter code, e.g. USD")
        return value.upper()
    if not _is_number(value):
        raise ValueError(f"{key} must be numeric")
    number = float(value)
    if number < 0:
        raise ValueError(f"{key} cannot be negative")
    if key.endswith("_percent") and number > 100000:
        raise ValueError("margin percent is unreasonably large")
    return repr(number) if "." in value or key.startswith("provider_cost") else str(number)


@dataclass
class PricingQuote:
    currency: str
    provider_cost: float
    margin_percent: float
    billable: float
    profit: float


class AdminConfig:
    """Typed accessor over the DB admin_settings table. `db` is a Database instance."""

    def __init__(self, db):
        self.db = db

    def get(self, key: str) -> str:
        if key not in DEFAULTS:
            raise ValueError(f"Unknown admin setting: {key}")
        stored = self.db.get_admin_setting(key)
        return stored if stored is not None else DEFAULTS[key]

    def set(self, key: str, value: str) -> str:
        cleaned = validate_admin_setting(key, value)
        self.db.set_admin_setting(key, cleaned)
        return cleaned

    def all(self) -> dict:
        return {key: self.get(key) for key in DEFAULTS}

    # ---- typed helpers

    def fallback_provider(self) -> str:
        return self.get("fallback_validation_provider")

    def send_enabled(self) -> bool:
        return _BOOL.get(self.get("sms_send_enabled").lower(), False)

    def currency(self) -> str:
        return self.get("currency")

    def _quote(self, cost_key: str, margin_key: str) -> PricingQuote:
        cost = float(self.get(cost_key))
        margin = float(self.get(margin_key))
        billable = round(cost * (1 + margin / 100), 6)
        return PricingQuote(self.currency(), cost, margin, billable, round(billable - cost, 6))

    def receive_quote(self) -> PricingQuote:
        return self._quote("provider_cost_receive", "margin_receive_percent")

    def send_quote(self) -> PricingQuote | None:
        if not self.send_enabled():
            return None
        return self._quote("provider_cost_send", "margin_send_percent")
