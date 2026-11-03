import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import Database  # noqa: E402
from engine import EngineSettings, PhoneIntelEngine  # noqa: E402


def lookup_payload(e164, line_type="mobile", carrier="Example Wireless", valid=True, portability=None):
    return {"data": {
        "phone_number": e164,
        "country_code": "US",
        "valid_number": valid,
        "carrier": {"name": carrier, "type": line_type, "error_code": None},
        "portability": portability if portability is not None else {
            "ported_status": "N", "line_type": line_type, "city": "SHOULD NOT BE STORED"},
    }}


class FakeClient:
    def __init__(self, responses=None, default="mobile", error=None):
        self.responses = responses or {}
        self.default = default
        self.error = error
        self.calls = []

    def lookup(self, e164):
        self.calls.append(e164)
        if self.error is not None:
            raise self.error
        value = self.responses.get(e164, self.default)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, dict):
            return value
        return lookup_payload(e164, value)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def make_engine(db):
    def factory(client=None, **settings):
        return PhoneIntelEngine(db, client if client is not None else FakeClient(),
                                EngineSettings(**settings))
    return factory
