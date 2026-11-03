import importlib.util
from pathlib import Path

ANDROID = Path(__file__).resolve().parents[1]


def test_engine_copies_match_terminal():
    spec = importlib.util.spec_from_file_location("sync_core", ANDROID / "sync_core.py")
    sync_core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_core)
    assert sync_core.out_of_sync() == [], "run: python android/sync_core.py"


def test_app_has_no_terminal_only_modules():
    app = ANDROID / "app"
    assert not (app / "interface.py").exists()
    assert (app / "main.py").read_text(encoding="utf-8").count("from kivy.app import App") == 1
