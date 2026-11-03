import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Classification(str, Enum):
    MOBILE = "MOBILE"
    LANDLINE = "LANDLINE"
    FIXED_VOIP = "FIXED_VOIP"
    NON_FIXED_VOIP = "NON_FIXED_VOIP"
    OTHER_VOIP = "OTHER_VOIP"
    TOLL_FREE = "TOLL_FREE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class LookupStatus(str, Enum):
    SUCCESS = "SUCCESS"
    CACHED = "CACHED"
    INVALID = "INVALID"
    FAILED = "FAILED"


_LINE_TYPE_MAP = {
    "mobile": Classification.MOBILE,
    "wireless": Classification.MOBILE,
    "cellular": Classification.MOBILE,
    "cell": Classification.MOBILE,
    "fixedline": Classification.LANDLINE,
    "landline": Classification.LANDLINE,
    "fixed": Classification.LANDLINE,
    "wireline": Classification.LANDLINE,
    "fixedvoip": Classification.FIXED_VOIP,
    "nonfixedvoip": Classification.NON_FIXED_VOIP,
    "voip": Classification.OTHER_VOIP,
    "othervoip": Classification.OTHER_VOIP,
    "tollfree": Classification.TOLL_FREE,
    "unknown": Classification.UNKNOWN,
    "fixedlineormobile": Classification.UNKNOWN,
}

PORTABILITY_FIELDS = (
    "ported_status", "ported_date", "line_type", "spid", "spid_carrier_name",
    "spid_carrier_type", "altspid", "altspid_carrier_name", "altspid_carrier_type", "ocn", "lrn",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class LookupResult:
    input: str
    e164: str | None
    status: str
    classification: str
    country: str | None = None
    carrier: str | None = None
    line_type_raw: str | None = None
    line_type_source: str | None = None
    ported_status: str | None = None
    ported_date: str | None = None
    portability: dict = field(default_factory=dict)
    error: str | None = None
    looked_up_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_line_type(raw: str | None) -> Classification:
    if raw is None:
        return Classification.UNKNOWN
    key = re.sub(r"[^a-z]", "", str(raw).lower())
    if not key:
        return Classification.UNKNOWN
    if key in _LINE_TYPE_MAP:
        return _LINE_TYPE_MAP[key]
    if "voip" in key:
        return Classification.OTHER_VOIP
    return Classification.OTHER


def invalid_result(raw: str, error: str, e164: str | None = None, country: str | None = None) -> LookupResult:
    return LookupResult(raw, e164, LookupStatus.INVALID.value, Classification.INVALID.value,
                        country=country, error=error)


def failed_result(raw: str, e164: str | None, error: str, country: str | None = None) -> LookupResult:
    return LookupResult(raw, e164, LookupStatus.FAILED.value, Classification.UNKNOWN.value,
                        country=country, error=error)


def _text(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def parse_lookup_response(payload, raw: str, e164: str, country: str | None = None) -> LookupResult:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return failed_result(raw, e164, "Malformed API response: missing data object", country)
    returned = _text(data.get("phone_number"))
    if returned and returned != e164:
        return failed_result(raw, e164, f"API returned a different number ({returned})", country)
    country = _text(data.get("country_code")) or country
    if data.get("valid_number") is False:
        return invalid_result(raw, "Telnyx reported the number as invalid", e164, country)

    carrier = data.get("carrier") if isinstance(data.get("carrier"), dict) else {}
    portability = data.get("portability") if isinstance(data.get("portability"), dict) else {}
    line_type, source = _pick_line_type(carrier, portability)
    port = {k: portability[k] for k in PORTABILITY_FIELDS if portability.get(k) not in (None, "")}
    carrier_name = (_text(carrier.get("name")) or _text(carrier.get("normalized_carrier"))
                    or _text(portability.get("spid_carrier_name")))
    return LookupResult(
        input=raw,
        e164=e164,
        status=LookupStatus.SUCCESS.value,
        classification=normalize_line_type(line_type).value,
        country=country,
        carrier=carrier_name,
        line_type_raw=line_type,
        line_type_source=source,
        ported_status=_text(portability.get("ported_status")),
        ported_date=_text(portability.get("ported_date")),
        portability=port,
        error=_carrier_error(carrier),
    )


def _carrier_error(carrier: dict) -> str | None:
    code = _text(carrier.get("error_code"))
    return f"Carrier error code {code}" if code else None


def _pick_line_type(carrier: dict, portability: dict) -> tuple[str | None, str | None]:
    value = _text(carrier.get("type"))
    if value:
        return value, "carrier.type"
    value = _text(portability.get("line_type"))
    if value:
        return value, "portability.line_type"
    return None, None
