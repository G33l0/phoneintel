import csv
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from classifier import EXPORT_BUCKETS, LookupResult, LookupStatus, export_bucket, utc_now
from engine import PhoneIntelEngine
from telnyx_client import AuthenticationError
from validator import normalize

SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".txt")
PHONE_HINTS = ("phone", "mobile", "msisdn", "cell", "tel", "number", "contact", "whatsapp", "e164")
TXT_COLUMN = "phone_number"
RECORD_STATUS = {
    LookupStatus.SUCCESS.value: "done",
    LookupStatus.CACHED.value: "done",
    LookupStatus.INVALID.value: "invalid",
    LookupStatus.FAILED.value: "failed",
}

ProgressCallback = Callable[[int, int, LookupResult | None], None]


class BulkInputError(Exception):
    pass


@dataclass
class PreparedJob:
    source_file: str
    column: str
    columns: list[str]
    records: list[dict]

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def invalid(self) -> int:
        return sum(1 for r in self.records if r["status"] == "invalid")

    @property
    def duplicates(self) -> int:
        return sum(1 for r in self.records if r["duplicate_of"] is not None)

    @property
    def unique_numbers(self) -> list[str]:
        return [r["e164"] for r in self.records if r["status"] == "pending" and r["duplicate_of"] is None]


@dataclass
class Estimate:
    total_rows: int
    invalid: int
    duplicates: int
    unique_valid: int
    cached: int
    to_lookup: int
    cost_per_lookup: float
    estimated_cost: float
    force_refresh: bool = False


@dataclass
class JobSummary:
    job_id: int
    status: str
    processed: int = 0
    api_calls: int = 0
    cache_hits: int = 0
    error: str | None = None
    buckets: dict = field(default_factory=dict)


def clean_path(text: str) -> Path:
    text = text.strip()
    if text.startswith("& "):
        text = text[2:].strip()
    return Path(text.strip("'\"")).expanduser()


