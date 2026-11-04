from pathlib import Path

import pytest

import services
import telnyx_client
from conftest import lookup_payload

KEY = "KEY0123456789ABCDEFGHIJKLMNOP_android"


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.delenv("TELNYX_API_KEY", raising=False)
    calls = []

    def fake_lookup(self, e164):
        calls.append(e164)
        return lookup_payload(e164, "fixed line" if e164.endswith("1234") else "mobile")

    monkeypatch.setattr(telnyx_client.TelnyxClient, "lookup", fake_lookup)
    monkeypatch.setattr(telnyx_client.TelnyxClient, "check_connection", lambda self: {"data": {"balance": "1"}})
    svc = services.PhoneIntelService(tmp_path / "data")
    svc.calls = calls
    return svc


def test_requires_key(service):
    assert not service.has_key()
    with pytest.raises(ValueError):
        service.lookup("6502530000")
    with pytest.raises(ValueError):
        service.test_connection()


def test_key_lifecycle_and_masking(service):
    service.save_key(KEY)
    assert service.has_key() and KEY not in service.masked_key()
    assert service.test_connection()["data"]["balance"] == "1"
    service.remove_key()
    assert not service.has_key()


def test_lookup_cache_and_stats(service):
    service.save_key(KEY)
    assert service.lookup("650-253-0000").classification == "MOBILE"
    assert service.is_cached("6502530000")
    assert service.lookup("6502530000").status == "CACHED"
    assert service.lookup("6502530000", force=True).status == "SUCCESS"
    assert len(service.calls) == 2
    assert service.stats()["unique_numbers"] == 1
    assert service.recent(10, "650")[0].e164 == "+16502530000"


def test_settings_validation(service):
    assert service.update_settings({"max_retries": "6", "bogus": "1"}) == {"max_retries": "6"}
    assert service.settings()["max_retries"] == "6"
    with pytest.raises(ValueError):
        service.update_settings({"max_retries": "500"})


def test_free_validation_offline_and_rate_limited(service):
    # free validation needs no API key
    assert not service.has_key()
    from config import FREE_VALIDATION_DAILY_LIMIT
    limit = FREE_VALIDATION_DAILY_LIMIT
    assert service.free_validations_remaining() == limit
    o1 = service.free_validate("(650) 253-0000")
    assert o1.allowed and o1.result.valid and o1.result.source == "offline" and o1.remaining == limit - 1
    for _ in range(limit - 1):
        service.free_validate("+44 20 7946 0958")
    blocked = service.free_validate("212-555-1234")
    assert not blocked.allowed and blocked.result is None
    assert service.free_validations_remaining() == 0
