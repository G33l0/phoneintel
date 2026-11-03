import pytest

import engine as E
import validation_provider as V
from admin_config import AdminConfig
from database import Database
from engine import EngineSettings, PhoneIntelEngine


@pytest.fixture
def engine():
    db = Database(":memory:")
    return PhoneIntelEngine(db, None, EngineSettings())


def test_offline_healthy_does_not_use_provider(engine, monkeypatch):
    def fail(*a, **k):
        raise AssertionError("provider must not be called when offline works")
    monkeypatch.setattr(V, "lookup", fail)
    result = engine.free_validate("(650) 253-0000")
    assert result.valid and result.source == "offline"


def test_offline_failure_without_provider_reports_unavailable(engine, monkeypatch):
    monkeypatch.setattr(E, "validate_offline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    result = engine.free_validate("(650) 253-0000")
    assert not result.valid and "unavailable" in result.error.lower()


def test_offline_failure_uses_configured_provider(engine, monkeypatch):
    monkeypatch.setattr(E, "validate_offline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    AdminConfig(engine.db).set("fallback_validation_provider", "twilio")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setattr(V, "lookup",
                        lambda *a, **k: V.ProviderResult(True, "+16502530000", "landline",
                                                         "LANDLINE", "AcmeTel", "twilio"))
    result = engine.free_validate("(650) 253-0000")
    assert result.valid and result.classification_hint == "LANDLINE"
    assert result.source == "provider:twilio" and "billable" in result.note.lower()


def test_provider_error_falls_through_to_unavailable(engine, monkeypatch):
    monkeypatch.setattr(E, "validate_offline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    AdminConfig(engine.db).set("fallback_validation_provider", "telnyx")
    monkeypatch.setenv("TELNYX_API_KEY", "KEY")
    monkeypatch.setattr(V, "lookup", lambda *a, **k: (_ for _ in ()).throw(V.ProviderError("boom")))
    result = engine.free_validate("(650) 253-0000")
    assert not result.valid and "unavailable" in result.error.lower()


def test_rate_limit_still_applies_with_fallback(engine):
    from config import FREE_VALIDATION_DAILY_LIMIT
    for _ in range(FREE_VALIDATION_DAILY_LIMIT):
        assert engine.free_validate_rate_limited("650-253-0000").allowed
    assert not engine.free_validate_rate_limited("650-253-0000").allowed
