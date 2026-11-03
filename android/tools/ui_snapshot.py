"""Render every PHONEINTEL screen offline with mocked Telnyx responses and save screenshots.

Usage: xvfb-run -s "-screen 0 2400x2600x24" python tools/ui_snapshot.py OUT_DIR WIDTH_DP HEIGHT_DP DENSITY
"""
import os
import sys
import tempfile
from pathlib import Path

out_dir = Path(sys.argv[1]).resolve()
width_dp, height_dp, density = int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
os.environ["KIVY_METRICS_DENSITY"] = str(density)
os.environ["KIVY_NO_ARGS"] = "1"
os.environ.setdefault("KIVY_LOG_MODE", "PYTHON")
from kivy.config import Config  # noqa: E402

Config.set("graphics", "width", str(int(width_dp * density)))
Config.set("graphics", "height", str(int(height_dp * density)))
Config.set("graphics", "resizable", "0")

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
home = Path(tempfile.mkdtemp(prefix="pi_ui_"))
os.environ["PHONEINTEL_DOWNLOADS"] = str(home / "Downloads")
os.environ.pop("TELNYX_API_KEY", None)

import telnyx_client  # noqa: E402

LINES = {"+16502530000": "mobile", "+12125551234": "fixed line", "+13125550100": "voip",
         "+14155550123": "toll free", "+12025550123": "fixed line or mobile"}


def fake_lookup(self, e164):
    return {"data": {"phone_number": e164, "country_code": "US", "valid_number": True,
                     "carrier": {"name": "T-Mobile USA, Inc." if LINES.get(e164) == "mobile" else "Bandwidth/13",
                                 "type": LINES.get(e164, "mobile")},
                     "portability": {"ported_status": "Y", "ported_date": "2021-06-14", "line_type": LINES.get(e164, "mobile")}}}


telnyx_client.TelnyxClient.lookup = fake_lookup
telnyx_client.TelnyxClient.check_connection = lambda self: {"data": {"balance": "42.10", "currency": "USD"}}

import main as app_main  # noqa: E402
from sms_hosting import VerificationRequest as VReq  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402

sample = home / "contacts.csv"
sample.write_text("name,phone,city\nAlice,(650) 253-0000,MV\nBob,212-555-1234,NY\nCarol,bad,LA\n"
                  "Dan,+1 650 253 0000,SF\nEve,3125550100,CHI\nFay,4155550123,SF\nGus,2025550123,DC\n", encoding="utf-8")


class SnapshotApp(app_main.PhoneIntelApp):
    @property
    def user_data_dir(self):
        return str(home / "data")


app = SnapshotApp()
shots = []
errors = []
_toast = SnapshotApp.toast


def recording_toast(self, message, icon="info", duration=3.2):
    if icon == "error":
        errors.append(message)
    return _toast(self, message, icon, duration)


SnapshotApp.toast = recording_toast


def shot(name):
    def take(*_):
        path = out_dir / f"{name}.png"
        Window.screenshot(name=str(path))
        produced = sorted(out_dir.glob(f"{name}*.png"), key=os.path.getmtime)[-1]
        produced.rename(path)
        shots.append(path.name)
    return take


def seed_sms(*_):
    from hosting_db import HostingDB
    from sms_hosting import SMSHostingService
    req = app.hosting.request_hosting("(312) 555-0100")
    with HostingDB(app.hosting.db_path) as db:
        s = SMSHostingService(db)
        s.confirm_ownership(req.e164, req.code)
        s.ingest_inbound(req.e164, "+14155550199", "Your appointment is confirmed for 3pm tomorrow.")
        s.ingest_inbound(req.e164, "+18665551234", "Order #4821 has shipped. Reply STOP to opt out.")


