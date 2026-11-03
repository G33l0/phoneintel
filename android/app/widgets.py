from kivy.animation import Animation
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ColorProperty, ListProperty, NumericProperty, ObjectProperty,
                             OptionProperty, StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget

from theme import CLASS_COLORS, ICONS, T, with_alpha


class Card(BoxLayout):
    bg = ColorProperty(T.surface)
    line = ColorProperty(T.border)
    radius = NumericProperty(dp(18))


class Text(Label):
    role = OptionProperty("body", options=["body", "caption", "title", "h1", "label", "mono", "value"])


class Icon(Label):
    icon = StringProperty("info")
    glyph = StringProperty("")
    size_px = NumericProperty(dp(22))

    def on_icon(self, *_):
        self.glyph = ICONS.get(self.icon, "")

    def on_kv_post(self, *_):
        self.on_icon()


class Spacer(Widget):
    pass


class Pressable(ButtonBehavior):
    pressed_scale = NumericProperty(1.0)

    def on_state(self, _widget, state):
        Animation.cancel_all(self, "pressed_scale")
        Animation(pressed_scale=0.6 if state == "down" else 1.0, d=0.08).start(self)


class AppButton(Pressable, BoxLayout):
    text = StringProperty("")
    icon = StringProperty("")
    variant = OptionProperty("primary", options=["primary", "outline", "ghost", "danger", "danger_outline"])
    busy = BooleanProperty(False)
    busy_text = StringProperty("Working...")
    compact = BooleanProperty(False)
    bg_color = ColorProperty(T.accent)
    fg_color = ColorProperty(T.on_accent)
    line_color = ColorProperty(T.transparent)

    def on_kv_post(self, *_):
        self.bind(variant=self._restyle, disabled=self._restyle, busy=self._restyle, state=self._restyle)
        self._restyle()

    def _restyle(self, *_):
        styles = {
            "primary": (T.accent, T.on_accent, T.transparent),
            "outline": (T.transparent, T.accent, T.border_hi),
            "ghost": (T.transparent, T.muted, T.transparent),
            "danger": (T.danger, T.on_accent, T.transparent),
            "danger_outline": (T.transparent, T.danger, with_alpha(T.danger, 0.45)),
        }
        bg, fg, line = styles[self.variant]
        if self.state == "down" and not self.disabled:
            bg = with_alpha(bg, 0.82) if bg[3] else with_alpha(T.accent, 0.10)
        if self.disabled or self.busy:
            bg = T.raised if self.variant in ("primary", "danger") else bg
            fg = T.faint
            line = T.border if line[3] else line
        self.bg_color, self.fg_color, self.line_color = bg, fg, line

    def on_touch_down(self, touch):
        if self.busy:
            return self.collide_point(*touch.pos)
        return super().on_touch_down(touch)


class IconButton(Pressable, Label):
    icon = StringProperty("info")
    hidden = BooleanProperty(False)
    glyph = StringProperty("")
    tint = ColorProperty(T.muted)

    def on_icon(self, *_):
        self.glyph = ICONS.get(self.icon, "")

    def on_kv_post(self, *_):
        self.on_icon()


class Field(BoxLayout):
    label = StringProperty("")
    hint = StringProperty("")
    text = StringProperty("")
    helper = StringProperty("")
    error = StringProperty("")
    password = BooleanProperty(False)
    reveal = BooleanProperty(False)
    input_type = StringProperty("text")
    input_filter = ObjectProperty(None, allownone=True)
    leading_icon = StringProperty("")
    trailing_icon = StringProperty("")
    focused = BooleanProperty(False)

    __events__ = ("on_submit", "on_trailing")

    def on_text(self, _w, value):
        if self.ids and self.ids.inp.text != value:
            self.ids.inp.text = value

    def on_submit(self, *_):
        pass

    def on_trailing(self, *_):
        pass

    def focus(self):
        Clock.schedule_once(lambda *_: setattr(self.ids.inp, "focus", True), 0.05)


class ToggleSwitch(Pressable, Widget):
    active = BooleanProperty(False)
    knob = NumericProperty(0.0)

    def on_press(self):
        self.active = not self.active

    def on_active(self, *_):
        Animation.cancel_all(self, "knob")
        Animation(knob=1.0 if self.active else 0.0, d=0.16, t="out_quad").start(self)


class SwitchRow(Pressable, BoxLayout):
    title = StringProperty("")
    subtitle = StringProperty("")
    active = BooleanProperty(False)

    def on_release(self):
        self.active = not self.active


