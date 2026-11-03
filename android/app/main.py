import os
import sys
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)

from kivy.app import App  # noqa: E402
from kivy.clock import Clock, mainthread  # noqa: E402
from kivy.core.clipboard import Clipboard  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.factory import Factory  # noqa: E402
from kivy.metrics import dp, sp  # noqa: E402
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty  # noqa: E402
from kivy.uix.behaviors import ButtonBehavior  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.floatlayout import FloatLayout  # noqa: E402
from kivy.uix.recycleview.views import RecycleDataViewBehavior  # noqa: E402
from kivy.uix.screenmanager import FadeTransition, Screen  # noqa: E402

import theme  # noqa: E402
from android_bridge import IS_ANDROID, AndroidBridge  # noqa: E402
from hosting_service import HostingService  # noqa: E402
from sms_hosting import HostingError, HostingRequest  # noqa: E402
from config import APP_VERSION, DEFAULT_SETTINGS, SETTING_DESCRIPTIONS, is_plausible_key  # noqa: E402
from services import PhoneIntelService  # noqa: E402
from telnyx_client import AuthenticationError, TelnyxError  # noqa: E402
from theme import CLASS_COLORS, STATUS_COLORS, T  # noqa: E402
from widgets import (AppButton, BarRow, Card, Dialog, Field, KVRow, Pressable, SectionTitle,  # noqa: E402
                     StatTile, Text)

theme.register_fonts()
Factory.register("Pressable", cls=Pressable)

PAGE_INFO = {
    "home": ("PHONEINTEL", "business messages on the go"),
    "lookup": ("Lookup", "carrier & line type"),
    "history": ("History", "previous lookups"),
    "sms": ("Business SMS", "receive texts for a line you own"),
    "settings": ("Settings", "api key & engine"),
}
SETTING_LABELS = {
    "default_region": "Default region", "concurrency": "Parallel workers",
    "requests_per_second": "Requests / second", "max_retries": "Max retries",
    "request_timeout": "Timeout (s)", "cache_days": "Cache days", "batch_size": "Batch size",
    "cost_per_lookup": "Cost / lookup (USD)",
}


def background(task, on_done=None, on_error=None):
    def runner():
        try:
            result = task()
        except Exception as exc:  # surfaced to the UI
            if on_error:
                Clock.schedule_once(lambda *_: on_error(exc))
            return
        if on_done:
            Clock.schedule_once(lambda *_: on_done(result))

    threading.Thread(target=runner, daemon=True).start()


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, AuthenticationError):
        return "Telnyx rejected the API key. Check it in Settings."
    if isinstance(exc, TelnyxError):
        return str(exc)
    return str(exc) or exc.__class__.__name__


def fmt_time(value: str | None) -> str:
    return (value or "")[:16].replace("T", " ")


def result_rows(result) -> list[tuple[str, str, tuple, bool]]:
    if result.status == "INVALID" and not result.carrier:
        return [
            ("Phone number", result.e164 or "-", T.text, True),
            ("Input", result.input or "-", T.text, True),
            ("Classification", "INVALID", T.danger, True),
            ("Reason", result.error or "Not a valid phone number", T.warn, False),
            ("API cost", "None - not sent to Telnyx", T.muted, False),
            ("Checked", fmt_time(result.looked_up_at) + " UTC", T.text, True),
        ]
    port = {"Y": "Ported", "N": "Not ported"}.get(result.ported_status or "", "Not provided")
    rows = [
        ("Phone number", result.e164 or "-", T.text, True),
        ("Input", result.input or "-", T.text, True),
        ("Country", result.country or "-", T.text, False),
        ("Carrier", result.carrier or "Not provided", T.text, False),
        ("Provider line type", result.line_type_raw or "Not provided", T.text, False),
        ("Classification", result.classification.replace("_", " "), CLASS_COLORS.get(result.classification, T.text), True),
        ("Portability", port, T.text, False),
    ]
    if result.ported_date:
        rows.append(("Ported on", result.ported_date, T.text, True))
    if result.line_type_source:
        rows.append(("Line type source", result.line_type_source, T.muted, True))
    rows.append(("Status", result.status, STATUS_COLORS.get(result.status, T.text), True))
    rows.append(("Looked up", fmt_time(result.looked_up_at) + " UTC", T.text, True))
    if result.error:
        rows.append(("Notes", result.error, T.warn, False))
    return rows


def fill_rows(container, rows) -> None:
    container.clear_widgets()
    for key, value, tone, mono in rows:
        container.add_widget(KVRow(key=key, value=str(value), tone=tone, mono=mono))


class ResultCard(Card):
    number = StringProperty("")
    classification = StringProperty("UNKNOWN")

    def show(self, result):
        self.number = result.e164 or result.input or "-"
        self.classification = result.classification
        fill_rows(self.ids.rows, result_rows(result)[1:])


class FreeResultCard(Card):
    number = StringProperty("")
    classification = StringProperty("UNKNOWN")

    def show(self, result, remaining):
        self.number = result.e164 or result.input or "-"
        self.classification = result.classification_hint or ("INVALID" if not result.valid else "UNKNOWN")
        if result.valid:
            rows = [
                ("Phone number", result.e164 or "-", T.text, True),
                ("Valid", "Yes", T.accent, True),
                ("Country", result.country or "-", T.text, False),
                ("Area / region", result.region or "-", T.text, False),
                ("National format", result.national_format or "-", T.text, True),
                ("Line type (estimate)", result.line_type_hint or "Unknown", T.text, False),
            ]
        else:
            rows = [
                ("Input", result.input or "-", T.text, True),
                ("Valid", "No", T.danger, True),
                ("Reason", result.error or "Invalid number", T.warn, False),
            ]
        rows.append(("Source", "Offline estimate - not a carrier lookup", T.muted, False))
        rows.append(("Free checks left today", str(remaining), T.muted, True))
        fill_rows(self.ids.rows, rows)


class HistoryRow(RecycleDataViewBehavior, ButtonBehavior, BoxLayout):
    number = StringProperty("")
    meta = StringProperty("")
    classification = StringProperty("UNKNOWN")
    index = NumericProperty(0)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super().refresh_view_attrs(rv, index, data)

    def on_release(self):
        App.get_running_app().root.ids.sm.get_screen("history").open_detail(self.index)


class BaseScreen(Screen):
    @property
    def app(self):
        return App.get_running_app()

    def on_enter(self, *_):
        self.refresh()

    def refresh(self):
        pass


class HomeScreen(BaseScreen):
    def refresh(self):
        background(self.app.service.stats, self._render, lambda e: self.app.toast(friendly_error(e), "error"))

    def _render(self, stats):
        grid = self.ids.stats
        grid.clear_widgets()
        tiles = [
            ("smartphone", stats["unique_numbers"], "Numbers stored", T.accent),
            ("search", stats["lookups_total"], "Lookups", T.info),
        ]
        for icon, value, caption, tone in tiles:
            grid.add_widget(StatTile(icon=icon, value=f"{value:,}", caption=caption, tone=tone))
        card = self.ids.breakdown
        card.clear_widgets()
        counts = stats["by_classification"]
        total = sum(counts.values())
        if not total:
            card.add_widget(Text(role="caption", text="No classified numbers yet. Your line-type mix appears here after the first lookup."))
            return
        for name, count in sorted(counts.items(), key=lambda item: -item[1]):
            card.add_widget(BarRow(title=name, count=count, fraction=count / total,
                                   tone=CLASS_COLORS.get(name, T.muted)))


class LookupScreen(BaseScreen):
    def paste(self):
        text = (Clipboard.paste() or "").strip()
        if text:
            self.ids.number.text = text[:40]

    def run_lookup(self):
        raw = self.ids.number.text.strip()
        if not raw:
            self.ids.number.error = "Enter a phone number"
            return
        if not self.app.key_ok:
            self.app.toast("Add your Telnyx API key first", "warning")
            self.app.go("settings")
            return
        self.ids.number.ids.inp.focus = False
        self.ids.go.busy = True
        force = self.ids.force.active
        background(lambda: self.app.service.lookup(raw, force=force), self._done, self._failed)

    def _done(self, result):
        self.ids.go.busy = False
        holder = self.ids.result_holder
        holder.clear_widgets()
        card = ResultCard()
        card.show(result)
        holder.add_widget(card)
        if result.status == "INVALID":
            self.ids.number.error = result.error or "Invalid number"
        elif result.status == "FAILED":
            self.app.toast(result.error or "Lookup failed", "error")
        elif result.status == "CACHED":
            self.app.toast("Served from cache. Enable 'Force fresh lookup' to re-query.", "info")
        Clock.schedule_once(lambda *_: self._scroll_to(card), 0.1)

    def _scroll_to(self, widget):
        scroll = self.ids.page.parent
        if widget.parent:
            scroll.scroll_to(widget, padding=dp(12), animate=True)

    def _failed(self, exc):
        self.ids.go.busy = False
        self.app.toast(friendly_error(exc), "error")

    def on_enter(self, *_):
        self.refresh_free()

    def refresh_free(self):
        background(self.app.service.free_validations_remaining, self._set_free_remaining)

    @mainthread
    def _set_free_remaining(self, remaining):
        self.ids.free_btn.text = f"Free check  -  {remaining} left"
        self.ids.free_btn.disabled = remaining <= 0

    def run_free(self):
        raw = self.ids.number.text.strip()
        if not raw:
            self.ids.number.error = "Enter a phone number"
            return
        self.ids.number.ids.inp.focus = False
        self.ids.free_btn.busy = True
        background(lambda: self.app.service.free_validate(raw), self._free_done, self._failed_free)

    def _failed_free(self, exc):
        self.ids.free_btn.busy = False
        self.app.toast(friendly_error(exc), "error")

    def _free_done(self, outcome):
        self.ids.free_btn.busy = False
        self.refresh_free()
        if not outcome.allowed:
            self.app.toast(outcome.message or "Daily free limit reached", "warning", 4.5)
            return
        result = outcome.result
        holder = self.ids.result_holder
        holder.clear_widgets()
        card = FreeResultCard()
        card.show(result, outcome.remaining)
        holder.add_widget(card)
        if not result.valid:
            self.ids.number.error = result.error or "Invalid number"
        Clock.schedule_once(lambda *_: self._scroll_to(card), 0.1)


class HistoryScreen(BaseScreen):
    _event = None

    def refresh(self):
        search = self.ids.search.text.strip()

        def done(results):
            self.results = results
            self.ids.rv.data = [{
                "number": r.e164 or r.input or "-",
                "meta": "  |  ".join(x for x in (fmt_time(r.looked_up_at)[5:], r.carrier or r.error or r.status) if x),
                "classification": "FAILED" if r.status == "FAILED" else r.classification,
            } for r in results]
            self.ids.empty.text = "" if results else ("No matching results." if search else "No lookups yet.")

        background(lambda: self.app.service.recent(150, search), done)

    def schedule_refresh(self):
        if self._event:
            self._event.cancel()
        self._event = Clock.schedule_once(lambda *_: self.refresh(), 0.35)

    def open_detail(self, index):
        if index >= len(getattr(self, "results", [])):
            return
        result = self.results[index]
        body = BoxLayout(orientation="vertical", size_hint_y=None)
        body.bind(minimum_height=body.setter("height"))
        fill_rows(body, result_rows(result))
        Dialog(title=result.e164 or "Result", icon="info", body=body,
               buttons=[("Copy number", "outline", lambda: self.copy(result.e164)),
                        ("Close", "primary", None)]).open()

    def copy(self, value):
        if value:
            Clipboard.copy(value)
            self.app.toast("Number copied", "check", 1.8)


