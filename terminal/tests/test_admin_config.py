import pytest

from admin_config import AdminConfig, validate_admin_setting
from database import Database


@pytest.fixture
def cfg():
    db = Database(":memory:")
    yield AdminConfig(db)
    db.close()


def test_defaults(cfg):
    assert cfg.fallback_provider() == "none"
    assert cfg.get("margin_receive_percent") == "110"
    assert cfg.get("margin_send_percent") == "200"
    assert cfg.send_enabled() is False


def test_receive_margin_110_percent(cfg):
    cfg.set("provider_cost_receive", "0.004")
    q = cfg.receive_quote()
    assert q.provider_cost == 0.004
    assert q.billable == pytest.approx(0.0084)     # 0.004 * (1 + 110/100)
    assert q.profit == pytest.approx(0.0044)
    assert q.currency == "USD"


def test_send_margin_200_percent_and_toggle(cfg):
    assert cfg.send_quote() is None                 # disabled by default
    cfg.set("sms_send_enabled", "true")
    cfg.set("provider_cost_send", "0.0075")
    q = cfg.send_quote()
    assert q.billable == pytest.approx(0.0225)      # 0.0075 * (1 + 200/100)
    assert q.margin_percent == 200


def test_margins_are_editable(cfg):
    cfg.set("provider_cost_receive", "0.01")
    cfg.set("margin_receive_percent", "150")
    assert cfg.receive_quote().billable == pytest.approx(0.025)


@pytest.mark.parametrize("key,value", [
    ("fallback_validation_provider", "sketchy"),
    ("sms_send_enabled", "maybe"),
    ("currency", "dollars"),
    ("provider_cost_receive", "-1"),
    ("margin_receive_percent", "abc"),
    ("unknown_key", "1"),
])
def test_validation_rejects_bad_values(key, value):
    with pytest.raises(ValueError):
        validate_admin_setting(key, value)


@pytest.mark.parametrize("provider", ["none", "twilio", "telnyx"])
def test_provider_choices_accepted(cfg, provider):
    assert cfg.set("fallback_validation_provider", provider) == provider
