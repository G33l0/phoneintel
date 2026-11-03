import threading
from pathlib import Path

import exporter
from bulk_processor import (BulkProcessor, InputTable, JobSummary, PreparedJob, create_job, detect_column,
                            estimate, load_file, prepare_job)
from classifier import LookupResult
from config import DEFAULT_SETTINGS, AppConfig, mask_key, validate_setting
from database import Database
from engine import PhoneIntelEngine


class PhoneIntelService:
    """UI-agnostic facade. Every call opens its own SQLite connection so it is safe from any thread."""

    def __init__(self, base_dir: Path | str):
        self.config = AppConfig(Path(base_dir))
        self.config.ensure_dirs()
        with self._db() as db:
            db.mark_stale_running_jobs()

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

    def stats(self) -> dict:
        with self._db() as db:
            return db.global_stats()

    def recent(self, limit: int = 100, search: str | None = None) -> list[LookupResult]:
        with self._db() as db:
            return db.recent_results(limit, search or None)

    def jobs(self, limit: int = 20) -> list[dict]:
        with self._db() as db:
            return db.list_jobs(limit)

    def resumable_jobs(self) -> list[dict]:
        with self._db() as db:
            return db.resumable_jobs()

    def load_table(self, path: Path | str) -> tuple[InputTable, str | None]:
        table = load_file(path)
        with self._db() as db:
            region = db.get_setting("default_region")
        return table, detect_column(table, region)

    def prepare(self, table: InputTable, column: str, source: str, force: bool) -> tuple[PreparedJob, object]:
        with self._db() as db:
            engine = self._engine(db)
            prepared = prepare_job(table, column, source, engine.settings.default_region)
            return prepared, estimate(prepared, engine, force)

    def create_job(self, prepared: PreparedJob, force: bool) -> int:
        with self._db() as db:
            return create_job(self._engine(db), prepared, force)

    def run_job(self, job_id: int, progress=None, stop_event: threading.Event | None = None) -> JobSummary:
        with self._db() as db:
            engine = self._engine(db)
            if engine.client is None:
                raise ValueError("Add your Telnyx API key in Settings first")
            processor = BulkProcessor(engine)
            try:
                return processor.run(job_id, progress=progress, stop_event=stop_event)
            finally:
                exporter.export_job(db, job_id, self.config.export_dir)

    def job_buckets(self, job_id: int) -> dict:
        with self._db() as db:
            return BulkProcessor(self._engine(db)).bucket_counts(job_id)

    def job(self, job_id: int) -> dict | None:
        with self._db() as db:
            return db.get_job(job_id)

    def export_job(self, job_id: int) -> Path:
        with self._db() as db:
            return exporter.export_job(db, job_id, self.config.export_dir)

    def export_bucket(self, bucket: str) -> tuple[Path, int]:
        with self._db() as db:
            return exporter.export_bucket_numbers(db, bucket, self.config.export_dir)
