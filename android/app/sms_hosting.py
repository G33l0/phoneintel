"""Business-line SMS hosting: receive texts for a line your business owns, in the app.

Verification is performed by the operator/super-admin, not in the app. A user requests
hosting for a number; the admin validates the business's Letter of Authorization (LOA) for
that line - the same proof of authorization Telnyx requires to host/text-enable a number -
and only then marks it verified. This keeps a clear, auditable chain: a number is enabled
only after a human verified the requesting account is authorized for the line.

The hard gate remains: no inbound message is stored or shown for a number until it is
verified, and only to the account that owns it. A number is owned by one account at a time
and cannot be taken over.
"""
from dataclasses import dataclass

import hosting_db
import identity
from validator import normalize


@dataclass
class HostingError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class HostingRequest:
    e164: str
    status: str


class SMSHostingService:
    def __init__(self, db: hosting_db.HostingDB, messaging_client=None):
        self.db = db
        self.messaging = messaging_client

    # ---- onboarding / account

    def register_account(self, account_id: str, label: str | None = None) -> None:
        self.db.ensure_account(identity.hash_account_id(account_id), label)

    # ---- user requests hosting for a line their business owns

    def request_hosting(self, account_id: str, raw_number: str, region: str = "US") -> HostingRequest:
        id_hash = identity.hash_account_id(account_id)
        self.db.ensure_account(id_hash)
        check = normalize(raw_number, region)
        if not check.valid:
            raise HostingError(check.error or "That phone number is not valid.")
        e164 = check.e164
        existing = self.db.get_number(e164)
        if existing is not None and not identity.account_ids_equal(existing["account_id_hash"], id_hash):
            raise HostingError("This number is already registered to another account.")
        if existing is None:
            self.db.create_pending(e164, id_hash)
            return HostingRequest(e164, hosting_db.PENDING)
        return HostingRequest(e164, existing["status"])

    # ---- operator / super-admin verifies the LOA and marks the number verified

    def verify_ownership(self, e164: str, loa_reference: str, verified_by: str | None = None) -> bool:
        check = normalize(e164, "US")
        e164 = check.e164 or e164
        number = self.db.get_number(e164)
        if number is None:
            raise HostingError("No hosting request for that number.")
        if number["status"] in hosting_db.VERIFIED_STATES:
            return True
        if not (loa_reference or "").strip():
            raise HostingError("An LOA reference is required to verify ownership.")
        self.db.mark_verified(e164, loa_reference.strip(), verified_by)
        return True

    def enable_hosting(self, e164: str) -> dict:
        number = self.db.get_number(e164)
        if number is None or number["status"] not in hosting_db.VERIFIED_STATES:
            raise HostingError("The number must be verified before hosting can be enabled.")
        result = {"status": "pending_operator"}
        if self.messaging is not None:
            result = self.messaging.enable_messaging(e164)
            self.db.set_status(e164, hosting_db.ACTIVE)
        return result

    # ---- inbound + inbox (all gated by verified ownership)

    def ingest_inbound(self, e164: str, from_number: str | None, body: str) -> bool:
        check = normalize(e164, "US")
        return self.db.ingest_message(check.e164 or e164, from_number, body or "")

    def inbox(self, account_id: str, e164: str, limit: int = 200) -> list[dict]:
        return self.db.messages_for(identity.hash_account_id(account_id), e164, limit)

    def numbers(self, account_id: str) -> list[dict]:
        return self.db.numbers_for_account(identity.hash_account_id(account_id))

    def mark_read(self, account_id: str, e164: str) -> int:
        return self.db.mark_read(identity.hash_account_id(account_id), e164)

    def release(self, account_id: str, e164: str) -> bool:
        return self.db.release(e164, identity.hash_account_id(account_id))
