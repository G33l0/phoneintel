import threading
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
    assert service.update_settings({"concurrency": "6", "bogus": "1"}) == {"concurrency": "6"}
    assert service.settings()["concurrency"] == "6"
    with pytest.raises(ValueError):
        service.update_settings({"concurrency": "500"})


def test_bulk_flow_from_background_thread(service, tmp_path):
    service.save_key(KEY)
    source = tmp_path / "in.csv"
    source.write_text("name,phone\nA,6502530000\nB,2125551234\nC,nope\nD,650 253 0000\n", encoding="utf-8")
    table, detected = service.load_table(source)
    assert detected == "phone"
    prepared, est = service.prepare(table, detected, str(source), False)
    assert est.to_lookup == 2 and est.invalid == 1 and est.duplicates == 1
    job_id = service.create_job(prepared, False)
    outcome = {}

    def worker():
        outcome["summary"] = service.run_job(job_id, progress=lambda *a: None, stop_event=threading.Event())

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(10)
    assert outcome["summary"].status == "completed"
    buckets = service.job_buckets(job_id)
    assert buckets["MOBILE"] == 2 and buckets["LANDLINE"] == 1 and buckets["INVALID"] == 1
    folder = Path(service.job(job_id)["export_dir"])
    assert (folder / "COMPLETE_RESULTS.xlsx").exists() and (folder / "MOBILE.csv").exists()
    path, count = service.export_bucket("MOBILE")
    assert count == 1 and path.exists()
    assert service.jobs()[0]["id"] == job_id


def test_stale_running_job_recovered_on_start(service, tmp_path):
    source = tmp_path / "in.txt"
    source.write_text("6502530000\n", encoding="utf-8")
    table, column = service.load_table(source)
    prepared, _ = service.prepare(table, column, str(source), False)
    job_id = service.create_job(prepared, False)
    from database import Database
    with Database(service.config.db_path) as db:
        db.update_job(job_id, status="running")
    restarted = services.PhoneIntelService(service.config.base_dir)
    assert restarted.resumable_jobs()[0]["id"] == job_id


def test_free_validation_offline_and_rate_limited(service):
    # free validation needs no API key
    assert not service.has_key()
    assert service.free_validations_remaining() == 2
    o1 = service.free_validate("(650) 253-0000")
    assert o1.allowed and o1.result.valid and o1.result.source == "offline" and o1.remaining == 1
    o2 = service.free_validate("+44 20 7946 0958")
    assert o2.allowed and o2.remaining == 0
    o3 = service.free_validate("212-555-1234")
    assert not o3.allowed and o3.result is None
    assert service.free_validations_remaining() == 0
