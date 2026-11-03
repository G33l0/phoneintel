import os

import pytest

import identity
from hosting_db import HostingDB
from hosting_service import HostingService
from sms_hosting import SMSHostingService


@pytest.fixture
def host(tmp_path):
    return HostingService(tmp_path / "acct")


def operator_confirm(host, e164, code):
    with HostingDB(host.db_path) as db:
        return SMSHostingService(db).confirm_ownership(e164, code)


def test_account_id_is_18_digits_stable_and_private(host):
    aid = host.account_id()
    assert identity.is_well_formed(aid)
    assert host.account_id() == aid  # stable across calls
    if os.name == "posix":
        assert oct(os.stat(host.id_path).st_mode & 0o777) == "0o600"
    # the raw id is on device, but the hosting DB only stores its hash
    with HostingDB(host.db_path) as db:
        stored = db.conn.execute("SELECT id_hash FROM accounts").fetchone()["id_hash"]
    assert aid not in stored


def test_request_verify_inbox_roundtrip(host):
    req = host.request_hosting("(312) 555-0100")
    assert host.inbox(req.e164) == []            # nothing before verification
    operator_confirm(host, req.e164, req.code)
    with HostingDB(host.db_path) as db:
        SMSHostingService(db).ingest_inbound(req.e164, "+1", "hi there")
    assert [m["body"] for m in host.inbox(req.e164)] == ["hi there"]
    assert host.total_unread() == 1
    host.mark_read(req.e164)
    assert host.total_unread() == 0


def test_release_removes_access(host):
    req = host.request_hosting("(312) 555-0100")
    operator_confirm(host, req.e164, req.code)
    with HostingDB(host.db_path) as db:
        SMSHostingService(db).ingest_inbound(req.e164, "+1", "hi")
    assert host.release(req.e164) is True
    assert host.inbox(req.e164) == []


def test_user_facade_has_no_confirm_method(host):
    # the app user must not be able to self-verify; that is operator-only
    assert not hasattr(host, "confirm_ownership")


def test_two_accounts_on_one_backend_cannot_share_a_number(tmp_path):
    # simulate two accounts against one shared backend database
    a = HostingService(tmp_path / "a")
    b = HostingService(tmp_path / "b")
    b.db_path = a.db_path
    assert a.account_id() != b.account_id()
    a.request_hosting("+13125550100")
    with pytest.raises(Exception, match="another account"):
        b.request_hosting("+13125550100")
