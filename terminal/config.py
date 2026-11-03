import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

APP_NAME = "PHONEINTEL"
APP_VERSION = "1.1.0"
FREE_VALIDATION_DAILY_LIMIT = 2
API_KEY_VAR = "TELNYX_API_KEY"
TELNYX_BASE_URL = "https://api.telnyx.com/v2"

DEFAULT_SETTINGS = {
    "default_region": "US",
    "concurrency": "4",
    "requests_per_second": "5",
    "max_retries": "3",
    "request_timeout": "15",
    "cache_days": "30",
    "batch_size": "100",
    "cost_per_lookup": "0.0025",
}

SETTING_LIMITS = {
    "concurrency": (1, 20),
    "requests_per_second": (0.2, 40),
    "max_retries": (0, 10),
    "request_timeout": (3, 120),
    "cache_days": (0, 3650),
    "batch_size": (1, 1000),
    "cost_per_lookup": (0, 10),
}

SETTING_DESCRIPTIONS = {
    "default_region": "Region used for numbers without a + prefix",
    "concurrency": "Parallel API workers during bulk jobs",
    "requests_per_second": "Global API throttle (requests per second)",
    "max_retries": "Retries for 429, 5xx and network failures",
    "request_timeout": "HTTP timeout in seconds",
    "cache_days": "Days a successful lookup stays cached (0 = off)",
    "batch_size": "Numbers per committed batch",
    "cost_per_lookup": "Estimated USD cost per lookup (verify with Telnyx)",
}


def _base_dir() -> Path:
    override = os.environ.get("PHONEINTEL_HOME")
    return Path(override).expanduser().resolve() if override else Path(__file__).resolve().parent


@dataclass
class AppConfig:
    base_dir: Path = field(default_factory=_base_dir)

    @property
    def env_path(self) -> Path:
        return self.base_dir / ".env"

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def export_dir(self) -> Path:
        return self.base_dir / "exports"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "phoneintel.db"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def api_key(self) -> str | None:
        key = os.environ.get(API_KEY_VAR)
        if not key and self.env_path.exists():
            key = dotenv_values(self.env_path).get(API_KEY_VAR)
        key = (key or "").strip()
        return key or None

    def save_api_key(self, key: str) -> None:
        key = key.strip()
        if not is_plausible_key(key):
            raise ValueError("API key format looks invalid")
        if not self.env_path.exists():
            self.env_path.touch()
        set_key(str(self.env_path), API_KEY_VAR, key, quote_mode="never")
        _restrict_permissions(self.env_path)
        os.environ[API_KEY_VAR] = key

    def remove_api_key(self) -> None:
        if self.env_path.exists():
            unset_key(str(self.env_path), API_KEY_VAR)
        os.environ.pop(API_KEY_VAR, None)


def is_plausible_key(key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-\.]{20,200}", key or ""))


def mask_key(key: str | None) -> str:
    if not key:
        return "not configured"
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 8}{key[-4:]}"


def validate_setting(name: str, value: str) -> str:
    value = str(value).strip()
    if name not in DEFAULT_SETTINGS:
        raise ValueError(f"Unknown setting: {name}")
    if name == "default_region":
        if not re.fullmatch(r"[A-Za-z]{2}", value):
            raise ValueError("Region must be a two-letter ISO code, e.g. US")
        return value.upper()
    low, high = SETTING_LIMITS[name]
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not low <= number <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    if name in ("requests_per_second", "cost_per_lookup"):
        return str(number)
    if not number.is_integer():
        raise ValueError(f"{name} must be a whole number")
    return str(int(number))


def _restrict_permissions(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass
