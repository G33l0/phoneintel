"""Super-admin configuration CLI (stand-in for the admin portal).

Edits the operator-only settings a super-admin controls: the fallback validation provider
and the SMS hosting pricing / profit margins. In a real deployment this same AdminConfig
layer is driven by the secured web portal; this CLI operates on the server's phoneintel.db.

    python admin_tool.py --db <phoneintel.db> show
    python admin_tool.py --db <phoneintel.db> set margin_receive_percent 125
    python admin_tool.py --db <phoneintel.db> set fallback_validation_provider twilio

Provider API credentials are never set here; they live in the operator's secure environment
(TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN, TELNYX_API_KEY).
"""
import argparse
import sys

from admin_config import DEFAULTS, AdminConfig
from database import Database


def _print_quote(label, quote):
    if quote is None:
        print(f"  {label}: disabled")
        return
    print(f"  {label}: cost {quote.provider_cost} + {quote.margin_percent}% "
          f"=> charge {quote.billable} {quote.currency} (profit {quote.profit})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PHONEINTEL super-admin config")
    parser.add_argument("--db", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    setter = sub.add_parser("set")
    setter.add_argument("key")
    setter.add_argument("value")
    args = parser.parse_args(argv)

    with Database(args.db) as db:
        cfg = AdminConfig(db)
        if args.command == "set":
            if args.key not in DEFAULTS:
                print(f"Unknown setting '{args.key}'. Valid: {', '.join(DEFAULTS)}", file=sys.stderr)
                return 1
            try:
                saved = cfg.set(args.key, args.value)
            except ValueError as exc:
                print(f"Rejected: {exc}", file=sys.stderr)
                return 1
            print(f"{args.key} = {saved}")
            return 0
        # show
        print("Admin settings:")
        for key in DEFAULTS:
            print(f"  {key} = {cfg.get(key)}")
        print("Pricing:")
        _print_quote("receive SMS", cfg.receive_quote())
        _print_quote("send SMS", cfg.send_quote())
        print(f"Fallback validation provider: {cfg.fallback_provider()} "
              f"(line-type lookups are billable; offline validation stays free)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
