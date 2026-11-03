from datetime import datetime, timedelta, timezone

from classifier import failed_result
from database import Database
from telnyx_client import APIError, AuthenticationError, NetworkError
from tests.conftest import FakeClient

import pytest


def test_single_lookup_persists_and_caches(make_engine, db):
    client = FakeClient(default="mobile")
    engine = make_engine(client)
    first = engine.lookup("(650) 253-0000")
    assert first.status == "SUCCESS" and first.classification == "MOBILE"
    second = engine.lookup("650 253 0000")
    assert second.status == "CACHED" and second.classification == "MOBILE"
    assert client.calls == ["+16502530000"]
    assert db.global_stats()["unique_numbers"] == 1


def test_force_refresh_bypasses_cache(make_engine):
    client = FakeClient()
    engine = make_engine(client)
    engine.lookup("6502530000")
    engine.lookup("6502530000", force=True)
    assert len(client.calls) == 2


def test_failed_lookups_never_cached(make_engine, db):
    client = FakeClient(error=NetworkError("down"))
    engine = make_engine(client)
    result = engine.lookup("6502530000")
    assert result.status == "FAILED" and "down" in result.error
    assert db.cached_result("+16502530000", 30) is None
    client.error = None
    assert engine.lookup("6502530000").status == "SUCCESS"
    assert len(client.calls) == 2


def test_api_error_becomes_failed_result(make_engine):
    engine = make_engine(FakeClient(error=APIError("Telnyx API error (422)", 422)))
    assert engine.lookup("6502530000").bucket == "FAILED"


def test_auth_error_propagates(make_engine):
    engine = make_engine(FakeClient(error=AuthenticationError("bad")))
    with pytest.raises(AuthenticationError):
        engine.lookup("6502530000")


def test_invalid_number_skips_api(make_engine):
    client = FakeClient()
    result = make_engine(client).lookup("12345")
    assert result.status == "INVALID" and client.calls == []


def test_cache_expiration(make_engine, db):
    engine = make_engine(FakeClient(), cache_days=30)
    engine.lookup("6502530000")
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
    db.conn.execute("UPDATE lookup_results SET looked_up_at = ?", (old,))
    db.conn.commit()
    assert db.cached_result("+16502530000", 30) is None
    assert db.cached_result("+16502530000", 60) is not None


def test_cache_disabled_with_zero_days(make_engine):
    client = FakeClient()
    engine = make_engine(client, cache_days=0)
    engine.lookup("6502530000")
    engine.lookup("6502530000")
    assert len(client.calls) == 2


def test_settings_persist_across_connections(tmp_path):
    path = tmp_path / "s.db"
    first = Database(path)
    assert first.get_setting("concurrency") == "4"
    first.set_setting("concurrency", "8")
    first.close()
    second = Database(path)
    assert second.get_setting("concurrency") == "8"
    second.close()


def test_results_persist_across_connections(tmp_path):
    path = tmp_path / "r.db"
    first = Database(path)
    first.save_result(failed_result("x", "+16502530000", "boom"))
    first.close()
    second = Database(path)
    assert second.recent_results()[0].error == "boom"
    second.close()


def test_schema_tables_exist(db):
    names = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"phone_numbers", "lookup_results", "bulk_jobs", "job_records", "job_statistics",
            "settings"} <= names


def test_latest_successful_ignores_failures(make_engine, db):
    engine = make_engine(FakeClient(default="landline"))
    engine.lookup("6502530000")
    db.save_result(failed_result("x", "+16502530000", "later failure"))
    latest = db.latest_successful(("LANDLINE",))
    assert [r.e164 for r in latest] == ["+16502530000"]
