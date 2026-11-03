import csv
import json
from datetime import datetime
from pathlib import Path

from bulk_processor import record_bucket
from classifier import BUCKET_CLASSES, EXPORT_BUCKETS, LookupResult
from database import Database

RESULT_COLUMNS = [
    "pi_row", "pi_input", "pi_e164", "pi_country", "pi_carrier", "pi_line_type",
    "pi_line_type_source", "pi_classification", "pi_bucket", "pi_ported_status", "pi_ported_date",
    "pi_status", "pi_duplicate_of_row", "pi_error", "pi_looked_up_at",
]
NUMBER_COLUMNS = ["e164", "country", "carrier", "line_type", "classification",
                  "ported_status", "ported_date", "looked_up_at"]


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def job_rows(db: Database, job_id: int) -> tuple[list[str], list[dict]]:
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    original = json.loads(job["columns_json"])
    rows = []
    for record in db.job_records(job_id):
        row = dict(json.loads(record["raw_json"]))
        bucket = record_bucket(record)
        row.update({
            "pi_row": record["row_index"] + 1,
            "pi_input": record["raw_value"],
            "pi_e164": record["e164"] or "",
            "pi_country": record.get("country") or "",
            "pi_carrier": record.get("carrier") or "",
            "pi_line_type": record.get("line_type_raw") or "",
            "pi_line_type_source": record.get("line_type_source") or "",
            "pi_classification": record.get("classification") or ("INVALID" if bucket == "INVALID" else ""),
            "pi_bucket": bucket,
            "pi_ported_status": record.get("ported_status") or "",
            "pi_ported_date": record.get("ported_date") or "",
            "pi_status": record.get("r_status") or record["status"].upper(),
            "pi_duplicate_of_row": "" if record["duplicate_of"] is None else record["duplicate_of"] + 1,
            "pi_error": record.get("error") or record.get("validation_error") or "",
            "pi_looked_up_at": record.get("looked_up_at") or "",
        })
        rows.append(row)
    return original + [c for c in RESULT_COLUMNS if c not in original], rows


def export_job(db: Database, job_id: int, export_root: Path) -> Path:
    columns, rows = job_rows(db, job_id)
    folder = Path(export_root) / f"job_{job_id}_{timestamp()}"
    folder.mkdir(parents=True, exist_ok=True)
    for bucket in EXPORT_BUCKETS:
        subset = [r for r in rows if r["pi_bucket"] == bucket]
        write_csv(folder / f"{bucket}.csv", columns, subset)
    pending = [r for r in rows if r["pi_bucket"] == "PENDING"]
    if pending:
        write_csv(folder / "PENDING.csv", columns, pending)
    write_workbook(folder / "COMPLETE_RESULTS.xlsx", columns, rows)
    db.update_job(job_id, export_dir=str(folder))
    return folder


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_workbook(path: Path, columns: list[str], rows: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    workbook = Workbook(write_only=True)
    header_font = Font(bold=True, color="00FF66")
    header_fill = PatternFill("solid", fgColor="0B0F0C")
    results = workbook.create_sheet("Results")
    results.append([_header_cell(results, c, header_font, header_fill) for c in columns])
    for row in rows:
        results.append([_excel_value(results, row.get(c, "")) for c in columns])
    summary = workbook.create_sheet("Summary")
    summary.append([_header_cell(summary, c, header_font, header_fill) for c in ("bucket", "rows")])
    buckets = list(EXPORT_BUCKETS) + ["PENDING"]
    for bucket in buckets:
        summary.append([bucket, sum(1 for r in rows if r.get("pi_bucket") == bucket)])
    workbook.save(path)


def _header_cell(sheet, value, font, fill):
    from openpyxl.cell import WriteOnlyCell
    cell = WriteOnlyCell(sheet, value=value)
    cell.font, cell.fill = font, fill
    return cell


def _excel_value(sheet, value):
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith("="):
        from openpyxl.cell import WriteOnlyCell
        cell = WriteOnlyCell(sheet, value=value)
        cell.data_type = "s"
        return cell
    return value


def export_bucket_numbers(db: Database, bucket: str, export_root: Path) -> tuple[Path, int]:
    if bucket not in BUCKET_CLASSES:
        raise ValueError(f"Unsupported bucket: {bucket}")
    classes = tuple(c.value for c in BUCKET_CLASSES[bucket])
    results = db.latest_successful(classes)
    path = Path(export_root) / f"{bucket}_{timestamp()}.csv"
    Path(export_root).mkdir(parents=True, exist_ok=True)
    write_csv(path, NUMBER_COLUMNS, [_number_row(r) for r in results])
    return path, len(results)


def _number_row(result: LookupResult) -> dict:
    return {
        "e164": result.e164,
        "country": result.country or "",
        "carrier": result.carrier or "",
        "line_type": result.line_type_raw or "",
        "classification": result.classification,
        "ported_status": result.ported_status or "",
        "ported_date": result.ported_date or "",
        "looked_up_at": result.looked_up_at,
    }
