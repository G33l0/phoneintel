from dataclasses import dataclass

from classifier import LookupResult, LookupStatus, failed_result, invalid_result, parse_lookup_response
from config import AppConfig
from database import Database
from telnyx_client import AuthenticationError, RateLimiter, TelnyxClient, TelnyxError
from validator import ValidationResult, normalize


@dataclass
class EngineSettings:
    default_region: str = "US"
    concurrency: int = 4
    requests_per_second: float = 5.0
    max_retries: int = 3
    request_timeout: float = 15.0
    cache_days: int = 30
    batch_size: int = 100
    cost_per_lookup: float = 0.0025

    @classmethod
    def from_db(cls, db: Database) -> "EngineSettings":
        s = db.all_settings()
        return cls(
            default_region=s["default_region"],
            concurrency=int(s["concurrency"]),
            requests_per_second=float(s["requests_per_second"]),
            max_retries=int(s["max_retries"]),
            request_timeout=float(s["request_timeout"]),
            cache_days=int(s["cache_days"]),
            batch_size=int(s["batch_size"]),
            cost_per_lookup=float(s["cost_per_lookup"]),
        )


class PhoneIntelEngine:
    def __init__(self, db: Database, client: TelnyxClient | None, settings: EngineSettings):
        self.db = db
        self.client = client
        self.settings = settings

    @classmethod
    def from_config(cls, config: AppConfig, db: Database | None = None) -> "PhoneIntelEngine":
        db = db or Database(config.db_path)
        settings = EngineSettings.from_db(db)
        key = config.api_key()
        client = build_client(key, settings) if key else None
        return cls(db, client, settings)

    def validate(self, raw) -> ValidationResult:
        return normalize(raw, self.settings.default_region)

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
        rate_limiter=RateLimiter(settings.requests_per_second),
    )
