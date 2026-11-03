"""Copy the shared PHONEINTEL engine modules into the Kivy app folder before running or building."""
import shutil
import sys
from pathlib import Path

CORE = ["config.py", "validator.py", "classifier.py", "telnyx_client.py", "engine.py",
        "database.py", "bulk_processor.py", "exporter.py"]


def main() -> int:
    here = Path(__file__).resolve().parent
    root, app = here.parent, here / "app"
    for name in CORE:
        source = root / name
        if not source.is_file():
            print(f"missing core module: {source}", file=sys.stderr)
            return 1
        shutil.copy2(source, app / name)
    print(f"synced {len(CORE)} core modules into {app}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
