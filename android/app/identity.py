"""Anonymous account identity for PHONEINTEL.

Onboarding mints a random 18-character account ID that mixes uppercase letters and digits in
random positions (e.g. 7F2Q9K4M1DZ3BXR8TN). No email or phone is collected. The raw ID is the
user's only credential, shown once; only its salted hash is persisted, so a leak of stored
data never reveals a usable ID. All lookups compare in constant time and are meant to be
rate-limited by callers.

The 36-symbol alphabet over 18 positions gives ~93 bits of entropy (36**18 ~= 1e28), far
harder to guess than an all-digit ID, and letters scattered among the digits remove any
digit-only structure an attacker could exploit.
"""
import hashlib
import hmac
import secrets
import string

ID_LENGTH = 18
_ALPHABET = string.ascii_uppercase + string.digits  # A-Z 0-9, 36 symbols
_ALPHABET_SET = frozenset(_ALPHABET)
_MIN_LETTERS = 4
_MIN_DIGITS = 4
# Fixed application salt for the identity hash. Not secret on its own; it only
# domain-separates these hashes. Online guessing is bounded by the caller's rate limiting.
_ID_HASH_INFO = b"phoneintel.account.id.v2"


def generate_account_id() -> str:
    """Return a fresh 18-char ID with letters and digits scattered through the positions."""
    while True:
        chars = [secrets.choice(_ALPHABET) for _ in range(ID_LENGTH)]
        letters = sum(c.isalpha() for c in chars)
        if letters >= _MIN_LETTERS and (ID_LENGTH - letters) >= _MIN_DIGITS:
            return "".join(chars)


def is_well_formed(account_id: str) -> bool:
    account_id = (account_id or "").strip()
    return len(account_id) == ID_LENGTH and all(c in _ALPHABET_SET for c in account_id)


def hash_account_id(account_id: str) -> str:
    """Salted SHA-256 of a well-formed account ID, as hex. Raises on malformed input."""
    account_id = (account_id or "").strip()
    if not is_well_formed(account_id):
        raise ValueError(f"Account ID must be {ID_LENGTH} characters (A-Z, 0-9)")
    return hashlib.sha256(_ID_HASH_INFO + account_id.encode("ascii")).hexdigest()


def account_ids_equal(candidate_hash: str, stored_hash: str) -> bool:
    return hmac.compare_digest((candidate_hash or ""), (stored_hash or ""))


def format_grouped(account_id: str) -> str:
    """Display helper: XXXX-XXXX-XXXX-XXXXXX grouping for readability."""
    account_id = (account_id or "").strip()
    if not is_well_formed(account_id):
        return account_id
    return f"{account_id[:4]}-{account_id[4:8]}-{account_id[8:12]}-{account_id[12:]}"
