"""Operator-side verification tool for business-line SMS hosting.

An operator runs this after calling the number the user registered and hearing the code read
back. Confirming here is what moves a number to 'verified'. It is deliberately NOT part of the
user app: the person who answers the line and the operator are different roles, which is the
whole point of the ownership proof.

    python operator_verify.py --db <hosting.db> list
    python operator_verify.py --db <hosting.db> confirm +13125550100 123456

In a real deployment this logic lives in the secured admin portal, operating on the server's
hosting database, not on any device.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from hosting_db import HostingDB  # noqa: E402
from sms_hosting import HostingError, SMSHostingService  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PHONEINTEL operator verification")
    parser.add_argument("--db", required=True, help="path to hosting.db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show pending verifications")
    confirm = sub.add_parser("confirm", help="confirm a spoken code")
    confirm.add_argument("e164")
    confirm.add_argument("code")
    args = parser.parse_args(argv)

    with HostingDB(args.db) as db:
        service = SMSHostingService(db)
        if args.command == "list":
            rows = db.conn.execute(
                "SELECT v.e164, v.attempts, v.max_attempts, v.expires_at "
                "FROM verifications v").fetchall()
            if not rows:
                print("No pending verifications.")
                return 0
            for r in rows:
                print(f"{r['e164']}  attempts={r['attempts']}/{r['max_attempts']}  "
                      f"expires={r['expires_at']}")
            return 0
        if args.command == "confirm":
            try:
                service.confirm_ownership(args.e164, args.code)
            except HostingError as exc:
                print(f"NOT VERIFIED: {exc}", file=sys.stderr)
                return 1
            print(f"VERIFIED: {args.e164} is now confirmed as owned.")
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