class SettingsScreen(BaseScreen):
    reveal_account = BooleanProperty(False)
    account_display = StringProperty("")

    def on_kv_post(self, *_):
        self.fields = {}
        grid = self.ids.fields
        for name in DEFAULT_SETTINGS:
            numeric = name != "default_region"
            field = Field(label=SETTING_LABELS[name], helper=SETTING_DESCRIPTIONS[name],
                          input_filter="float" if numeric else None,
                          input_type="number" if numeric else "text")
            self.fields[name] = field
            grid.add_widget(field)

    def _account_masked(self, grouped: str) -> str:
        return "----" + grouped[-5:] if len(grouped) >= 5 else "****"

    def _apply_account_display(self):
        grouped = self.app.hosting.account_id_grouped()
        self.account_display = grouped if self.reveal_account else self._account_masked(grouped)

    def on_reveal_account(self, *_):
        self._apply_account_display()

    def toggle_account_reveal(self):
        self.reveal_account = not self.reveal_account

    def copy_account_id(self):
        Clipboard.copy(self.app.hosting.account_id())
        self.app.toast("Account ID copied. Store it somewhere safe.", "check", 3)

    def refresh(self):
        self._apply_account_display()
        background(self.app.service.settings, self._fill)

    def _fill(self, settings):
        for name, value in settings.items():
            self.fields[name].text = value
            self.fields[name].error = ""

    def save_key(self):
        key = self.ids.key.text.strip()
        if not key:
            self.ids.key.error = "Paste your Telnyx API key"
            return
        if not is_plausible_key(key):
            self.ids.key.error = "That does not look like a Telnyx API key"
            return
        try:
            self.app.service.save_key(key)
        except Exception as exc:
            self.ids.key.error = friendly_error(exc)
            return
        self.ids.key.text = ""
        self.ids.key.ids.inp.focus = False
        self.app.refresh_key_state()
        self.app.toast("API key saved securely on this device", "check")

    def test_connection(self):
        button = self.ids.test
        button.busy = True

        def done(payload):
            button.busy = False
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            balance = data.get("balance")
            extra = f"  Balance {balance} {data.get('currency', '')}".rstrip() if balance is not None else ""
            self.app.toast("Connected - Telnyx accepted the key." + extra, "check", 4.5)

        def failed(exc):
            button.busy = False
            self.app.toast(friendly_error(exc), "error", 4.5)

        background(self.app.service.test_connection, done, failed)

    def confirm_remove(self):
        Dialog(title="Remove API key?", icon="warning", tone=T.danger,
               body=Text(role="caption", text="Lookups stop working until a new key is saved. Stored results are kept."),
               buttons=[("Cancel", "ghost", None), ("Remove", "danger", self.remove_key)]).open()

    def remove_key(self):
        self.app.service.remove_key()
        self.app.refresh_key_state()
        self.app.toast("API key removed", "info")

    def save_settings(self):
        values = {name: field.text for name, field in self.fields.items()}
        errors = {}
        from config import validate_setting
        for name, value in values.items():
            try:
                validate_setting(name, value)
            except ValueError as exc:
                errors[name] = str(exc)
        for name, field in self.fields.items():
            field.error = errors.get(name, "")
        if errors:
            first = next(self.fields[n] for n in self.fields if n in errors)
            self.ids.page.parent.scroll_to(first, padding=dp(80), animate=True)
            self.app.toast("Fix the highlighted settings", "warning")
            return
        self.app.service.update_settings(values)
        self.refresh()
        self.app.region = values["default_region"].upper()
        self.app.toast("Settings saved", "check")


STATUS_LABELS = {
    "pending_verification": ("Verification pending", T.warn),
    "verified": ("Verified", T.accent),
    "hosting_active": ("Active", T.accent),
}


