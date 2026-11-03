import re
from dataclasses import dataclass

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

_FLOAT_ARTIFACT = re.compile(r"^\+?\d+\.0+$")
_ALLOWED_CHARS = re.compile(r"^[\d\s\+\-\.\(\)/]+$|^[\d\s\+\-\.\(\)/]*(ext\.?|x|#)\s*\d+$", re.I)


@dataclass(frozen=True)
class ValidationResult:
    raw: str
    e164: str | None
    valid: bool
    country: str | None = None
    error: str | None = None


def clean_input(raw) -> str:
    if raw is None:
        return ""
    text = str(raw).strip().strip("'\"").strip()
    if text.lower() in ("nan", "none", "null"):
        return ""
    if _FLOAT_ARTIFACT.match(text):
        text = text.split(".")[0]
    return text


def normalize(raw, region: str = "US") -> ValidationResult:
    original = "" if raw is None else str(raw)
    text = clean_input(raw)
    if not text:
        return ValidationResult(original, None, False, error="Empty value")
    if not _ALLOWED_CHARS.match(text):
        return ValidationResult(original, None, False, error="Contains invalid characters")
    if text.startswith("00"):
        text = "+" + text[2:]
    try:
        parsed = phonenumbers.parse(text, region.upper())
    except NumberParseException:
        return ValidationResult(original, None, False, error="Unparseable phone number")
    if not phonenumbers.is_valid_number(parsed):
        return ValidationResult(original, None, False, error="Not a valid phone number")
    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    country = phonenumbers.region_code_for_number(parsed)
    return ValidationResult(original, e164, True, country)


def is_valid(raw, region: str = "US") -> bool:
    return normalize(raw, region).valid
