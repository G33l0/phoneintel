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
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS free_usage (
    day TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


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

    def get_admin_setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM admin_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_admin_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO admin_settings (key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        self.conn.commit()

    def all_admin_settings(self) -> dict:
        return {r["key"]: r["value"]
                for r in self.conn.execute("SELECT key, value FROM admin_settings").fetchall()}

    def free_validations_today(self, day: str) -> int:
        row = self.conn.execute("SELECT count FROM free_usage WHERE day = ?", (day,)).fetchone()
        return row["count"] if row else 0

    def try_consume_free_validation(self, day: str, daily_limit: int) -> tuple[bool, int]:
        """Atomically claim one free validation for `day`. Returns (allowed, remaining_after).

        The claim is a single guarded UPDATE: SQLite serialises writers, so the WHERE
        `count < limit` guard is re-checked against committed state for each caller and the
        counter can never exceed the limit, even with many connections racing.
        """
        self.conn.execute(
            "INSERT OR IGNORE INTO free_usage (day, count) VALUES (?, 0)", (day,))
        cursor = self.conn.execute(
            "UPDATE free_usage SET count = count + 1 WHERE day = ? AND count < ?",
            (day, daily_limit))
        self.conn.commit()
        if cursor.rowcount != 1:
            return False, 0
        return True, max(0, daily_limit - self.free_validations_today(day))

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

    def global_stats(self) -> dict:
        q = self.conn.execute
        stats = {
            "unique_numbers": q("SELECT COUNT(*) FROM phone_numbers").fetchone()[0],
            "lookups_total": q("SELECT COUNT(*) FROM lookup_results").fetchone()[0],
        }
        stats["by_status"] = {r[0]: r[1] for r in q(
            "SELECT status, COUNT(*) FROM lookup_results GROUP BY status").fetchall()}
        stats["by_classification"] = {r[0]: r[1] for r in q(
            "SELECT r.classification, COUNT(*) FROM lookup_results r JOIN ("
            "SELECT e164, MAX(id) AS id FROM lookup_results WHERE status = ? GROUP BY e164) l "
            "ON l.id = r.id GROUP BY r.classification", (LookupStatus.SUCCESS.value,)).fetchall()}
        return stats


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
