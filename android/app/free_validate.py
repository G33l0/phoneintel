"""Offline phone validation — no Telnyx, no network, no API key.

Uses the bundled phonenumbers metadata only. It confirms that a number is
well-formed and dialable and gives the number plan's line-type *hint*, which is
derived from numbering-plan ranges, not from a live carrier lookup. It is clearly
labelled as an estimate so it is never confused with a Telnyx carrier result.
"""
from dataclasses import dataclass, field

import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType, geocoder

from validator import normalize

# phonenumbers number-plan type -> (human label, PHONEINTEL classification hint)
_TYPE_LABELS = {
    PhoneNumberType.MOBILE: ("Mobile", "MOBILE"),
    PhoneNumberType.FIXED_LINE: ("Fixed line / landline", "LANDLINE"),
    PhoneNumberType.FIXED_LINE_OR_MOBILE: ("Fixed line or mobile", "UNKNOWN"),
    PhoneNumberType.TOLL_FREE: ("Toll-free", "TOLL_FREE"),
    PhoneNumberType.PREMIUM_RATE: ("Premium rate", "OTHER"),
    PhoneNumberType.SHARED_COST: ("Shared cost", "OTHER"),
    PhoneNumberType.VOIP: ("VoIP", "OTHER_VOIP"),
    PhoneNumberType.PERSONAL_NUMBER: ("Personal number", "OTHER"),
    PhoneNumberType.PAGER: ("Pager", "OTHER"),
    PhoneNumberType.UAN: ("UAN", "OTHER"),
    PhoneNumberType.VOICEMAIL: ("Voicemail", "OTHER"),
    PhoneNumberType.UNKNOWN: ("Unknown", "UNKNOWN"),
}


@dataclass
class FreeValidationResult:
    input: str
    valid: bool
    e164: str | None = None
    country: str | None = None
    region: str | None = None
    national_format: str | None = None
    line_type_hint: str | None = None
    classification_hint: str | None = None
    error: str | None = None
    source: str = "offline"
    note: str = "Offline estimate from the number plan - not a live carrier lookup."

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "input", "valid", "e164", "country", "region", "national_format",
            "line_type_hint", "classification_hint", "error", "source")}


def validate_offline(raw, region: str = "US") -> FreeValidationResult:
    check = normalize(raw, region)
    original = check.raw if check.raw else ("" if raw is None else str(raw))
    if not check.valid:
        return FreeValidationResult(original, False, error=check.error or "Invalid number")
    parsed = phonenumbers.parse(check.e164, None)
    label, classification = _TYPE_LABELS.get(
        phonenumbers.number_type(parsed), ("Unknown", "UNKNOWN"))
    place = geocoder.description_for_number(parsed, "en") or None
    return FreeValidationResult(
        input=original,
        valid=True,
        e164=check.e164,
        country=check.country,
        region=place,
        national_format=phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL),
        line_type_hint=label,
        classification_hint=classification,
    )
