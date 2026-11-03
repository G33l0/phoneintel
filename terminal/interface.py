
from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from classifier import LookupResult
from config import (APP_NAME, APP_VERSION, DEFAULT_SETTINGS, SETTING_DESCRIPTIONS, AppConfig,
                    is_plausible_key, mask_key, validate_setting)
from database import Database
from engine import PhoneIntelEngine
from telnyx_client import AuthenticationError, TelnyxError

THEME = Theme({
    "accent": "bold bright_green",
    "dim": "green",
    "ok": "bold bright_green",
    "warn": "bold yellow",
    "err": "bold red",
    "label": "bright_green",
    "value": "bright_white",
})
BG = "on black"

BANNER = r"""
 ____  _   _  ___  _   _ _____ ___ _   _ _____ _____ _
|  _ \| | | |/ _ \| \ | | ____|_ _| \ | |_   _| ____| |
| |_) | |_| | | | |  \| |  _|  | ||  \| | | | |  _| | |
|  __/|  _  | |_| | |\  | |___ | || |\  | | | | |___| |___
|_|   |_| |_|\___/|_| \_|_____|___|_| \_| |_| |_____|_____|
"""

MENU = [
    ("1", "Single Phone Number Lookup"),
    ("2", "Free Phone Validation (offline, no key)"),
    ("3", "View Previous Results"),
    ("4", "View Statistics"),
    ("5", "Telnyx API Configuration"),
    ("6", "Test API Connection"),
    ("7", "Application Information"),
    ("8", "Exit"),
]

CLASS_STYLES = {
    "MOBILE": "bright_green", "LANDLINE": "cyan", "FIXED_VOIP": "magenta",
    "NON_FIXED_VOIP": "magenta", "OTHER_VOIP": "magenta", "TOLL_FREE": "yellow",
    "OTHER": "yellow", "UNKNOWN": "white", "INVALID": "red",
}
STATUS_STYLES = {"SUCCESS": "ok", "CACHED": "ok", "INVALID": "err", "FAILED": "err"}


