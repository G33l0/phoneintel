"""SQLite store for business-line SMS hosting.

Security invariants enforced here:
  * Inbound messages are only retrievable by the account that owns the number AND only
    while that number is in a verified/active state. The query always joins through
    hosted_numbers, so there is no code path that returns a message without ownership.
  * A number can be owned by at most one account (PRIMARY KEY on e164). A number already
    claimed by one account cannot be taken over by another.
  * Account IDs are stored only as hashes.
  * Verification is an operator action: a number only becomes verified when the admin
    confirms the business's Letter of Authorization (LOA) for it. The LOA reference and the
    time are recorded for audit. Nothing on the client can self-verify.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# hosted_numbers.status lifecycle
PENDING = "pending_verification"
VERIFIED = "verified"
ACTIVE = "hosting_active"
RELEASED = "released"
VERIFIED_STATES = (VERIFIED, ACTIVE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id_hash TEXT PRIMARY KEY,
    label TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hosted_numbers (
    e164 TEXT PRIMARY KEY,
    account_id_hash TEXT NOT NULL REFERENCES accounts(id_hash),
    status TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    verified_at TEXT,
    verified_by TEXT,
    loa_reference TEXT,
    released_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_hosted_account ON hosted_numbers (account_id_hash, status);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    e164 TEXT NOT NULL,
    from_number TEXT,
    body TEXT NOT NULL,
    received_at TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_e164 ON messages (e164, id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HostingDB:
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

    def __enter__(self) -> "HostingDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- accounts

    def ensure_account(self, id_hash: str, label: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO accounts (id_hash, label, created_at) VALUES (?, ?, ?)",
            (id_hash, label, utc_now()))
        self.conn.commit()

    def account_exists(self, id_hash: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM accounts WHERE id_hash = ?", (id_hash,)).fetchone() is not None

    # ---- hosted numbers

    def get_number(self, e164: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM hosted_numbers WHERE e164 = ?", (e164,)).fetchone()
        return dict(row) if row else None

    def numbers_for_account(self, id_hash: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM hosted_numbers WHERE account_id_hash = ? AND status != ? "
            "ORDER BY requested_at DESC", (id_hash, RELEASED)).fetchall()
        return [dict(r) for r in rows]

    def create_pending(self, e164: str, id_hash: str) -> None:
        self.conn.execute(
            "INSERT INTO hosted_numbers (e164, account_id_hash, status, requested_at) "
            "VALUES (?, ?, ?, ?)", (e164, id_hash, PENDING, utc_now()))
        self.conn.commit()

    def mark_verified(self, e164: str, loa_reference: str, verified_by: str | None = None) -> None:
        self.conn.execute(
            "UPDATE hosted_numbers SET status = ?, verified_at = ?, verified_by = ?, "
            "loa_reference = ? WHERE e164 = ?",
            (VERIFIED, utc_now(), verified_by, loa_reference, e164))
        self.conn.commit()

    def set_status(self, e164: str, status: str) -> None:
        self.conn.execute("UPDATE hosted_numbers SET status = ? WHERE e164 = ?", (status, e164))
        self.conn.commit()

    def release(self, e164: str, id_hash: str) -> bool:
        """Fully remove a number this account owns, along with its messages.

        A hard delete (not a status flag) so the number can be claimed again later and no
        private message survives a release. The account guard means one account can never
        release another's number.
        """
        cur = self.conn.execute(
            "DELETE FROM hosted_numbers WHERE e164 = ? AND account_id_hash = ?", (e164, id_hash))
        if cur.rowcount == 1:
            self.conn.execute("DELETE FROM messages WHERE e164 = ?", (e164,))
        self.conn.commit()
        return cur.rowcount == 1

    # ---- messages (always gated through hosted_numbers ownership)

    def ingest_message(self, e164: str, from_number: str | None, body: str) -> bool:
        """Store an inbound message only if the number is in a verified/active state."""
        number = self.get_number(e164)
        if number is None or number["status"] not in VERIFIED_STATES:
            return False
        self.conn.execute(
            "INSERT INTO messages (e164, from_number, body, received_at) VALUES (?, ?, ?, ?)",
            (e164, from_number, body, utc_now()))
        self.conn.commit()
        return True

    def messages_for(self, id_hash: str, e164: str, limit: int = 200) -> list[dict]:
        """Return messages for a number ONLY if this account owns it in a verified state."""
        marks = ",".join("?" * len(VERIFIED_STATES))
        rows = self.conn.execute(
            f"SELECT m.* FROM messages m "
            f"JOIN hosted_numbers h ON h.e164 = m.e164 "
            f"WHERE m.e164 = ? AND h.account_id_hash = ? AND h.status IN ({marks}) "
            f"ORDER BY m.id DESC LIMIT ?",
            (e164, id_hash, *VERIFIED_STATES, limit)).fetchall()
        return [dict(r) for r in rows]

    def mark_read(self, id_hash: str, e164: str) -> int:
        cur = self.conn.execute(
            "UPDATE messages SET read = 1 WHERE e164 = ? AND read = 0 AND e164 IN "
            "(SELECT e164 FROM hosted_numbers WHERE e164 = ? AND account_id_hash = ?)",
            (e164, e164, id_hash))
        self.conn.commit()
        return cur.rowcount

    def unread_count(self, id_hash: str, e164: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM messages m JOIN hosted_numbers h ON h.e164 = m.e164 "
            "WHERE m.e164 = ? AND h.account_id_hash = ? AND m.read = 0",
            (e164, id_hash)).fetchone()
        return row["n"] if row else 0
