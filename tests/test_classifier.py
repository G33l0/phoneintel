import pytest

from classifier import (Classification, LookupStatus, export_bucket, normalize_line_type,
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


@pytest.mark.parametrize("status,classification,bucket", [
    ("SUCCESS", "MOBILE", "MOBILE"), ("SUCCESS", "LANDLINE", "LANDLINE"),
    ("SUCCESS", "FIXED_VOIP", "VOIP"), ("SUCCESS", "NON_FIXED_VOIP", "VOIP"),
    ("SUCCESS", "OTHER_VOIP", "VOIP"), ("SUCCESS", "TOLL_FREE", "OTHER"),
    ("SUCCESS", "OTHER", "OTHER"), ("SUCCESS", "UNKNOWN", "UNKNOWN"),
    ("INVALID", "INVALID", "INVALID"), ("FAILED", "UNKNOWN", "FAILED"),
])
def test_export_buckets(status, classification, bucket):
    assert export_bucket(status, classification) == bucket


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