class SMSScreen(BaseScreen):
    def refresh(self):
        background(self.app.hosting.numbers, self._render_list,
                  lambda e: self.app.toast(friendly_error(e), "error"))

    def page(self):
        page = self.ids.page
        page.clear_widgets()
        return page

    def _intro_card(self):
        card = Card(line=T.border_hi)
        card.add_widget(Factory.Icon(icon="sms", size_px=dp(30)))
        card.add_widget(Text(role="title", text="Business SMS"))
        card.add_widget(Text(role="caption", text="Receive texts sent to a business line you own, "
                             "right here in the app. Our team verifies your business's authorization "
                             "for the line (the LOA the carrier requires) before it's enabled."))
        return card

    def _render_list(self, numbers):
        page = self.page()
        page.add_widget(self._intro_card())
        add = AppButton(text="Add a business line you own", icon="add")
        add.bind(on_release=lambda *_: self.show_add())
        page.add_widget(add)
        if numbers:
            page.add_widget(SectionTitle(text="Your numbers", icon="verified"))
            card = Card(spacing=dp(2))
            for number in numbers:
                card.add_widget(self._number_row(number))
            page.add_widget(card)
        page.add_widget(Text(role="caption", text="Only for a business line you own. A number is "
                             "enabled only after our team verifies your authorization (LOA) for it, "
                             "and messages are only ever shown to the account that owns the line."))

    def _number_row(self, number):
        label, tone = STATUS_LABELS.get(number["status"], (number["status"], T.muted))
        verified = number["status"] in ("verified", "hosting_active")
        row = Factory.JobRow(
            title=number["e164"],
            meta=label,
            action_text="Open inbox" if verified else "Cancel",
            action_icon="inbox" if verified else "close",
            on_action=(lambda e=number["e164"]: self.open_inbox(e)) if verified
            else (lambda e=number["e164"]: self.cancel_request(e)))
        return row

    # ---- add / request

    def show_add(self):
        self.state = "add"
        page = self.page()
        card = Card(line=T.border_hi)
        card.add_widget(Text(role="title", text="Add a business line"))
        card.add_widget(Text(role="caption", text="Enter a phone number your business owns. Our team "
                             "verifies your authorization for the line (LOA) before it is enabled and "
                             "any messages appear."))
        self.number_field = Field(label="Business phone number", hint="+1 312 555 0100",
                                  input_type="tel", leading_icon="phone")
        card.add_widget(self.number_field)
        submit = AppButton(text="Submit for verification", icon="verified")
        submit.bind(on_release=lambda *_: self.submit_add(submit))
        card.add_widget(submit)
        cancel = AppButton(text="Back", icon="close", variant="ghost")
        cancel.bind(on_release=lambda *_: self.refresh())
        card.add_widget(cancel)
        page.add_widget(card)

    def submit_add(self, button):
        raw = self.number_field.text.strip()
        if not raw:
            self.number_field.error = "Enter a phone number"
            return
        button.busy = True

        def done(req):
            button.busy = False
            self.show_submitted(req)

        def failed(exc):
            button.busy = False
            if isinstance(exc, HostingError):
                self.number_field.error = str(exc)
            else:
                self.app.toast(friendly_error(exc), "error")

        background(lambda: self.app.hosting.request_hosting(raw), done, failed)

    def cancel_request(self, e164):
        background(lambda: self.app.hosting.release(e164),
                  lambda *_: self.refresh(),
                  lambda e: self.app.toast(friendly_error(e), "error"))

    def show_submitted(self, req):
        self.state = "submitted"
        page = self.page()
        card = Card(line=T.border_hi)
        top = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(10))
        top.add_widget(Factory.Icon(icon="verified", color=T.accent, pos_hint={"center_y": .5}))
        top.add_widget(Text(role="title", text="Request submitted", pos_hint={"center_y": .5}))
        card.add_widget(top)
        card.add_widget(Text(role="caption", text=f"We received your hosting request for "
                             f"[b]{req.e164}[/b]. Our team will verify your business's authorization "
                             "for this line (the Letter of Authorization the carrier requires) and "
                             "enable it. You'll see its messages here once it's verified."))
        card.add_widget(Text(role="caption", text="This number can only be enabled for a business "
                             "that is authorized for the line.", color=T.muted))
        done = AppButton(text="Back to my numbers", icon="check", variant="outline")
        done.bind(on_release=lambda *_: self.refresh())
        card.add_widget(done)
        page.add_widget(card)

    # ---- inbox

    def open_inbox(self, e164):
        self.state = "inbox"
        self.active_number = e164

        def loaded(messages):
            self.app.hosting.mark_read(e164)
            self._render_inbox(e164, messages)

        background(lambda: self.app.hosting.inbox(e164), loaded,
                  lambda e: self.app.toast(friendly_error(e), "error"))

    def _render_inbox(self, e164, messages):
        page = self.page()
        header = Card(line=T.border_hi, spacing=dp(6))
        top = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(10))
        top.add_widget(Factory.Icon(icon="verified", color=T.accent, pos_hint={"center_y": .5}))
        top.add_widget(Text(role="title", text=e164, pos_hint={"center_y": .5}))
        header.add_widget(top)
        header.add_widget(Text(role="caption", text="Inbound SMS for this verified line. Only your "
                               "account can see these."))
        back = AppButton(text="Back to my numbers", icon="close", variant="ghost", compact=True)
        back.bind(on_release=lambda *_: self.refresh())
        header.add_widget(back)
        page.add_widget(header)
        if not messages:
            empty = Card()
            empty.add_widget(Text(role="caption", text="No messages yet. Texts sent to this number "
                                  "will appear here once hosting is active."))
            page.add_widget(empty)
            return
        for message in messages:
            page.add_widget(self._message_card(message))

    def _message_card(self, message):
        card = Card(spacing=dp(4))
        top = BoxLayout(size_hint_y=None, height=dp(22), spacing=dp(8))
        top.add_widget(Text(role="label", text=message.get("from_number") or "Unknown sender",
                            pos_hint={"center_y": .5}))
        when = Label(text=fmt_time(message.get("received_at")), font_name="Mono", font_size=sp(11),
                     color=T.faint, halign="right", valign="middle", size_hint_x=None, width=dp(130))
        when.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
        top.add_widget(when)
        card.add_widget(top)
        body = Text(text=message.get("body") or "", role="body")
        card.add_widget(body)
        return card


