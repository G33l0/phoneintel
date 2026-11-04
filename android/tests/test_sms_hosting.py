import pytest

import hosting_db
import identity
from hosting_db import HostingDB
from sms_hosting import HostingError, SMSHostingService

ACC_A = identity.generate_account_id()
ACC_B = identity.generate_account_id()
NUMBER = "(312) 555-0100"
E164 = "+13125550100"
LOA = "LOA-2026-00042"


@pytest.fixture
def svc():
    db = HostingDB(":memory:")
    service = SMSHostingService(db)
    yield service
    db.close()


def verify(svc, account, raw=NUMBER, loa=LOA):
    req = svc.request_hosting(account, raw)
    assert svc.verify_ownership(req.e164, loa) is True
    return req.e164


# ---- happy path

def test_request_verify_inbox_flow(svc):
    req = svc.request_hosting(ACC_A, NUMBER)
    assert req.e164 == E164 and req.status == hosting_db.PENDING
    # not verified yet -> inbound dropped
    assert svc.ingest_inbound(E164, "+14155550000", "before verify") is False
    assert svc.verify_ownership(E164, LOA) is True
    assert svc.ingest_inbound(E164, "+14155550000", "Appointment confirmed") is True
    inbox = svc.inbox(ACC_A, E164)
    assert len(inbox) == 1 and inbox[0]["body"] == "Appointment confirmed"
    number = svc.db.get_number(E164)
    assert number["loa_reference"] == LOA and number["verified_at"]


# ---- the core gate

def test_messages_never_leak_to_another_account(svc):
    verify(svc, ACC_A)
    svc.ingest_inbound(E164, "+1", "private message")
    assert svc.inbox(ACC_A, E164)
    assert svc.inbox(ACC_B, E164) == []


def test_inbound_dropped_until_verified(svc):
    svc.request_hosting(ACC_A, NUMBER)
    assert svc.ingest_inbound(E164, "+1", "hi") is False
    assert svc.inbox(ACC_A, E164) == []


def test_messages_hidden_after_release(svc):
    verify(svc, ACC_A)
    svc.ingest_inbound(E164, "+1", "msg")
    assert svc.inbox(ACC_A, E164)
    assert svc.release(ACC_A, E164) is True
    assert svc.inbox(ACC_A, E164) == []


# ---- verification is operator-only and auditable

def test_user_facade_cannot_self_verify():
    # the app-facing facade must not expose verification
    from hosting_service import HostingService
    assert not hasattr(HostingService, "verify_ownership")


def test_verify_requires_loa_reference(svc):
    svc.request_hosting(ACC_A, NUMBER)
    with pytest.raises(HostingError, match="LOA reference is required"):
        svc.verify_ownership(E164, "")
    assert svc.db.get_number(E164)["status"] == hosting_db.PENDING


def test_verify_unknown_number_rejected(svc):
    with pytest.raises(HostingError, match="No hosting request"):
        svc.verify_ownership("+12025550123", LOA)


def test_verify_records_operator(svc):
    svc.request_hosting(ACC_A, NUMBER)
    svc.verify_ownership(E164, LOA, verified_by="alice")
    assert svc.db.get_number(E164)["verified_by"] == "alice"


# ---- takeover protection

def test_second_account_cannot_claim_pending_number(svc):
    svc.request_hosting(ACC_A, NUMBER)
    with pytest.raises(HostingError, match="another account"):
        svc.request_hosting(ACC_B, NUMBER)


def test_second_account_cannot_claim_verified_number(svc):
    verify(svc, ACC_A)
    with pytest.raises(HostingError, match="another account"):
        svc.request_hosting(ACC_B, NUMBER)


def test_released_number_is_reclaimable_without_old_messages(svc):
    verify(svc, ACC_A)
    svc.ingest_inbound(E164, "+1", "secret")
    assert svc.release(ACC_A, E164) is True
    assert svc.db.conn.execute("SELECT COUNT(*) AS n FROM messages WHERE e164 = ?", (E164,)).fetchone()["n"] == 0
    assert svc.db.get_number(E164) is None
    newe = verify(svc, ACC_B)
    assert svc.inbox(ACC_B, newe) == []


def test_release_requires_ownership(svc):
    verify(svc, ACC_A)
    assert svc.release(ACC_B, E164) is False
    assert svc.db.get_number(E164) is not None


# ---- misc

def test_invalid_number_rejected(svc):
    with pytest.raises(HostingError):
        svc.request_hosting(ACC_A, "12345")


def test_request_is_idempotent_for_same_account(svc):
    r1 = svc.request_hosting(ACC_A, NUMBER)
    r2 = svc.request_hosting(ACC_A, NUMBER)
    assert r1.e164 == r2.e164
    assert svc.db.conn.execute("SELECT COUNT(*) AS n FROM hosted_numbers").fetchone()["n"] == 1


def test_enable_hosting_requires_verification(svc):
    svc.request_hosting(ACC_A, NUMBER)
    with pytest.raises(HostingError, match="verified"):
        svc.enable_hosting(E164)


def test_enable_hosting_calls_messaging_client(svc):
    calls = []

    class FakeMessaging:
        def enable_messaging(self, e164):
            calls.append(e164)
            return {"data": {"phone_number": e164, "status": "hosted"}}

    svc.messaging = FakeMessaging()
    verify(svc, ACC_A)
    out = svc.enable_hosting(E164)
    assert calls == [E164] and out["data"]["status"] == "hosted"
    assert svc.db.get_number(E164)["status"] == hosting_db.ACTIVE