class App:
    def __init__(self, config: AppConfig | None = None, console: Console | None = None):
        self.config = config or AppConfig()
        self.config.ensure_dirs()
        self.console = console or Console(theme=THEME, highlight=False)
        self.db = Database(self.config.db_path)
        self.actions = {
            "1": self.single_lookup, "2": self.free_validation, "3": self.view_results,
            "4": self.statistics, "5": self.configure, "6": self.test_connection,
            "7": self.information,
        }

    @property
    def narrow(self) -> bool:
        return self.console.width < 70

    def engine(self) -> PhoneIntelEngine:
        return PhoneIntelEngine.from_config(self.config, self.db)

    def run(self) -> None:
        try:
            while True:
                self.show_menu()
                choice = self.ask("Select an option", choices=[k for k, _ in MENU], show_choices=False)
                if choice == "8":
                    self.console.print("[accent]Session closed. Goodbye.[/]")
                    return
                self.console.clear()
                try:
                    self.actions[choice]()
                except KeyboardInterrupt:
                    self.console.print("\n[warn]Action cancelled.[/]")
                except (EOFError, SystemExit):
                    raise
                except Exception as exc:
                    self.error(f"Unexpected error: {exc}")
                self.pause()
        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[accent]Session closed. Goodbye.[/]")
        finally:
            self.db.close()

    # ---------- shared widgets ----------

    def ask(self, prompt: str, **kwargs) -> str:
        return Prompt.ask(f"[accent]>[/] [label]{prompt}[/]", console=self.console, **kwargs)

    def confirm(self, prompt: str, default: bool = False) -> bool:
        return Confirm.ask(f"[accent]>[/] [label]{prompt}[/]", console=self.console, default=default)

    def pause(self) -> None:
        try:
            self.console.input("\n[dim]Press Enter to return to the menu...[/]")
        except KeyboardInterrupt:
            pass

    def panel(self, body, title: str, style: str = "accent") -> Panel:
        return Panel(body, title=f"[{style}] {title} [/]", border_style="green", box=box.ROUNDED,
                     style=BG, padding=(0, 1))

    def header(self, title: str) -> None:
        self.console.print(self.panel(Align.center(Text(title, style="accent")), APP_NAME))

    def error(self, message: str) -> None:
        self.console.print(self.panel(Text(message, style="err"), "ERROR", "err"))

    def success(self, message: str) -> None:
        self.console.print(self.panel(Text(message, style="ok"), "OK"))

    def table(self, title: str | None = None) -> Table:
        return Table(title=title, box=box.SIMPLE_HEAVY, border_style="green", header_style="accent",
                     style=BG, expand=True, title_style="accent")

    def key_value(self, rows: list[tuple[str, str]]) -> Table:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="label", no_wrap=True)
        grid.add_column(style="value", overflow="fold")
        for key, value in rows:
            grid.add_row(key, value if isinstance(value, Text) else Text(str(value)))
        return grid

    # ---------- main menu ----------

    def show_menu(self) -> None:
        self.console.clear()
        banner = Text(APP_NAME, style="accent") if self.console.width < 66 else Text(BANNER.strip("\n"), style="accent")
        key = self.config.api_key()
        if key:
            status = Text.assemble(("API KEY ", "dim"), (mask_key(key), "value"), ("  READY", "ok"))
        else:
            status = Text("API KEY NOT CONFIGURED - use option 5", style="warn")
        subtitle = Text(f"Phone Number Intelligence v{APP_VERSION}  |  Powered by Telnyx Number Lookup", style="dim")
        self.console.print(self.panel(Group(Align.center(banner), Align.center(subtitle), Align.center(status)),
                                      "TERMINAL"))
        menu = Table.grid(padding=(0, 2), expand=True)
        columns = 1 if self.narrow else 2
        for _ in range(columns):
            menu.add_column(justify="right", style="accent", no_wrap=True, width=4)
            menu.add_column(style="value", overflow="fold")
        half = (len(MENU) + columns - 1) // columns
        for i in range(half):
            cells = []
            for c in range(columns):
                idx = i + c * half
                if idx < len(MENU):
                    cells += [f"[{MENU[idx][0]}]", MENU[idx][1]]
                else:
                    cells += ["", ""]
            menu.add_row(*cells)
        self.console.print(self.panel(menu, "MAIN MENU"))

    # ---------- 1. single lookup ----------

    def single_lookup(self) -> None:
        self.header("SINGLE PHONE NUMBER LOOKUP")
        engine = self.engine()
        if engine.client is None:
            return self.error("No Telnyx API key configured. Use option 5 first.")
        raw = self.ask(f"Enter phone number (default region {engine.settings.default_region})").strip()
        if not raw:
            return self.error("No number entered.")
        check = engine.validate(raw)
        force = False
        if check.valid and engine.cached(check.e164):
            force = self.confirm("A cached result exists. Force a fresh lookup?", default=False)
        try:
            with self.console.status("[accent]Querying Telnyx...[/]", spinner="dots"):
                result = engine.lookup(raw, force=force)
        except AuthenticationError as exc:
            return self.error(f"{exc}\nCheck your API key with option 5.")
        self.show_result(result)

    def free_validation(self) -> None:
        self.header("FREE PHONE VALIDATION")
        engine = self.engine()
        remaining = engine.free_validations_remaining()
        self.console.print(f"[dim]Offline validation - no Telnyx, no API key. "
                           f"Free uses left today:[/] [value]{remaining}[/]")
        if remaining <= 0:
            return self.error("You have used today's free validations. This resets at 00:00 UTC.\n"
                              "Use option 1 for a full carrier lookup via Telnyx.")
        raw = self.ask(f"Enter phone number (default region {engine.settings.default_region})").strip()
        if not raw:
            return self.error("No number entered. (Your free allowance was not used.)")
        outcome = engine.free_validate_rate_limited(raw)
        if not outcome.allowed:
            return self.error(outcome.message or "Free validation limit reached.")
        self.show_free_result(outcome)

    def show_free_result(self, outcome) -> None:
        result = outcome.result
        if not result.valid:
            rows = [("Input", result.input or "-"),
                    ("Valid", Text("NO", style="err")),
                    ("Reason", Text(result.error or "Invalid number", style="warn"))]
        else:
            hint = result.classification_hint or "UNKNOWN"
            rows = [
                ("Input", result.input),
                ("Phone number", result.e164 or "-"),
                ("Valid", Text("YES", style="ok")),
                ("Country", result.country or "-"),
                ("Area / region", result.region or "-"),
                ("National format", result.national_format or "-"),
                ("Line type (estimate)", Text(f"{result.line_type_hint}", style=CLASS_STYLES.get(hint, "value"))),
            ]
        rows.append(("Source", "Offline number-plan data (not a carrier lookup)"))
        rows.append(("Free uses left today", str(outcome.remaining)))
        self.console.print(self.panel(self.key_value(rows), "FREE VALIDATION"))
        self.console.print("[dim]Line type here is an estimate from numbering-plan ranges. "
                           "For carrier-confirmed results use option 1 (Telnyx).[/]")

    def show_result(self, result: LookupResult) -> None:
        port = result.ported_status or "Not provided"
        if result.ported_date:
            port += f" (ported {result.ported_date})"
        rows = [
            ("Input", result.input),
            ("Phone number", result.e164 or "-"),
            ("Country", result.country or "-"),
            ("Carrier", result.carrier or "Not provided"),
            ("Provider line type", result.line_type_raw or "Not provided"),
            ("Classification", Text(result.classification, style=CLASS_STYLES.get(result.classification, "value"))),
            ("Portability", port),
            ("Lookup timestamp", result.looked_up_at),
            ("Lookup status", Text(result.status, style=STATUS_STYLES.get(result.status, "value"))),
        ]
        if result.line_type_source:
            rows.insert(5, ("Line type source", result.line_type_source))
        if result.error:
            rows.append(("Notes", Text(result.error, style="warn")))
        self.console.print(self.panel(self.key_value(rows), "LOOKUP RESULT"))

    def view_results(self) -> None:
        self.header("PREVIOUS RESULTS")
        options = {"1": "Recent lookups", "2": "Search by number", "0": "Back"}
        self.console.print(self.key_value([(f"[{k}]", v) for k, v in options.items()]))
        choice = self.ask("Select", choices=list(options), show_choices=False, default="1")
        if choice == "1":
            self.show_results(self.db.recent_results(25), "RECENT LOOKUPS")
        elif choice == "2":
            term = self.ask("Number or fragment").strip()
            self.show_results(self.db.recent_results(50, term), f"RESULTS FOR '{term}'")

    def show_results(self, results: list[LookupResult], title: str) -> None:
        if not results:
            return self.console.print("[warn]No results found.[/]")
        table = self.table(title)
        table.add_column("Number", style="value", overflow="fold")
        table.add_column("Class", overflow="fold")
        if not self.narrow:
            table.add_column("Carrier", overflow="fold")
            table.add_column("Line type", overflow="fold")
            table.add_column("When", no_wrap=True)
        table.add_column("Status")
        for r in results:
            row = [r.e164 or r.input, Text(r.classification, style=CLASS_STYLES.get(r.classification, "value"))]
            if not self.narrow:
                row += [r.carrier or "-", r.line_type_raw or "-", r.looked_up_at[:16].replace("T", " ")]
            row.append(Text(r.status, style=STATUS_STYLES.get(r.status, "value")))
            table.add_row(*row)
        self.console.print(table)

    # ---------- 4. statistics ----------

    def statistics(self) -> None:
        self.header("STATISTICS")
        stats = self.db.global_stats()
        rows = [("Unique numbers stored", str(stats["unique_numbers"])),
                ("Lookup records", str(stats["lookups_total"]))]
        rows += [(f"Status {k}", str(v)) for k, v in sorted(stats["by_status"].items())]
        self.console.print(self.panel(self.key_value(rows), "OVERVIEW"))
        if stats["by_classification"]:
            table = self.table("LATEST CLASSIFICATION PER NUMBER")
            table.add_column("Classification", style="label")
            table.add_column("Numbers", justify="right", style="value")
            total = sum(stats["by_classification"].values()) or 1
            table.add_column("Share", justify="right", style="dim")
            for name, count in sorted(stats["by_classification"].items(), key=lambda x: -x[1]):
                table.add_row(Text(name, style=CLASS_STYLES.get(name, "value")), str(count),
                              f"{count / total:.1%}")
            self.console.print(table)

    # ---------- 9. configuration ----------

    def configure(self) -> None:
        while True:
            self.console.clear()
            self.header("TELNYX API CONFIGURATION")
            key = self.config.api_key()
            rows = [("API key", mask_key(key)), ("Stored in", str(self.config.env_path))]
            self.console.print(self.panel(self.key_value(rows), "CREDENTIALS"))
            table = self.table("SETTINGS")
            table.add_column("#", style="accent", width=3)
            table.add_column("Setting", style="label", overflow="fold")
            table.add_column("Value", style="value")
            if not self.narrow:
                table.add_column("Description", style="dim", overflow="fold")
            names = list(DEFAULT_SETTINGS)
            for i, name in enumerate(names, 1):
                row = [str(i), name, self.db.get_setting(name)]
                if not self.narrow:
                    row.append(SETTING_DESCRIPTIONS[name])
                table.add_row(*row)
            self.console.print(table)
            self.console.print("[accent][K][/] Set API key  [accent][R][/] Remove API key  "
                               "[accent][1-8][/] Edit setting  [accent][0][/] Back")
            choice = self.ask("Select", default="0").strip().upper()
            if choice == "0":
                return
            if choice == "K":
                self.set_api_key()
            elif choice == "R":
                if self.confirm("Remove the stored API key?", default=False):
                    self.config.remove_api_key()
                    self.success("API key removed.")
            elif choice.isdigit() and 1 <= int(choice) <= len(names):
                self.edit_setting(names[int(choice) - 1])
            else:
                self.error("Unknown option.")
            self.pause()

    def set_api_key(self) -> None:
        key = Prompt.ask("[accent]>[/] [label]Paste Telnyx API key (input hidden)[/]",
                         console=self.console, password=True).strip()
        if not key:
            return self.console.print("[warn]No key entered. Nothing changed.[/]")
        if not is_plausible_key(key):
            return self.error("That does not look like a Telnyx API key. Nothing saved.")
        self.config.save_api_key(key)
        self.success(f"API key saved as {mask_key(key)} in {self.config.env_path}")

    def edit_setting(self, name: str) -> None:
        value = self.ask(f"New value for {name}", default=self.db.get_setting(name))
        try:
            self.db.set_setting(name, validate_setting(name, value))
        except ValueError as exc:
            return self.error(str(exc))
        self.success(f"{name} updated.")

    # ---------- 10. connection test ----------

    def test_connection(self) -> None:
        self.header("TEST API CONNECTION")
        engine = self.engine()
        if engine.client is None:
            return self.error("No Telnyx API key configured. Use option 5 first.")
        try:
            with self.console.status("[accent]Contacting api.telnyx.com...[/]"):
                payload = engine.client.check_connection()
        except AuthenticationError as exc:
            return self.error(f"{exc}\nThe key was rejected by Telnyx.")
        except TelnyxError as exc:
            return self.error(str(exc))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        rows = [("Endpoint", "GET /v2/balance (no lookup charge)"), ("Authentication", Text("ACCEPTED", style="ok"))]
        if data.get("balance") is not None:
            rows.append(("Account balance", f"{data.get('balance')} {data.get('currency', '')}".strip()))
        self.console.print(self.panel(self.key_value(rows), "CONNECTION OK"))

    # ---------- 11. info ----------

    def information(self) -> None:
        self.header("APPLICATION INFORMATION")
        rows = [
            ("Application", f"{APP_NAME} v{APP_VERSION}"),
            ("Data source", "Telnyx Number Lookup API (type=carrier)"),
            ("Data requested", "Carrier, line type, portability only"),
            ("Not requested", "Caller name, identity, address"),
            ("Database", str(self.config.db_path)),
            ("Config file", str(self.config.env_path)),
            ("Classifications", "MOBILE, LANDLINE, FIXED_VOIP, NON_FIXED_VOIP, OTHER_VOIP, "
                                "TOLL_FREE, OTHER, UNKNOWN, INVALID"),
            ("Classification rule", "Provider-reported line type only; never inferred from prefixes"),
        ]
        self.console.print(self.panel(self.key_value(rows), "ABOUT"))
