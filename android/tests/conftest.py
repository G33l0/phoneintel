import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def lookup_payload(e164, line_type="mobile", carrier="Example Wireless"):
    return {"data": {
        "phone_number": e164, "country_code": "US", "valid_number": True,
        "carrier": {"name": carrier, "type": line_type, "error_code": None},
        "portability": {"ported_status": "N", "line_type": line_type},
    }}
