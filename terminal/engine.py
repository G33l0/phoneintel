from dataclasses import dataclass
from datetime import datetime, timezone

import os

from admin_config import AdminConfig
from classifier import LookupResult, LookupStatus, failed_result, invalid_result, parse_lookup_response
from config import FREE_VALIDATION_DAILY_LIMIT, AppConfig
from database import Database
from free_validate import FreeValidationResult, validate_offline
from telnyx_client import AuthenticationError, TelnyxClient, TelnyxError
from validator import ValidationResult, normalize
import validation_provider


@dataclass
class EngineSettings:
    default_region: str = "US"
    max_retries: int = 3
    request_timeout: float = 15.0
    cache_days: int = 30

    @classmethod
    def from_db(cls, db: Database) -> "EngineSettings":
        s = db.all_settings()
        return cls(
            default_region=s["default_region"],
            max_retries=int(s["max_retries"]),
            request_timeout=float(s["request_timeout"]),
            cache_days=int(s["cache_days"]),
        )


@dataclass
class FreeValidationOutcome:
    allowed: bool
    remaining: int
    limit: int
    result: FreeValidationResult | None = None
    message: str | None = None


class PhoneIntelEngine:
    def __init__(self, db: Database, client: TelnyxClient | None, settings: EngineSettings):
        self.db = db
        self.client = client
        self.settings = settings
        self.admin = AdminConfig(db)

    @classmethod
    def from_config(cls, config: AppConfig, db: Database | None = None) -> "PhoneIntelEngine":
        db = db or Database(config.db_path)
        settings = EngineSettings.from_db(db)
        key = config.api_key()
        client = build_client(key, settings) if key else None
        return cls(db, client, settings)

    def validate(self, raw) -> ValidationResult:
        return normalize(raw, self.settings.default_region)

    def free_validate(self, raw) -> FreeValidationResult:
        return self._free_validate_with_fallback(raw)

    def _free_validate_with_fallback(self, raw) -> FreeValidationResult:
        """Offline first; only if the offline validator errors do we try a configured provider."""
        try:
            return validate_offline(raw, self.settings.default_region)
        except Exception:
            fallback = self._provider_validate(raw)
            if fallback is not None:
                return fallback
            return FreeValidationResult(
                "" if raw is None else str(raw), False,
                error="Validation is temporarily unavailable. Please try again shortly.")

    def _provider_credentials(self, provider: str) -> dict:
        if provider == "twilio":
            return {"account_sid": os.environ.get("TWILIO_ACCOUNT_SID", ""),
                    "auth_token": os.environ.get("TWILIO_AUTH_TOKEN", "")}
        if provider == "telnyx":
            key = os.environ.get("TELNYX_API_KEY", "")
            return {"api_key": key}
        return {}

    def _provider_validate(self, raw) -> FreeValidationResult | None:
        provider = self.admin.fallback_provider()
        if provider == "none":
            return None
        check = normalize(raw, self.settings.default_region)
        if not check.valid:
            return FreeValidationResult("" if raw is None else str(raw), False,
                                        error=check.error or "Invalid number")
        try:
            result = validation_provider.lookup(provider, check.e164,
                                                self._provider_credentials(provider))
        except validation_provider.ProviderError:
            return None
        return FreeValidationResult(
            input=check.raw, valid=result.valid, e164=result.e164 or check.e164,
            country=check.country, region=None, national_format=None,
            line_type_hint=result.line_type, classification_hint=result.classification_hint,
            source=f"provider:{result.source}",
            note=f"Carrier lookup via {result.source} fallback (billable).")

    def free_validations_remaining(self) -> int:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        used = self.db.free_validations_today(day)
        return max(0, FREE_VALIDATION_DAILY_LIMIT - used)

    def free_validate_rate_limited(self, raw) -> FreeValidationOutcome:
        limit = FREE_VALIDATION_DAILY_LIMIT
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if raw is None or not str(raw).strip():
            return FreeValidationOutcome(
                allowed=True, remaining=self.free_validations_remaining(), limit=limit,
                result=self._free_validate_with_fallback(raw))
        allowed, remaining = self.db.try_consume_free_validation(day, limit)
        if not allowed:
            return FreeValidationOutcome(
                allowed=False, remaining=0, limit=limit,
                message=f"Free validation limit reached ({limit}/day). Try again tomorrow (UTC).")
        return FreeValidationOutcome(
            allowed=True, remaining=remaining, limit=limit,
            result=self._free_validate_with_fallback(raw))

    def cached(self, e164: str) -> tuple[int, LookupResult] | None:
        return self.db.cached_result(e164, self.settings.cache_days)

    def fetch(self, raw: str, e164: str, country: str | None = None) -> LookupResult:
        if self.client is None:
            raise AuthenticationError("Telnyx API key is not configured")
        try:
            payload = self.client.lookup(e164)
        except AuthenticationError:
            raise
        except TelnyxError as exc:
            return failed_result(raw, e164, str(exc), country)
        return parse_lookup_response(payload, raw, e164, country)

    def lookup(self, raw, force: bool = False) -> LookupResult:
        check = self.validate(raw)
        if not check.valid:
            result = invalid_result(check.raw, check.error or "Invalid number")
            self.db.save_result(result)
            return result
        if not force:
            hit = self.cached(check.e164)
            if hit:
                result = hit[1]
                result.input = check.raw
                result.status = LookupStatus.CACHED.value
                return result
        result = self.fetch(check.raw, check.e164, check.country)
        self.db.save_result(result)
        return result


def build_client(api_key: str, settings: EngineSettings) -> TelnyxClient:
    return TelnyxClient(
        api_key,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    )