def load_file(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise BulkInputError(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise BulkInputError(f"Unsupported file type '{suffix}'. Use CSV, XLSX or TXT.")
    if suffix == ".txt":
        return _load_txt(path)
    frame = _read_table(path, header=0)
    if any(normalize(c).valid for c in frame.columns):
        frame = _read_table(path, header=None)
        frame.columns = [f"column_{i + 1}" for i in range(len(frame.columns))]
    if frame.empty:
        raise BulkInputError("The file contains no data rows")
    frame.columns = _unique_columns([str(c).strip() or f"column_{i + 1}" for i, c in enumerate(frame.columns)])
    return frame


def _read_table(path: Path, header) -> pd.DataFrame:
    try:
        if path.suffix.lower() == ".xlsx":
            return pd.read_excel(path, dtype=str, keep_default_na=False, header=header, engine="openpyxl")
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                return pd.read_csv(path, dtype=str, keep_default_na=False, header=header,
                                   sep=_sniff_delimiter(path, encoding), encoding=encoding)
            except UnicodeDecodeError:
                continue
    except pd.errors.EmptyDataError as exc:
        raise BulkInputError("The file is empty") from exc
    except Exception as exc:
        raise BulkInputError(f"Could not read file: {exc}") from exc
    raise BulkInputError("Could not decode file text")


def _sniff_delimiter(path: Path, encoding: str) -> str:
    with path.open(encoding=encoding, newline="") as handle:
        sample = handle.read(8192)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _load_txt(path: Path) -> pd.DataFrame:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise BulkInputError("The file contains no phone numbers")
    return pd.DataFrame({TXT_COLUMN: lines})


def _unique_columns(columns: list[str]) -> list[str]:
    seen, result = {}, []
    for name in columns:
        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if count == 0 else f"{name}_{count + 1}")
    return result


def detect_column(frame: pd.DataFrame, region: str = "US", sample: int = 50) -> str | None:
    scores = {}
    for column in frame.columns:
        values = [v for v in frame[column].head(sample).tolist() if str(v).strip()]
        if not values:
            continue
        valid = sum(1 for v in values if normalize(v, region).valid)
        ratio = valid / len(values)
        hint = any(h in str(column).lower() for h in PHONE_HINTS)
        if ratio > 0 or hint:
            scores[column] = ratio + (0.25 if hint else 0)
    if not scores:
        return None
    best = max(scores, key=scores.get)
    return best if scores[best] >= 0.25 else None


def prepare_job(frame: pd.DataFrame, column: str, source_file: str, region: str = "US") -> PreparedJob:
    if column not in frame.columns:
        raise BulkInputError(f"Column '{column}' not found")
    first_seen: dict[str, int] = {}
    records = []
    for index, row in enumerate(frame.to_dict(orient="records")):
        raw = "" if row[column] is None else str(row[column])
        check = normalize(raw, region)
        duplicate_of = None
        if check.valid:
            duplicate_of = first_seen.get(check.e164)
            first_seen.setdefault(check.e164, index)
        records.append({
            "row_index": index,
            "raw_value": raw,
            "row": {k: "" if v is None else str(v) for k, v in row.items()},
            "e164": check.e164,
            "status": "pending" if check.valid else "invalid",
            "duplicate_of": duplicate_of,
            "validation_error": check.error,
        })
    return PreparedJob(str(source_file), column, [str(c) for c in frame.columns], records)


def estimate(prepared: PreparedJob, engine: PhoneIntelEngine, force: bool = False) -> Estimate:
    unique = prepared.unique_numbers
    cached = 0 if force else sum(1 for n in unique if engine.cached(n))
    to_lookup = len(unique) - cached
    cost = engine.settings.cost_per_lookup
    return Estimate(prepared.total, prepared.invalid, prepared.duplicates, len(unique), cached,
                    to_lookup, cost, round(to_lookup * cost, 4), force)


def create_job(engine: PhoneIntelEngine, prepared: PreparedJob, force: bool = False) -> int:
    return engine.db.create_job(prepared.source_file, prepared.column, prepared.columns,
                                prepared.records, force)


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


class BulkProcessor:
    def __init__(self, engine: PhoneIntelEngine):
        self.engine = engine
        self.db = engine.db

    def run(self, job_id: int, progress: ProgressCallback | None = None,
            stop_event: threading.Event | None = None) -> JobSummary:
        job = self.db.get_job(job_id)
        if job is None:
            raise BulkInputError(f"Job {job_id} not found")
        if self.engine.client is None:
            raise AuthenticationError("Telnyx API key is not configured")
        self.db.update_job(job_id, status="running", error=None)
        summary = JobSummary(job_id, "running")
        numbers = self.db.pending_numbers(job_id)
        total = len(numbers)
        notify = progress or (lambda *_: None)
        notify(0, total, None)
        to_fetch = self._apply_cache(job_id, numbers, bool(job["force_refresh"]), summary, notify, total)
        pool = ThreadPoolExecutor(max_workers=self.engine.settings.concurrency)
        try:
            for batch in _chunks(to_fetch, self.engine.settings.batch_size):
                if stop_event is not None and stop_event.is_set():
                    return self._stop(job_id, summary, "interrupted", "Stopped by user")
                self._run_batch(pool, job_id, batch, summary, notify, total)
        except AuthenticationError as exc:
            self.db.conn.commit()
            self._stop(job_id, summary, "paused", str(exc))
            raise
        except KeyboardInterrupt:
            self.db.conn.commit()
            self._stop(job_id, summary, "interrupted", "Interrupted by user")
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return self._finish(job_id, summary)

    def _apply_cache(self, job_id, numbers, force, summary, notify, total) -> list[str]:
        if force:
            return list(numbers)
        remaining = []
        for e164 in numbers:
            hit = self.engine.cached(e164)
            if not hit:
                remaining.append(e164)
                continue
            self.db.assign_result(job_id, e164, hit[0], "done", commit=False)
            self.db.increment_stat(job_id, "cache_hits")
            summary.cache_hits += 1
            summary.processed += 1
            notify(summary.processed, total, hit[1])
        self.db.conn.commit()
        return remaining

    def _run_batch(self, pool, job_id, batch, summary, notify, total) -> None:
        futures = {pool.submit(self.engine.fetch, e164, e164): e164 for e164 in batch}
        pending = set(futures)
        try:
            while pending:
                finished, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for future in finished:
                    result = future.result()
                    self._store(job_id, futures[future], result, summary)
                    notify(summary.processed, total, result)
        finally:
            for future in pending:
                future.cancel()
            self.db.conn.commit()

    def _store(self, job_id: int, e164: str, result: LookupResult, summary: JobSummary) -> None:
        result_id = self.db.save_result(result, commit=False)
        self.db.assign_result(job_id, e164, result_id, RECORD_STATUS[result.status], commit=False)
        self.db.increment_stat(job_id, "api_calls")
        summary.api_calls += 1
        summary.processed += 1

    def _stop(self, job_id: int, summary: JobSummary, status: str, error: str) -> JobSummary:
        self.update_statistics(job_id)
        self.db.update_job(job_id, status=status, error=error)
        summary.status, summary.error = status, error
        summary.buckets = self.bucket_counts(job_id)
        return summary

    def _finish(self, job_id: int, summary: JobSummary) -> JobSummary:
        self.update_statistics(job_id)
        counts = self.db.record_status_counts(job_id)
        status = "interrupted" if counts.get("pending") else "completed"
        self.db.update_job(job_id, status=status, finished_at=utc_now())
        summary.status = status
        summary.buckets = self.bucket_counts(job_id)
        return summary

    def bucket_counts(self, job_id: int) -> dict:
        counts = {bucket: 0 for bucket in EXPORT_BUCKETS}
        counts["PENDING"] = 0
        for record in self.db.job_records(job_id):
            counts[record_bucket(record)] += 1
        return counts

    def update_statistics(self, job_id: int) -> None:
        counts = self.db.record_status_counts(job_id)
        for status in ("pending", "done", "invalid", "failed"):
            self.db.set_stat(job_id, f"rows_{status}", counts.get(status, 0))
        duplicates = self.db.conn.execute(
            "SELECT COUNT(*) FROM job_records WHERE job_id = ? AND duplicate_of IS NOT NULL",
            (job_id,)).fetchone()[0]
        self.db.set_stat(job_id, "duplicates", duplicates)
        for bucket, value in self.bucket_counts(job_id).items():
            self.db.set_stat(job_id, f"bucket_{bucket.lower()}", value)
        self.db.conn.commit()


def record_bucket(record: dict) -> str:
    if record["status"] == "invalid" and not record.get("result_id"):
        return "INVALID"
    if record["status"] == "pending" or not record.get("r_status"):
        return "PENDING"
    return export_bucket(record["r_status"], record["classification"])
