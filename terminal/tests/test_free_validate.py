import pytest

from database import Database
from engine import EngineSettings, PhoneIntelEngine
from free_validate import validate_offline


def make_engine(tmp_path):
    db = Database(tmp_path / "f.db")
    return PhoneIntelEngine(db, None, EngineSettings())


@pytest.mark.parametrize("raw,valid,cls", [
    ("(650) 253-0000", True, "UNKNOWN"),
    ("+44 20 7946 0958", True, "LANDLINE"),
    ("18005551234", True, "TOLL_FREE"),
    ("+2348031234567", True, "MOBILE"),
    ("312", False, None),
    ("", False, None),
    (None, False, None),
])
def test_offline_validation(raw, valid, cls):
    r = validate_offline(raw, "US")
    assert r.valid is valid
    assert r.source == "offline"
    if valid:
        assert r.e164 and r.classification_hint == cls
        assert "not a live carrier" in r.note.lower()
    else:
        assert r.e164 is None and r.error


def test_offline_never_hits_network(monkeypatch):
    import socket
    def boom(*a, **k):
        raise AssertionError("offline validation must not open a socket")
    monkeypatch.setattr(socket, "socket", boom)
    assert validate_offline("650-253-0000", "US").valid


def test_daily_limit_enforced(tmp_path):
    engine = make_engine(tmp_path)
    assert engine.free_validations_remaining() == 2
    o1 = engine.free_validate_rate_limited("650-253-0000")
    assert o1.allowed and o1.remaining == 1
    o2 = engine.free_validate_rate_limited("212-555-1234")
    assert o2.allowed and o2.remaining == 0
    o3 = engine.free_validate_rate_limited("312-555-0100")
    assert not o3.allowed and o3.result is None and "limit" in o3.message.lower()
    assert engine.free_validations_remaining() == 0


def test_blank_input_does_not_consume_quota(tmp_path):
    engine = make_engine(tmp_path)
    for _ in range(5):
        o = engine.free_validate_rate_limited("   ")
        assert o.allowed and o.result is not None and not o.result.valid
    assert engine.free_validations_remaining() == 2


def test_limit_is_per_utc_day(tmp_path):
    engine = make_engine(tmp_path)
    engine.free_validate_rate_limited("650-253-0000")
    engine.free_validate_rate_limited("650-253-0000")
    assert not engine.free_validate_rate_limited("650-253-0000").allowed
    # a different day has its own fresh allowance
    allowed, remaining = engine.db.try_consume_free_validation("2000-01-01", 2)
    assert allowed and remaining == 1


def test_consume_is_atomic_across_connections(tmp_path):
    """Each worker opens its own connection to the same DB file, like the Android service does."""
    import threading
    path = tmp_path / "shared.db"
    Database(path).close()
    day = "2026-11-03"
    results = []
    lock = threading.Lock()

    def worker():
        db = Database(path)
        try:
            for _ in range(20):
                allowed, _ = db.try_consume_free_validation(day, 2)
                if allowed:
                    with lock:
                        results.append(True)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 2