def step_list():
    a = app
    sm = lambda: a.root.ids.sm  # noqa: E731
    steps = [
        (1.2, shot("01_home_empty")),
        (0.2, lambda *_: a.go("settings")),
        (0.8, shot("02_settings_nokey")),
        (0.1, lambda *_: setattr(sm().get_screen("settings").ids.key, "text", "KEY0123456789ABCDEFGHIJKLMNOP")),
        (0.2, lambda *_: sm().get_screen("settings").save_key()),
        (0.6, shot("03_settings_saved")),
        (0.1, lambda *_: sm().get_screen("settings").test_connection()),
        (0.8, shot("04_settings_tested")),
        (0.1, lambda *_: a.go("lookup")),
        (0.4, lambda *_: setattr(sm().get_screen("lookup").ids.number, "text", "(650) 253-0000")),
        (0.2, lambda *_: sm().get_screen("lookup").run_lookup()),
        (1.2, shot("05_lookup_result")),
        (0.1, lambda *_: setattr(sm().get_screen("lookup").ids.number, "text", "12345")),
        (0.2, lambda *_: sm().get_screen("lookup").run_lookup()),
        (1.0, shot("06_lookup_invalid")),
        (0.1, lambda *_: setattr(sm().get_screen("lookup").ids.number, "text", "+44 20 7946 0958")),
        (0.2, lambda *_: sm().get_screen("lookup").run_free()),
        (1.0, shot("06b_lookup_free")),
        (0.1, seed_sms),
        (0.2, lambda *_: a.go("sms")),
        (0.8, shot("06c_sms_numbers")),
        (0.1, lambda *_: sm().get_screen("sms").show_add()),
        (0.5, shot("06d_sms_add")),
        (0.1, lambda *_: sm().get_screen("sms").show_pending(
            VReq("+12025550123", "482913", "2026-01-01T00:00:00+00:00"))),
        (0.5, shot("06e_sms_verify")),
        (0.1, lambda *_: sm().get_screen("sms").open_inbox("+13125550100")),
        (0.8, shot("06f_sms_inbox")),
        (0.1, lambda *_: a.go("bulk")),
        (0.8, shot("07_bulk_idle")),
        (0.1, lambda *_: sm().get_screen("bulk").load(sample)),
        (1.0, shot("08_bulk_config")),
        (0.1, lambda *_: sm().get_screen("bulk").review(app_main.AppButton())),
        (1.0, shot("09_bulk_estimate")),
        (0.1, lambda *_: [w.dismiss() for w in list(Window.children) if hasattr(w, "dismiss")]),
        (0.3, lambda *_: sm().get_screen("bulk").start(False)),
        (2.5, shot("10_bulk_done")),
        (0.1, lambda *_: a.go("history")),
        (1.0, shot("11_history")),
        (0.1, lambda *_: sm().get_screen("history").open_detail(0)),
        (0.8, shot("12_history_detail")),
        (0.1, lambda *_: [w.dismiss() for w in list(Window.children) if hasattr(w, "dismiss")]),
        (0.3, lambda *_: a.go("home")),
        (1.2, shot("13_home_stats")),
        (0.1, lambda *_: a.go("settings")),
        (0.3, lambda *_: setattr(sm().get_screen("settings").fields["concurrency"], "text", "99")),
        (0.1, lambda *_: sm().get_screen("settings").save_settings()),
        (0.8, shot("14_settings_error")),
        (0.1, lambda *_: setattr(sm().get_screen("settings"), "reveal_account", True)),
        (0.1, lambda *_: setattr(sm().get_screen("settings").children[0], "scroll_y", 0.0)),
        (0.6, shot("15_settings_account")),
        (0.3, lambda *_: a.stop()),
    ]
    return steps


def run_steps(*_):
    delay = 0
    for wait, action in step_list():
        delay += wait
        Clock.schedule_once(action, delay)


Clock.schedule_once(run_steps, 0.5)
out_dir.mkdir(parents=True, exist_ok=True)
app.run()
print("SHOTS", shots)
expected = sum(1 for _wait, action in step_list() if getattr(action, "__name__", "") == "take")
if errors or len(shots) != expected:
    print(f"UI SNAPSHOT FAILED: {len(shots)}/{expected} screenshots, error toasts: {errors}")
    sys.exit(1)
print("UI SNAPSHOT OK")
