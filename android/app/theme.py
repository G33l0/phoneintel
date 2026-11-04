from pathlib import Path

from kivy.core.text import LabelBase
from kivy.utils import get_color_from_hex as hx

ASSETS = Path(__file__).resolve().parent / "assets"


class T:
    bg = hx("#050807")
    surface = hx("#0B130E")
    surface2 = hx("#101C15")
    raised = hx("#14241A")
    border = hx("#1C3324")
    border_hi = hx("#2E5A3E")
    accent = hx("#00FF7A")
    accent_dim = hx("#00C25E")
    accent_soft = hx("#00FF7A26")
    on_accent = hx("#03140A")
    text = hx("#E6FFF0")
    muted = hx("#86A895")
    faint = hx("#4E6B5A")
    danger = hx("#FF5C6C")
    danger_soft = hx("#FF5C6C22")
    warn = hx("#FFC857")
    info = hx("#4FD1FF")
    violet = hx("#B58CFF")
    overlay = hx("#000000B8")
    transparent = (0, 0, 0, 0)


CLASS_COLORS = {
    "MOBILE": T.accent,
    "LANDLINE": T.info,
    "FIXED_VOIP": T.violet,
    "NON_FIXED_VOIP": T.violet,
    "OTHER_VOIP": T.violet,
    "VOIP": T.violet,
    "TOLL_FREE": T.warn,
    "OTHER": T.warn,
    "UNKNOWN": T.muted,
    "INVALID": T.danger,
    "FAILED": T.danger,
    "PENDING": T.faint,
}

STATUS_COLORS = {"SUCCESS": T.accent, "CACHED": T.info, "INVALID": T.danger, "FAILED": T.danger}

ICONS = {
    "home": "", "search": "", "phone": "", "upload": "",
    "history": "", "settings": "", "folder": "", "download": "",
    "share": "", "key": "", "check": "", "error": "", "warning": "",
    "info": "", "play": "", "refresh": "", "close": "",
    "visibility": "", "visibility_off": "", "paste": "", "delete": "",
    "radar": "", "smartphone": "", "table": "", "tower": "",
    "chart": "", "insights": "", "bolt": "", "save": "",
    "file": "", "resume": "", "stop": "", "tune": "", "shield": "",
    "lock": "", "lan": "", "cloud": "",
    "sms": "", "chat": "", "mail": "", "inbox": "", "forum": "", "verified": "",
    "call": "", "ring": "", "add": "", "forward": "", "copy": "", "badge": "",
}

FONT_UI = "Roboto"
FONT_MONO = "Mono"
FONT_MONO_BOLD = "MonoBold"
FONT_ICON = "Icons"


def register_fonts() -> None:
    LabelBase.register(FONT_MONO, str(ASSETS / "JetBrainsMono-Medium.ttf"))
    LabelBase.register(FONT_MONO_BOLD, str(ASSETS / "JetBrainsMono-Bold.ttf"))
    LabelBase.register(FONT_ICON, str(ASSETS / "MaterialIcons.ttf"))


def with_alpha(color, alpha: float):
    return (color[0], color[1], color[2], alpha)