class Root(FloatLayout):
    wide = BooleanProperty(False)
    page_title = StringProperty("PHONEINTEL")
    page_subtitle = StringProperty("")

    def on_size(self, *_):
        self.wide = self.width >= dp(840) and self.width > self.height * 1.05


class PhoneIntelApp(App):
    title = "PHONEINTEL"
    icon = "assets/icon.png"
    kv_file = str(APP_DIR / "phoneintel.kv")
    key_ok = BooleanProperty(False)
    masked_key = StringProperty("")
    region = StringProperty("US")
    version = StringProperty(APP_VERSION)

    def build(self):
        Window.clearcolor = T.bg
        Window.softinput_mode = "below_target"
        data_dir = Path(self.user_data_dir)
        self.service = PhoneIntelService(data_dir)
        self.hosting = HostingService(data_dir / "hosting")
        self.bridge = AndroidBridge(data_dir / "cache", Path(os.environ.get("PHONEINTEL_DOWNLOADS", Path.home() / "Downloads")))
        root = Root()
        self.shell = root
        sm = root.ids.sm
        sm.transition = FadeTransition(duration=0.14)
        for screen in (HomeScreen(), LookupScreen(), SMSScreen(),
                       HistoryScreen(), SettingsScreen()):
            sm.add_widget(screen)
        sm.bind(current=self._on_screen)
        self.refresh_key_state()
        self.region = self.service.settings()["default_region"]
        Window.bind(on_keyboard=self._on_key)
        self._on_screen(sm, sm.current)
        return root

    def on_start(self):
        self.bridge.style_system_bars("#050807", "#0B130E")

    def refresh_key_state(self):
        self.key_ok = self.service.has_key()
        self.masked_key = self.service.masked_key()

    def go(self, name):
        sm = self.shell.ids.sm
        if sm.current != name:
            sm.current = name
        else:
            sm.current_screen.refresh()

    def _on_screen(self, _sm, name):
        self.shell.ids.toast.hide()
        self.shell.page_title, self.shell.page_subtitle = PAGE_INFO.get(name, ("PHONEINTEL", ""))

    def toast(self, message, icon="info", duration=3.2):
        tone = {"error": T.danger, "warning": T.warn, "check": T.accent}.get(icon, T.info)
        self.shell.ids.toast.show(message, tone, icon, duration)

    def keep_awake(self, enabled: bool):
        if not IS_ANDROID:
            return
        try:
            from android_bridge import run_on_ui_thread
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            flag = autoclass("android.view.WindowManager$LayoutParams").FLAG_KEEP_SCREEN_ON

            @run_on_ui_thread
            def apply():
                window = activity.getWindow()
                window.addFlags(flag) if enabled else window.clearFlags(flag)

            apply()
        except Exception:
            pass

    def _on_key(self, _window, key, *_):
        if key != 27:
            return False
        from kivy.uix.modalview import ModalView
        for widget in Window.children:
            if isinstance(widget, ModalView):
                widget.dismiss()
                return True
        sm = self.shell.ids.sm
        if sm.current != "home":
            sm.current = "home"
            return True
        return self.bridge.minimize()

    def on_pause(self):
        return True


if __name__ == "__main__":
    PhoneIntelApp().run()
