"""Keep android/app's copy of the PHONEINTEL engine identical to terminal/.

    python android/sync_core.py          copy terminal/ engine modules into android/app
    python android/sync_core.py --check  exit 1 if the copies differ (used by CI)
"""
import filecmp
import shutil
import sys
from pathlib import Path

CORE = ["config.py", "validator.py", "classifier.py", "telnyx_client.py", "engine.py",
        "database.py", "bulk_processor.py", "exporter.py"]
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "terminal"
TARGET = HERE / "app"


def out_of_sync() -> list[str]:
    return [name for name in CORE
            if not (TARGET / name).is_file() or not filecmp.cmp(SOURCE / name, TARGET / name, shallow=False)]


def main(argv: list[str]) -> int:
    if "--check" in argv:
        stale = out_of_sync()
        if stale:
            print("android/app engine copies differ from terminal/: " + ", ".join(stale), file=sys.stderr)
            print("run: python android/sync_core.py", file=sys.stderr)
            return 1
        print("android/app engine copies are in sync")
        return 0
    for name in CORE:
        shutil.copy2(SOURCE / name, TARGET / name)
    print(f"synced {len(CORE)} engine modules from {SOURCE} into {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