class Badge(Label):
    color_key = StringProperty("UNKNOWN")
    tone = ColorProperty(T.muted)

    def on_color_key(self, *_):
        self.tone = CLASS_COLORS.get(self.color_key, T.muted)

    def on_kv_post(self, *_):
        self.on_color_key()


class ProgressTrack(Widget):
    value = NumericProperty(0.0)
    indeterminate = BooleanProperty(False)
    shimmer = NumericProperty(0.0)

    def on_indeterminate(self, *_):
        Animation.cancel_all(self, "shimmer")
        if self.indeterminate:
            anim = Animation(shimmer=1.0, d=1.1) + Animation(shimmer=0.0, d=0)
            anim.repeat = True
            anim.start(self)


class StatTile(Card):
    icon = StringProperty("insights")
    value = StringProperty("0")
    caption = StringProperty("")
    tone = ColorProperty(T.accent)


class BarRow(BoxLayout):
    title = StringProperty("")
    count = NumericProperty(0)
    fraction = NumericProperty(0.0)
    tone = ColorProperty(T.accent)
    shown = NumericProperty(0.0)

    def on_kv_post(self, *_):
        Clock.schedule_once(lambda *_: Animation(shown=self.fraction, d=0.5, t="out_cubic").start(self), 0.05)


class KVRow(BoxLayout):
    key = StringProperty("")
    value = StringProperty("")
    tone = ColorProperty(T.text)
    mono = BooleanProperty(False)


class ColumnOption(Pressable, BoxLayout):
    name = StringProperty("")
    sample = StringProperty("")
    detected = BooleanProperty(False)
    selected = BooleanProperty(False)


class JobRow(BoxLayout):
    job_id = NumericProperty(0)
    title = StringProperty("")
    meta = StringProperty("")
    action_text = StringProperty("Resume")
    action_icon = StringProperty("resume")
    on_action = ObjectProperty(None, allownone=True)


class SectionTitle(BoxLayout):
    text = StringProperty("")
    icon = StringProperty("")


class NavItem(Pressable, BoxLayout):
    icon = StringProperty("home")
    text = StringProperty("")
    screen = StringProperty("")
    active = BooleanProperty(False)
    vertical_rail = BooleanProperty(False)


class NavBar(BoxLayout):
    current = StringProperty("home")
    rail = BooleanProperty(False)
    items = ListProperty([("home", "Home", "home"), ("lookup", "Lookup", "search"),
                          ("bulk", "Bulk", "upload"), ("history", "History", "history"),
                          ("settings", "Settings", "settings")])
    __events__ = ("on_navigate",)

    def on_kv_post(self, *_):
        self._build()
        self.bind(rail=lambda *_: self._build())

    def _build(self):
        holder = self.ids.item_box
        holder.clear_widgets()
        for screen, label, icon in self.items:
            item = NavItem(screen=screen, text=label, icon=icon, active=screen == self.current,
                           vertical_rail=self.rail)
            item.bind(on_release=lambda w: self.dispatch("on_navigate", w.screen))
            holder.add_widget(item)

    def on_current(self, *_):
        if not self.ids:
            return
        for item in self.ids.item_box.children:
            item.active = item.screen == self.current

    def on_navigate(self, screen):
        pass


class Dialog(ModalView):
    title = StringProperty("")
    icon = StringProperty("info")
    tone = ColorProperty(T.accent)

    def __init__(self, body=None, buttons=(), **kwargs):
        super().__init__(**kwargs)
        if body is not None:
            self.ids.body.add_widget(body)
        for text, variant, handler in buttons:
            button = AppButton(text=text, variant=variant)
            button.bind(on_release=lambda _w, h=handler: self._choose(h))
            self.ids.buttons.add_widget(button)
        if not buttons:
            self.ids.buttons.height = 0

    def _choose(self, handler):
        self.dismiss()
        if handler:
            Clock.schedule_once(lambda *_: handler(), 0)


class Toast(BoxLayout):
    text = StringProperty("")
    tone = ColorProperty(T.accent)
    icon_glyph = StringProperty("")
    _event = None

    def show(self, message: str, tone=None, icon: str = "info", duration: float = 3.2):
        self.text = message
        self.tone = tone or T.accent
        self.icon_glyph = ICONS.get(icon, "")
        Animation.cancel_all(self)
        Animation(opacity=1, d=0.18).start(self)
        if self._event:
            self._event.cancel()
        self._event = Clock.schedule_once(lambda *_: Animation(opacity=0, d=0.3).start(self), duration)

    def hide(self):
        if self._event:
            self._event.cancel()
        Animation.cancel_all(self)
        self.opacity = 0




def font_px(value: float) -> float:
    return sp(value)
