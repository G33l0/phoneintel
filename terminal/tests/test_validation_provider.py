import pytest

import validation_provider as V


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.content = b"x"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.resp


def test_twilio_parses_line_type():
    resp = FakeResp(200, {"valid": True, "phone_number": "+13125550100",
                          "line_type_intelligence": {"type": "landline", "carrier_name": "AcmeTel"}})
    s = FakeSession(resp)
    r = V.lookup_twilio("+13125550100", "AC", "tok", session=s)
    assert r.valid and r.line_type == "landline" and r.classification_hint == "LANDLINE"
    assert r.carrier == "AcmeTel" and r.source == "twilio"
    assert s.calls[0][1]["auth"] == ("AC", "tok")


def test_twilio_mobile_hint():
    resp = FakeResp(200, {"valid": True, "phone_number": "+1",
                          "line_type_intelligence": {"type": "mobile"}})
    r = V.lookup_twilio("+1", "AC", "tok", session=FakeSession(resp))
    assert r.classification_hint == "MOBILE"


def test_twilio_not_found():
    r = V.lookup_twilio("+1", "AC", "tok", session=FakeSession(FakeResp(404)))
    assert not r.valid and r.classification_hint == "INVALID"


def test_twilio_error_raises():
    with pytest.raises(V.ProviderError):
        V.lookup_twilio("+1", "AC", "tok", session=FakeSession(FakeResp(500)))


def test_twilio_requires_credentials():
    with pytest.raises(V.ProviderError):
        V.lookup_twilio("+1", "", "", session=FakeSession(FakeResp(200)))


def test_telnyx_parses_carrier_type():
    resp = FakeResp(200, {"data": {"phone_number": "+13125550100", "valid_number": True,
                                   "carrier": {"type": "fixed line", "name": "Telco"}}})
    r = V.lookup_telnyx("+13125550100", "KEY", session=FakeSession(resp))
    assert r.valid and r.classification_hint == "LANDLINE" and r.carrier == "Telco"


def test_dispatch_none_raises():
    with pytest.raises(V.ProviderError):
        V.lookup("none", "+1", {})
