"""Anonymous account identity for PHONEINTEL.

Onboarding mints a cryptographically-random 18-digit account ID. No email or phone is
collected. The raw ID is the user's only credential (like a recovery code) and is shown
once; only its salted hash is ever persisted, so a leak of stored data does not reveal any
usable ID. All lookups compare in constant time and are meant to be rate-limited by callers.
"""
import hashlib
import hmac
import secrets

ID_DIGITS = 18
# Fixed application salt for the identity hash. This is not a secret by itself; it only
# domain-separates these hashes. Online guessing is bounded by the caller's rate limiting.
_ID_HASH_INFO = b"phoneintel.account.id.v1"


def generate_account_id() -> str:
    """Return a fresh 18-digit account ID with no leading-zero loss (uniform over 10**18)."""
    # secrets.randbelow gives a uniform integer in [0, 10**18); zero-pad to 18 digits.
    return f"{secrets.randbelow(10 ** ID_DIGITS):0{ID_DIGITS}d}"


def is_well_formed(account_id: str) -> bool:
    account_id = (account_id or "").strip()
    return len(account_id) == ID_DIGITS and account_id.isdigit()


def hash_account_id(account_id: str) -> str:
    """Salted SHA-256 of a well-formed account ID, as hex. Raises on malformed input."""
    account_id = (account_id or "").strip()
    if not is_well_formed(account_id):
        raise ValueError("Account ID must be exactly 18 digits")
    return hashlib.sha256(_ID_HASH_INFO + account_id.encode("ascii")).hexdigest()


def account_ids_equal(candidate_hash: str, stored_hash: str) -> bool:
    return hmac.compare_digest((candidate_hash or ""), (stored_hash or ""))


def format_grouped(account_id: str) -> str:
    """Display helper: 1234-5678-9012-345678 style grouping for readability."""
    account_id = (account_id or "").strip()
    if not is_well_formed(account_id):
        return account_id
    return f"{account_id[:4]}-{account_id[4:8]}-{account_id[8:12]}-{account_id[12:]}"
