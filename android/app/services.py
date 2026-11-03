from pathlib import Path

from classifier import LookupResult
from config import DEFAULT_SETTINGS, AppConfig, mask_key, validate_setting
from database import Database
from engine import PhoneIntelEngine


class PhoneIntelService:
    """UI-agnostic facade. Every call opens its own SQLite connection so it is safe from any thread."""

    def __init__(self, base_dir: Path | str):
        self.config = AppConfig(Path(base_dir))
        self.config.ensure_dirs()

    def _db(self) -> Database:
        return Database(self.config.db_path)

    def _engine(self, db: Database) -> PhoneIntelEngine:
        return PhoneIntelEngine.from_config(self.config, db)

    def has_key(self) -> bool:
        return self.config.api_key() is not None

    def masked_key(self) -> str:
        return mask_key(self.config.api_key())

    def save_key(self, key: str) -> None:
        self.config.save_api_key(key)

    def remove_key(self) -> None:
        self.config.remove_api_key()

    def settings(self) -> dict:
        with self._db() as db:
            return db.all_settings()

    def update_settings(self, values: dict) -> dict:
        cleaned = {name: validate_setting(name, value) for name, value in values.items()
                   if name in DEFAULT_SETTINGS}
        with self._db() as db:
            for name, value in cleaned.items():
                db.set_setting(name, value)
        return cleaned

    def test_connection(self) -> dict:
        with self._db() as db:
            engine = self._engine(db)
            if engine.client is None:
                raise ValueError("Add your Telnyx API key first")
            return engine.client.check_connection()

    def is_cached(self, raw: str) -> bool:
        with self._db() as db:
            engine = self._engine(db)
            check = engine.validate(raw)
            return bool(check.valid and engine.cached(check.e164))

    def lookup(self, raw: str, force: bool = False) -> LookupResult:
        with self._db() as db:
            engine = self._engine(db)
            if engine.client is None:
                raise ValueError("Add your Telnyx API key in Settings first")
            return engine.lookup(raw, force=force)

    def free_validations_remaining(self) -> int:
        with self._db() as db:
            return self._engine(db).free_validations_remaining()

    def free_validate(self, raw: str):
        with self._db() as db:
            return self._engine(db).free_validate_rate_limited(raw)

    def stats(self) -> dict:
        with self._db() as db:
            return db.global_stats()

    def recent(self, limit: int = 100, search: str | None = None) -> list[LookupResult]:
        with self._db() as db:
            return db.recent_results(limit, search or None)
