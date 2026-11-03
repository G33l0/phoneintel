import io
import re

import pytest
from rich.console import Console

from config import AppConfig, is_plausible_key, mask_key, validate_setting
from interface import App, THEME

KEY = "KEY0123456789ABCDEFGHIJKLMNOP_secret"


def test_mask_key_never_reveals_full_key():
    masked = mask_key(KEY)
    assert KEY not in masked and masked.startswith("KEY0") and masked.endswith("cret")
    assert mask_key(None) == "not configured"


def test_save_and_remove_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TELNYX_API_KEY", raising=False)
    config = AppConfig(tmp_path)
    assert config.api_key() is None
    config.save_api_key(KEY)
    monkeypatch.delenv("TELNYX_API_KEY", raising=False)
    assert config.api_key() == KEY
    assert "TELNYX_API_KEY=" in config.env_path.read_text()
    config.remove_api_key()
    assert config.api_key() is None


def test_rejects_implausible_key(tmp_path):
    assert not is_plausible_key("short")
    with pytest.raises(ValueError):
        AppConfig(tmp_path).save_api_key("has spaces in it but long enough")


@pytest.mark.parametrize("name,value,expected", [
    ("concurrency", "8", "8"), ("requests_per_second", "2.5", "2.5"), ("default_region", "gb", "GB"),
])
def test_validate_setting(name, value, expected):
    assert validate_setting(name, value) == expected


@pytest.mark.parametrize("name,value", [("concurrency", "0"), ("concurrency", "1.5"),
                                        ("default_region", "USA"), ("unknown", "1"),
                                        ("requests_per_second", "x")])
def test_validate_setting_rejects(name, value):
    with pytest.raises(ValueError):
        validate_setting(name, value)


def make_app(tmp_path, monkeypatch, inputs, width=100):
    monkeypatch.delenv("TELNYX_API_KEY", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(inputs))
    buffer = io.StringIO()
    console = Console(file=buffer, theme=THEME, width=width, force_terminal=False, color_system=None)
    return App(AppConfig(tmp_path), console), buffer


@pytest.mark.parametrize("width", [100, 50])
def test_first_screen_is_menu_and_exit_works(tmp_path, monkeypatch, width):
    app, buffer = make_app(tmp_path, monkeypatch, "12\n", width)
    app.run()
    output = buffer.getvalue()
    assert "MAIN MENU" in output
    for label in ("Single Phone Number Lookup", "Telnyx API Configuration", "Exit"):
        assert label in output


def test_menu_options_without_key_are_safe(tmp_path, monkeypatch):
    inputs = "1\n\n2\n\n10\n\n4\n\n5\n\n6\n\n7\n\n8\n\n11\n\n3\n1\n\n12\n"
    app, buffer = make_app(tmp_path, monkeypatch, inputs)
    app.run()
    output = buffer.getvalue()
    assert output.count("No Telnyx API key configured") == 3
    assert "Exported 0 unique mobile" in output
    assert "PROCESSING STATISTICS" in output and "APPLICATION INFORMATION" in output
    assert len(list((tmp_path / "exports").glob("*.csv"))) == 4


def test_configure_setting_via_menu(tmp_path, monkeypatch):
    app, buffer = make_app(tmp_path, monkeypatch, "9\n2\n7\n\n0\n\n12\n")
    app.run()
    assert app.config.db_path.exists()
    from database import Database
    db = Database(app.config.db_path)
    assert db.get_setting("concurrency") == "7"
    db.close()


class _Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.headers = {}
        self.reason = "x"

    def json(self):
        return self._payload


def _fake_get(self, url, params=None, headers=None, timeout=None):
    from urllib.parse import unquote
    if url.endswith("/balance"):
        return _Response(200, {"data": {"balance": "12.50", "currency": "USD"}})
    e164 = unquote(url.rsplit("/", 1)[1])
    line = {"+16502530000": "mobile", "+12125551234": "fixed line"}.get(e164, "voip")
    return _Response(200, {"data": {"phone_number": e164, "country_code": "US", "valid_number": True,
                                    "carrier": {"name": "Carrier X", "type": line},
                                    "portability": {"ported_status": "N"}}})


def test_end_to_end_with_mocked_http(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session, "get", _fake_get)
    source = tmp_path / "numbers.csv"
    source.write_text("name,phone\nA,6502530000\nB,2125551234\nC,bad\nD,650-253-0000\n", encoding="utf-8")
    inputs = (f"10\n\n1\n6502530000\n\n2\n{source}\n2\nn\ny\n\n4\n\n12\n")
    app, buffer = make_app(tmp_path, monkeypatch, inputs)
    app.config.save_api_key(KEY)
    app.run()
    output = buffer.getvalue()
    assert KEY not in output
    assert "ACCEPTED" in output and "12.50" in output
    assert "LOOKUP RESULT" in output and "MOBILE" in output and "Carrier X" in output
    assert "JOB ESTIMATE" in output and re.search(r"API lookups required\s+1\s", output)
    assert "Exported 1 unique mobile" in output
    folders = list((tmp_path / "exports").glob("job_*"))
    assert len(folders) == 1 and (folders[0] / "COMPLETE_RESULTS.xlsx").exists()
