import sys

if sys.version_info < (3, 11):
    sys.exit("PHONEINTEL requires Python 3.11 or newer.")


def main() -> int:
    try:
        from interface import App
    except ImportError as exc:
        print(f"Missing dependency: {exc.name}. Run: pip install -r requirements.txt")
        return 1
    App().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
