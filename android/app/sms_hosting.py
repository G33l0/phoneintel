"""Business-line SMS hosting: prove control of a line you own, then receive its SMS in-app.

Ownership proof (the security core):
  1. The authenticated account requests hosting for a number it owns.
  2. A one-time code is generated and shown ONLY inside that account's app session.
  3. An operator calls the number. Whoever answers must read the code back.
  4. The operator confirms the spoken code. A match proves the person who answers the line
     and the app account are the same party, i.e. the account controls the line.

Only after that does the number move to a verified state, and only then is any inbound
message for it stored or shown - and only to the owning account. A number already verified
by one account can never be claimed by another.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import hosting_db
import identity
from validator import normalize

CODE_DIGITS = 6
CODE_TTL_MINUTES = 15
MAX_ATTEMPTS = 5
_CODE_HASH_INFO = b"phoneintel.ownership.code.v1"


def _hash_code(e164: str, code: str) -> str:
    # bind the hash to the number so a code is only valid for the number it was issued for
    return hashlib.sha256(_CODE_HASH_INFO + e164.encode() + b"|" + code.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class HostingError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass
class VerificationRequest:
    e164: str
    code: str
    expires_at: str


class SMSHostingService:
    def __init__(self, db: hosting_db.HostingDB, messaging_client=None):
        self.db = db
        self.messaging = messaging_client

    # ---- onboarding / account

    def register_account(self, account_id: str, label: str | None = None) -> None:
        self.db.ensure_account(identity.hash_account_id(account_id), label)

    # ---- request hosting for an owned business line

    def request_hosting(self, account_id: str, raw_number: str, region: str = "US") -> VerificationRequest:
        id_hash = identity.hash_account_id(account_id)
        self.db.ensure_account(id_hash)
        check = normalize(raw_number, region)
        if not check.valid:
            raise HostingError(check.error or "That phone number is not valid.")
        e164 = check.e164
        existing = self.db.get_number(e164)
        if existing is not None and not identity.account_ids_equal(existing["account_id_hash"], id_hash):
            # owned (or being verified) by a different account - never allow a takeover
            raise HostingError("This number is already registered to another account.")
        if existing is None:
            self.db.create_pending(e164, id_hash)
        elif existing["status"] in hosting_db.VERIFIED_STATES:
            raise HostingError("This number is already verified on your account.")
        code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
        expires = (_now() + timedelta(minutes=CODE_TTL_MINUTES)).isoformat(timespec="seconds")
        self.db.upsert_verification(e164, id_hash, _hash_code(e164, code), expires, MAX_ATTEMPTS)
        return VerificationRequest(e164=e164, code=code, expires_at=expires)

    # ---- operator confirms the code spoken over the verification call

    def confirm_ownership(self, e164: str, spoken_code: str) -> bool:
        check = normalize(e164, "US")
        e164 = check.e164 or e164
        record = self.db.get_verification(e164)
        if record is None:
            raise HostingError("No pending verification for that number.")
        if datetime.fromisoformat(record["expires_at"]) < _now():
            self.db.clear_verification(e164)
            raise HostingError("The verification code has expired. Ask the user to request a new one.")
        if record["attempts"] >= record["max_attempts"]:
            self.db.clear_verification(e164)
            raise HostingError("Too many incorrect attempts. Ask the user to request a new code.")
        spoken = "".join(ch for ch in (spoken_code or "") if ch.isdigit())
        if not hmac.compare_digest(_hash_code(e164, spoken), record["code_hash"]):
            remaining = record["max_attempts"] - self.db.bump_attempts(e164)
            raise HostingError(f"Code does not match. {max(0, remaining)} attempt(s) left.")
        self.db.clear_verification(e164)
        self.db.set_status(e164, hosting_db.VERIFIED, verified=True)
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
