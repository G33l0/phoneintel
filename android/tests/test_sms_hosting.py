from datetime import datetime, timedelta, timezone

import pytest

import hosting_db
import identity
import sms_hosting
from hosting_db import HostingDB
from sms_hosting import HostingError, SMSHostingService

ACC_A = identity.generate_account_id()
ACC_B = identity.generate_account_id()
NUMBER = "(312) 555-0100"
E164 = "+13125550100"


@pytest.fixture
def svc():
    db = HostingDB(":memory:")
    service = SMSHostingService(db)
    yield service
    db.close()


def verify(svc, account, raw=NUMBER):
    req = svc.request_hosting(account, raw)
    assert svc.confirm_ownership(req.e164, req.code) is True
    return req.e164


# ---- happy path

def test_full_ownership_and_inbox_flow(svc):
    req = svc.request_hosting(ACC_A, NUMBER)
    assert req.e164 == E164 and len(req.code) == 6 and req.code.isdigit()
    # not yet verified -> no messages stored
    assert svc.ingest_inbound(E164, "+14155550000", "before verify") is False
    assert svc.confirm_ownership(E164, req.code) is True
    assert svc.ingest_inbound(E164, "+14155550000", "Your code is 123456") is True
    inbox = svc.inbox(ACC_A, E164)
    assert len(inbox) == 1 and inbox[0]["body"] == "Your code is 123456"


# ---- the core gate: only the verified owner can read

def test_messages_never_leak_to_another_account(svc):
    verify(svc, ACC_A)
    svc.ingest_inbound(E164, "+1", "private message")
    assert svc.inbox(ACC_A, E164)            # owner sees it
    assert svc.inbox(ACC_B, E164) == []       # a different account sees nothing


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


# ---- takeover protection

def test_second_account_cannot_claim_pending_number(svc):
    svc.request_hosting(ACC_A, NUMBER)
    with pytest.raises(HostingError, match="another account"):
        svc.request_hosting(ACC_B, NUMBER)


def test_second_account_cannot_claim_verified_number(svc):
    verify(svc, ACC_A)
    with pytest.raises(HostingError, match="another account"):
        svc.request_hosting(ACC_B, NUMBER)


def test_attacker_cannot_verify_without_code(svc):
    svc.request_hosting(ACC_A, NUMBER)
    with pytest.raises(HostingError, match="does not match"):
        svc.confirm_ownership(E164, "000000")
    assert svc.db.get_number(E164)["status"] == hosting_db.PENDING


# ---- code robustness

def test_wrong_code_locks_out_after_max_attempts(svc):
    req = svc.request_hosting(ACC_A, NUMBER)
    for _ in range(sms_hosting.MAX_ATTEMPTS):
        with pytest.raises(HostingError):
            svc.confirm_ownership(E164, "999999")
    # verification cleared; even the right code now fails until re-requested
    with pytest.raises(HostingError, match="No pending verification|Too many"):
        svc.confirm_ownership(E164, req.code)


def test_expired_code_rejected(svc):
    req = svc.request_hosting(ACC_A, NUMBER)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    svc.db.conn.execute("UPDATE verifications SET expires_at = ? WHERE e164 = ?", (past, E164))
    svc.db.conn.commit()
    with pytest.raises(HostingError, match="expired"):
        svc.confirm_ownership(E164, req.code)


def test_code_for_one_number_does_not_verify_another(svc):
    req = svc.request_hosting(ACC_A, NUMBER)
    svc.request_hosting(ACC_A, "+12025550123")
    with pytest.raises(HostingError, match="does not match"):
        svc.confirm_ownership("+12025550123", req.code)


# ---- secrets at rest

def test_code_and_account_stored_only_as_hashes(svc):
    req = svc.request_hosting(ACC_A, NUMBER)
    ver = svc.db.get_verification(E164)
    assert req.code not in ver["code_hash"] and len(ver["code_hash"]) == 64
    acct = svc.db.conn.execute("SELECT id_hash FROM accounts").fetchone()["id_hash"]
    assert ACC_A not in acct and len(acct) == 64


def test_invalid_number_rejected(svc):
    with pytest.raises(HostingError):
        svc.request_hosting(ACC_A, "12345")


def test_enable_hosting_requires_verification(svc):
    svc.request_hosting(ACC_A, NUMBER)
    with pytest.raises(HostingError, match="verified"):
        svc.enable_hosting(E164)


def test_enable_hosting_calls_messaging_client_when_present(svc):
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


def test_released_number_is_fully_removed_and_reclaimable(svc):
    verify(svc, ACC_A)
    svc.ingest_inbound(E164, "+1", "secret")
    assert svc.release(ACC_A, E164) is True
    # messages are gone from storage, not just hidden
    assert svc.db.conn.execute("SELECT COUNT(*) AS n FROM messages WHERE e164 = ?", (E164,)).fetchone()["n"] == 0
    assert svc.db.get_number(E164) is None
    # a different account can now claim the freed number
    req = svc.request_hosting(ACC_B, NUMBER)
    assert svc.confirm_ownership(req.e164, req.code) is True
    # and does not inherit the previous owner's messages
    assert svc.inbox(ACC_B, E164) == []


def test_release_requires_ownership(svc):
    verify(svc, ACC_A)
    assert svc.release(ACC_B, E164) is False      # not the owner
    assert svc.db.get_number(E164) is not None      # still there
