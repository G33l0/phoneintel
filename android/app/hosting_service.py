"""App-facing facade for business-line SMS hosting.

Holds the device's anonymous account identity (an 18-digit ID minted on first use and kept
in app-private storage) and exposes only user-safe operations. It deliberately does NOT
expose operator verification (confirm_ownership) - completing a verification is an operator
action performed from the admin side after the call, never something the app user can do to
their own request.
"""
import os
from pathlib import Path

import identity
from hosting_db import HostingDB
from sms_hosting import SMSHostingService


class HostingService:
    def __init__(self, base_dir: Path | str, messaging_client=None):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.id_path = self.base_dir / "account.id"
        self.db_path = self.base_dir / "hosting.db"
        self.messaging_client = messaging_client

    # ---- local anonymous account

    def account_id(self) -> str:
        if self.id_path.exists():
            existing = self.id_path.read_text(encoding="ascii").strip()
            if identity.is_well_formed(existing):
                return existing
        account_id = identity.generate_account_id()
        self.id_path.write_text(account_id, encoding="ascii")
        try:
            os.chmod(self.id_path, 0o600)
        except OSError:
            pass
        with self._db() as db:
            SMSHostingService(db).register_account(account_id)
        return account_id

    def account_id_grouped(self) -> str:
        return identity.format_grouped(self.account_id())

    def _db(self) -> HostingDB:
        return HostingDB(self.db_path)

    def _service(self, db) -> SMSHostingService:
        return SMSHostingService(db, self.messaging_client)

    # ---- user-safe operations

    def request_hosting(self, raw_number: str):
        with self._db() as db:
            return self._service(db).request_hosting(self.account_id(), raw_number)

    def numbers(self) -> list[dict]:
        with self._db() as db:
            return self._service(db).numbers(self.account_id())

    def inbox(self, e164: str, limit: int = 200) -> list[dict]:
        with self._db() as db:
            return self._service(db).inbox(self.account_id(), e164, limit)

    def mark_read(self, e164: str) -> int:
        with self._db() as db:
            return self._service(db).mark_read(self.account_id(), e164)

    def release(self, e164: str) -> bool:
        with self._db() as db:
            return self._service(db).release(self.account_id(), e164)

    def total_unread(self) -> int:
        with self._db() as db:
            service = self._service(db)
            account = self.account_id()
            return sum(db.unread_count(identity.hash_account_id(account), n["e164"])
                       for n in service.numbers(account))
