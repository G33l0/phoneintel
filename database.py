import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from classifier import LookupResult, LookupStatus, utc_now
from config import DEFAULT_SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS phone_numbers (
    e164 TEXT PRIMARY KEY,
    country TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lookup_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input TEXT,
    e164 TEXT,
    status TEXT NOT NULL,
    classification TEXT NOT NULL,
    country TEXT,
    carrier TEXT,
    line_type_raw TEXT,
    line_type_source TEXT,
    ported_status TEXT,
    ported_date TEXT,
    portability_json TEXT,
    error TEXT,
    looked_up_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_results_e164 ON lookup_results (e164, status, looked_up_at);
CREATE TABLE IF NOT EXISTS bulk_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    column_name TEXT NOT NULL,
    columns_json TEXT NOT NULL,
    status TEXT NOT NULL,
    force_refresh INTEGER NOT NULL DEFAULT 0,
    total_rows INTEGER NOT NULL DEFAULT 0,
    export_dir TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS job_records (
    job_id INTEGER NOT NULL REFERENCES bulk_jobs(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    raw_value TEXT,
    raw_json TEXT NOT NULL,
    e164 TEXT,
    status TEXT NOT NULL,
    duplicate_of INTEGER,
    result_id INTEGER REFERENCES lookup_results(id),
    validation_error TEXT,
    PRIMARY KEY (job_id, row_index)
);
CREATE INDEX IF NOT EXISTS idx_records_status ON job_records (job_id, status, e164);
CREATE TABLE IF NOT EXISTS job_statistics (
    job_id INTEGER NOT NULL REFERENCES bulk_jobs(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (job_id, metric)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

RESUMABLE_STATUSES = ("running", "interrupted", "paused")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get_setting(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else DEFAULT_SETTINGS[key]

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        self.conn.commit()

    def all_settings(self) -> dict:
        return {key: self.get_setting(key) for key in DEFAULT_SETTINGS}

    def save_result(self, result: LookupResult, commit: bool = True) -> int:
        if result.e164:
            now = utc_now()
            self.conn.execute(
                "INSERT INTO phone_numbers (e164, country, first_seen, last_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(e164) DO UPDATE SET last_seen = excluded.last_seen, "
                "country = COALESCE(excluded.country, phone_numbers.country)",
                (result.e164, result.country, now, now))
        cursor = self.conn.execute(
            "INSERT INTO lookup_results (input, e164, status, classification, country, carrier, "
            "line_type_raw, line_type_source, ported_status, ported_date, portability_json, error, "
            "looked_up_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (result.input, result.e164, result.status, result.classification, result.country,
             result.carrier, result.line_type_raw, result.line_type_source, result.ported_status,
             result.ported_date, json.dumps(result.portability or {}), result.error,
             result.looked_up_at))
        if commit:
            self.conn.commit()
        return cursor.lastrowid

    def cached_result(self, e164: str, max_age_days: int) -> tuple[int, LookupResult] | None:
        if max_age_days <= 0:
            return None
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat(timespec="seconds")
        row = self.conn.execute(
            "SELECT * FROM lookup_results WHERE e164 = ? AND status = ? AND looked_up_at >= ? "
            "ORDER BY looked_up_at DESC, id DESC LIMIT 1",
            (e164, LookupStatus.SUCCESS.value, cutoff)).fetchone()
        return (row["id"], row_to_result(row)) if row else None

    def get_result(self, result_id: int) -> LookupResult | None:
        row = self.conn.execute("SELECT * FROM lookup_results WHERE id = ?", (result_id,)).fetchone()
        return row_to_result(row) if row else None

    def recent_results(self, limit: int = 25, search: str | None = None) -> list[LookupResult]:
        if search:
            rows = self.conn.execute(
                "SELECT * FROM lookup_results WHERE e164 LIKE ? OR input LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{search}%", f"%{search}%", limit)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM lookup_results ORDER BY id DESC LIMIT ?",
                                     (limit,)).fetchall()
        return [row_to_result(r) for r in rows]

    def latest_successful(self, classifications: tuple[str, ...]) -> list[LookupResult]:
        marks = ",".join("?" * len(classifications))
        rows = self.conn.execute(
            f"SELECT r.* FROM lookup_results r JOIN ("
            f"  SELECT e164, MAX(id) AS id FROM lookup_results WHERE status = ? GROUP BY e164"
            f") latest ON latest.id = r.id WHERE r.classification IN ({marks}) ORDER BY r.e164",
            (LookupStatus.SUCCESS.value, *classifications)).fetchall()
        return [row_to_result(r) for r in rows]

    def create_job(self, source_file: str, column: str, columns: list[str], records: list[dict],
                   force_refresh: bool) -> int:
        now = utc_now()
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO bulk_jobs (source_file, column_name, columns_json, status, force_refresh, "
                "total_rows, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)",
                (source_file, column, json.dumps(columns), int(force_refresh), len(records), now, now))
            job_id = cursor.lastrowid
            self.conn.executemany(
                "INSERT INTO job_records (job_id, row_index, raw_value, raw_json, e164, status, "
                "duplicate_of, validation_error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(job_id, r["row_index"], r["raw_value"], json.dumps(r["row"], ensure_ascii=False),
                  r["e164"], r["status"], r["duplicate_of"], r["validation_error"]) for r in records])
        return job_id

    def get_job(self, job_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM bulk_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, limit: int = 20, statuses: tuple[str, ...] | None = None) -> list[dict]:
        if statuses:
            marks = ",".join("?" * len(statuses))
            rows = self.conn.execute(f"SELECT * FROM bulk_jobs WHERE status IN ({marks}) "
                                     f"ORDER BY id DESC LIMIT ?", (*statuses, limit)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM bulk_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def resumable_jobs(self) -> list[dict]:
        return self.list_jobs(limit=50, statuses=RESUMABLE_STATUSES)

    def update_job(self, job_id: int, **fields) -> None:
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE bulk_jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
        self.conn.commit()

    def pending_numbers(self, job_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT e164, MIN(row_index) AS first FROM job_records WHERE job_id = ? "
            "AND status IN ('pending', 'failed') AND e164 IS NOT NULL GROUP BY e164 ORDER BY first",
            (job_id,)).fetchall()
        return [r["e164"] for r in rows]

    def assign_result(self, job_id: int, e164: str, result_id: int, status: str, commit: bool = True) -> None:
        self.conn.execute("UPDATE job_records SET result_id = ?, status = ? WHERE job_id = ? AND e164 = ? "
                          "AND status IN ('pending', 'failed')", (result_id, status, job_id, e164))
        if commit:
            self.conn.commit()

    def job_records(self, job_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT jr.*, r.status AS r_status, r.classification, r.country, r.carrier, r.line_type_raw, "
            "r.line_type_source, r.ported_status, r.ported_date, r.error, r.looked_up_at "
            "FROM job_records jr LEFT JOIN lookup_results r ON r.id = jr.result_id "
            "WHERE jr.job_id = ? ORDER BY jr.row_index", (job_id,)).fetchall()
        return [dict(r) for r in rows]

    def record_status_counts(self, job_id: int) -> dict:
        rows = self.conn.execute("SELECT status, COUNT(*) AS n FROM job_records WHERE job_id = ? "
                                 "GROUP BY status", (job_id,)).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def increment_stat(self, job_id: int, metric: str, amount: float = 1, commit: bool = False) -> None:
        self.conn.execute("INSERT INTO job_statistics (job_id, metric, value) VALUES (?, ?, ?) "
                          "ON CONFLICT(job_id, metric) DO UPDATE SET value = value + excluded.value",
                          (job_id, metric, amount))
        if commit:
            self.conn.commit()

    def set_stat(self, job_id: int, metric: str, value: float) -> None:
        self.conn.execute("INSERT INTO job_statistics (job_id, metric, value) VALUES (?, ?, ?) "
                          "ON CONFLICT(job_id, metric) DO UPDATE SET value = excluded.value",
                          (job_id, metric, value))

    def job_stats(self, job_id: int) -> dict:
        rows = self.conn.execute("SELECT metric, value FROM job_statistics WHERE job_id = ?",
                                 (job_id,)).fetchall()
        return {r["metric"]: int(r["value"]) if float(r["value"]).is_integer() else r["value"]
                for r in rows}

    def global_stats(self) -> dict:
        q = self.conn.execute
        stats = {
            "unique_numbers": q("SELECT COUNT(*) FROM phone_numbers").fetchone()[0],
            "lookups_total": q("SELECT COUNT(*) FROM lookup_results").fetchone()[0],
            "jobs_total": q("SELECT COUNT(*) FROM bulk_jobs").fetchone()[0],
            "api_calls": q("SELECT COALESCE(SUM(value), 0) FROM job_statistics WHERE metric = 'api_calls'").fetchone()[0],
            "cache_hits": q("SELECT COALESCE(SUM(value), 0) FROM job_statistics WHERE metric = 'cache_hits'").fetchone()[0],
        }
        stats["by_status"] = {r[0]: r[1] for r in q(
            "SELECT status, COUNT(*) FROM lookup_results GROUP BY status").fetchall()}
        stats["by_classification"] = {r[0]: r[1] for r in q(
            "SELECT r.classification, COUNT(*) FROM lookup_results r JOIN ("
            "SELECT e164, MAX(id) AS id FROM lookup_results WHERE status = ? GROUP BY e164) l "
            "ON l.id = r.id GROUP BY r.classification", (LookupStatus.SUCCESS.value,)).fetchall()}
        return stats

    def mark_stale_running_jobs(self) -> int:
        cursor = self.conn.execute("UPDATE bulk_jobs SET status = 'interrupted', updated_at = ? "
                                   "WHERE status = 'running'", (utc_now(),))
        self.conn.commit()
        return cursor.rowcount


def row_to_result(row) -> LookupResult:
    return LookupResult(
        input=row["input"] or "",
        e164=row["e164"],
        status=row["status"],
        classification=row["classification"],
        country=row["country"],
        carrier=row["carrier"],
        line_type_raw=row["line_type_raw"],
        line_type_source=row["line_type_source"],
        ported_status=row["ported_status"],
        ported_date=row["ported_date"],
        portability=json.loads(row["portability_json"] or "{}"),
        error=row["error"],
        looked_up_at=row["looked_up_at"],
    )
