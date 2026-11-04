import pytest

from classifier import (Classification, LookupStatus, normalize_line_type,
                        parse_lookup_response)
from tests.conftest import lookup_payload


@pytest.mark.parametrize("raw,expected", [
    ("mobile", Classification.MOBILE),
    ("Wireless", Classification.MOBILE),
    ("fixed line", Classification.LANDLINE),
    ("landline", Classification.LANDLINE),
    ("fixed voip", Classification.FIXED_VOIP),
    ("Fixed VoIP", Classification.FIXED_VOIP),
    ("non-fixed voip", Classification.NON_FIXED_VOIP),
    ("nonFixedVoip", Classification.NON_FIXED_VOIP),
    ("voip", Classification.OTHER_VOIP),
    ("interconnected voip", Classification.OTHER_VOIP),
    ("toll free", Classification.TOLL_FREE),
    ("premium rate", Classification.OTHER),
    ("pager", Classification.OTHER),
    ("fixed line or mobile", Classification.UNKNOWN),
    ("unknown", Classification.UNKNOWN),
    ("", Classification.UNKNOWN),
    (None, Classification.UNKNOWN),
])
def test_line_type_mapping(raw, expected):
    assert normalize_line_type(raw) == expected




def test_parse_successful_response():
    payload = lookup_payload("+16502530000", "voip", "Example VoIP",
                             portability={"ported_status": "Y", "ported_date": "2024-01-01",
                                          "city": "X", "state": "Y", "spid_carrier_name": "Old"})
    result = parse_lookup_response(payload, "650-253-0000", "+16502530000")
    assert result.status == LookupStatus.SUCCESS.value
    assert result.classification == "OTHER_VOIP"
    assert result.carrier == "Example VoIP"
    assert result.line_type_raw == "voip"
    assert result.line_type_source == "carrier.type"
    assert result.ported_status == "Y" and result.ported_date == "2024-01-01"
    assert "city" not in result.portability and "state" not in result.portability


def test_missing_line_type_is_unknown_not_inferred():
    payload = {"data": {"phone_number": "+16502530000", "country_code": "US", "carrier": {"name": "X"}}}
    result = parse_lookup_response(payload, "x", "+16502530000")
    assert result.status == "SUCCESS"
    assert result.classification == "UNKNOWN"
    assert result.line_type_raw is None


def test_portability_line_type_used_when_carrier_type_absent():
    payload = {"data": {"phone_number": "+16502530000", "carrier": {},
                        "portability": {"line_type": "landline"}}}
    result = parse_lookup_response(payload, "x", "+16502530000")
    assert result.classification == "LANDLINE"
    assert result.line_type_source == "portability.line_type"


def test_provider_invalid_number():
    result = parse_lookup_response(lookup_payload("+16502530000", valid=False), "x", "+16502530000")
    assert result.status == "INVALID" and result.classification == "INVALID"


@pytest.mark.parametrize("payload", [None, [], {}, {"data": None}, {"data": "oops"}])
def test_malformed_responses_fail(payload):
    result = parse_lookup_response(payload, "x", "+16502530000")
    assert result.status == "FAILED"
    assert "Malformed" in result.error


def test_mismatched_number_fails():
    result = parse_lookup_response(lookup_payload("+15555550100"), "x", "+16502530000")
    assert result.status == "FAILED"


DOCUMENTED_TYPES = {
    "fixed line": "LANDLINE", "mobile": "MOBILE", "voip": "OTHER_VOIP",
    "fixed line or mobile": "UNKNOWN", "toll free": "TOLL_FREE", "premium rate": "OTHER",
    "shared cost": "OTHER", "personal number": "OTHER", "pager": "OTHER", "uan": "OTHER",
    "voicemail": "OTHER", "unknown": "UNKNOWN",
}


@pytest.mark.parametrize("raw,expected", DOCUMENTED_TYPES.items())
def test_every_documented_telnyx_type_is_mapped(raw, expected):
    assert normalize_line_type(raw).value == expected


def test_documented_response_shape():
    payload = {"data": {
        "record_type": "number_lookup", "country_code": "US", "national_format": "(0312) 945-7420",
        "phone_number": "+13129457420", "fraud": None, "valid_number": True, "nnid_override": None,
        "carrier": {"mobile_country_code": "US", "mobile_network_code": "0866", "name": "Telnyx/4",
                    "type": "voip", "error_code": None, "normalized_carrier": "AT&T"},
        "portability": {"lrn": "2245701999", "ported_status": "", "ported_date": "", "ocn": "073H",
                        "line_type": "voip", "spid": "073H", "spid_carrier_name": "Telnyx/4",
                        "spid_carrier_type": "3", "altspid": "073H", "altspid_carrier_name": "Telnyx/4",
                        "altspid_carrier_type": "3", "city": "WAUKEGAN", "state": "Illinois"},
    }}
    result = parse_lookup_response(payload, "3129457420", "+13129457420")
    assert result.status == "SUCCESS" and result.classification == "OTHER_VOIP"
    assert result.carrier == "Telnyx/4" and result.country == "US"
    assert result.ported_status is None and result.error is None
    assert result.portability["lrn"] == "2245701999"
    assert "city" not in result.portability and "state" not in result.portability
