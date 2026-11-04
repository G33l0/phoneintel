"""Operator / super-admin verification tool for business-line SMS hosting.

The admin runs this after validating the business's Letter of Authorization (LOA) for a
requested number - the same authorization the carrier requires to host/text-enable a line.
Recording the verification here is what moves a number to 'verified' and lets its messages
through to the requesting account.

    python operator_verify.py --db <hosting.db> list
    python operator_verify.py --db <hosting.db> verify +13125550100 LOA-2026-00042 [--by alice]

Verification is an operator action by design: it is never something the app user can do to
their own request. In a real deployment this runs inside the secured admin portal against the
server's hosting database, not on any device.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from hosting_db import PENDING, HostingDB  # noqa: E402
from sms_hosting import HostingError, SMSHostingService  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PHONEINTEL operator verification")
    parser.add_argument("--db", required=True, help="path to hosting.db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show numbers awaiting verification")
    verify = sub.add_parser("verify", help="verify a number after validating its LOA")
    verify.add_argument("e164")
    verify.add_argument("loa_reference", help="reference of the validated LOA document")
    verify.add_argument("--by", default=None, help="operator identifier for the audit record")
    args = parser.parse_args(argv)

    with HostingDB(args.db) as db:
        service = SMSHostingService(db)
        if args.command == "list":
            rows = db.conn.execute(
                "SELECT e164, account_id_hash, requested_at FROM hosted_numbers WHERE status = ? "
                "ORDER BY requested_at", (PENDING,)).fetchall()
            if not rows:
                print("No numbers awaiting verification.")
                return 0
            for r in rows:
                print(f"{r['e164']}  account={r['account_id_hash'][:12]}...  "
                      f"requested={r['requested_at']}")
            return 0
        if args.command == "verify":
            try:
                service.verify_ownership(args.e164, args.loa_reference, verified_by=args.by)
            except HostingError as exc:
                print(f"NOT VERIFIED: {exc}", file=sys.stderr)
                return 1
            print(f"VERIFIED: {args.e164} enabled (LOA {args.loa_reference}).")
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
