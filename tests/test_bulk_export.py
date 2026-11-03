import csv
import json
import threading

from openpyxl import Workbook, load_workbook
import pytest

import exporter
from bulk_processor import (BulkInputError, BulkProcessor, clean_path, create_job, detect_column,
                            estimate, load_file, prepare_job)
from classifier import EXPORT_BUCKETS
from telnyx_client import AuthenticationError, NetworkError
from tests.conftest import FakeClient

NUMBERS = {
    "+16502530000": "mobile",
    "+12125551234": "fixed line",
    "+13125550100": "voip",
    "+14155550123": "toll free",
    "+12025550123": "fixed line or mobile",
}


def write_csv(path, rows, header=("name", "phone", "city")):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if header:
            writer.writerow(header)
        writer.writerows(rows)


SAMPLE_ROWS = [
    ("Alice", "(650) 253-0000", "MV"),
    ("Bob", "212-555-1234", "NY"),
    ("Carol", "not a number", "LA"),
    ("Dan", "+1 650 253 0000", "SF"),
    ("Eve", "3125550100", "CHI"),
    ("Fay", "4155550123", "SF"),
    ("Gus", "+12025550123", "DC"),
    ("Hal", "8005551234", "TX"),
]


def run_sample(tmp_path, make_engine, client=None):
    source = tmp_path / "input.csv"
    write_csv(source, SAMPLE_ROWS)
    responses = dict(NUMBERS)
    responses["+18005551234"] = NetworkError("timeout")
    client = client or FakeClient(responses)
    engine = make_engine(client)
    frame = load_file(source)
    prepared = prepare_job(frame, detect_column(frame), str(source))
    job_id = create_job(engine, prepared)
    summary = BulkProcessor(engine).run(job_id)
    return engine, client, job_id, summary


def test_csv_loading_and_column_detection(tmp_path):
    source = tmp_path / "in.csv"
    write_csv(source, SAMPLE_ROWS)
    table = load_file(source)
    assert table.columns == ["name", "phone", "city"]
    assert len(table) == len(SAMPLE_ROWS)
    assert detect_column(table) == "phone"


def test_headerless_csv_detected(tmp_path):
    source = tmp_path / "in.csv"
    write_csv(source, [("6502530000",), ("2125551234",)], header=None)
    frame = load_file(source)
    assert len(frame) == 2 and detect_column(frame) == "column_1"


def test_semicolon_csv(tmp_path):
    source = tmp_path / "in.csv"
    source.write_text("id;mobile\n1;6502530000\n2;2125551234\n", encoding="utf-8")
    frame = load_file(source)
    assert detect_column(frame) == "mobile"


def test_xlsx_loading_preserves_text(tmp_path):
    source = tmp_path / "in.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["Customer", "Contact Number"])
    sheet.append(["A", 16502530000])
    sheet.append(["B", "212-555-1234"])
    book.save(source)
    frame = load_file(source)
    assert detect_column(frame) == "Contact Number"
    prepared = prepare_job(frame, "Contact Number", str(source))
    assert [r["e164"] for r in prepared.records] == ["+16502530000", "+12125551234"]


def test_txt_loading(tmp_path):
    source = tmp_path / "in.txt"
    source.write_text("6502530000\n\n212-555-1234\n", encoding="utf-8")
    frame = load_file(source)
    assert frame.column_values("phone_number") == ["6502530000", "212-555-1234"]


def test_unsupported_and_missing_files(tmp_path):
    with pytest.raises(BulkInputError):
        load_file(tmp_path / "nope.csv")
    bad = tmp_path / "x.pdf"
    bad.write_text("x")
    with pytest.raises(BulkInputError):
        load_file(bad)


def test_clean_path_handles_shell_quoting():
    assert str(clean_path('"C:/data/file.csv"')) == "C:/data/file.csv"
    assert str(clean_path("& 'C:/data/file.csv'")) == "C:/data/file.csv"


def test_duplicate_detection_and_estimate(tmp_path, make_engine):
    source = tmp_path / "in.csv"
    write_csv(source, SAMPLE_ROWS)
    frame = load_file(source)
    prepared = prepare_job(frame, "phone", str(source))
    assert prepared.total == 8 and prepared.invalid == 1 and prepared.duplicates == 1
    assert prepared.records[3]["duplicate_of"] == 0
    engine = make_engine(FakeClient(), cost_per_lookup=0.01)
    engine.lookup("6502530000")
    est = estimate(prepared, engine)
    assert est.unique_valid == 6 and est.cached == 1 and est.to_lookup == 5
    assert est.estimated_cost == pytest.approx(0.05)
    assert estimate(prepared, engine, force=True).to_lookup == 6


def test_bulk_run_classifies_each_unique_number_once(tmp_path, make_engine):
    engine, client, job_id, summary = run_sample(tmp_path, make_engine)
    assert summary.status == "completed"
    assert sorted(client.calls) == sorted(set(client.calls))
    assert len(client.calls) == 6
    assert summary.buckets == {"MOBILE": 2, "LANDLINE": 1, "VOIP": 1, "OTHER": 1, "UNKNOWN": 1,
                               "INVALID": 1, "FAILED": 1, "PENDING": 0}
    stats = engine.db.job_stats(job_id)
    assert stats["api_calls"] == 6 and stats["duplicates"] == 1


def test_exports_preserve_order_and_original_columns(tmp_path, make_engine):
    engine, _, job_id, _ = run_sample(tmp_path, make_engine)
    folder = exporter.export_job(engine.db, job_id, tmp_path / "exports")
    for bucket in EXPORT_BUCKETS:
        assert (folder / f"{bucket}.csv").exists()
    mobile = list(csv.DictReader((folder / "MOBILE.csv").open(encoding="utf-8-sig")))
    assert [r["name"] for r in mobile] == ["Alice", "Dan"]
    assert mobile[1]["pi_duplicate_of_row"] == "1"
    failed = list(csv.DictReader((folder / "FAILED.csv").open(encoding="utf-8-sig")))
    assert failed[0]["name"] == "Hal" and "timeout" in failed[0]["pi_error"]
    invalid = list(csv.DictReader((folder / "INVALID.csv").open(encoding="utf-8-sig")))
    assert invalid[0]["pi_input"] == "not a number"
    workbook = load_workbook(folder / "COMPLETE_RESULTS.xlsx", read_only=True)
    rows = list(workbook["Results"].iter_rows(values_only=True))
    header, body = list(rows[0]), rows[1:]
    assert header[:3] == ["name", "phone", "city"]
    assert [r[0] for r in body] == [r[0] for r in SAMPLE_ROWS]
    assert body[1][header.index("pi_classification")] == "LANDLINE"
    summary = {r[0] for r in workbook["Summary"].iter_rows(min_row=2, values_only=True)}
    assert summary >= set(EXPORT_BUCKETS)
    workbook.close()


def test_failed_rows_retried_on_resume(tmp_path, make_engine):
    engine, client, job_id, _ = run_sample(tmp_path, make_engine)
    client.responses["+18005551234"] = "toll free"
    summary = BulkProcessor(engine).run(job_id)
    assert summary.api_calls == 1
    assert summary.buckets["FAILED"] == 0 and summary.buckets["OTHER"] == 2


def test_auth_failure_pauses_job_and_keeps_pending(tmp_path, make_engine):
    source = tmp_path / "in.csv"
    write_csv(source, SAMPLE_ROWS)
    engine = make_engine(FakeClient(error=AuthenticationError("bad key")))
    frame = load_file(source)
    job_id = create_job(engine, prepare_job(frame, "phone", str(source)))
    with pytest.raises(AuthenticationError):
        BulkProcessor(engine).run(job_id)
    job = engine.db.get_job(job_id)
    assert job["status"] == "paused" and "bad key" in job["error"]
    counts = engine.db.record_status_counts(job_id)
    assert counts["pending"] == 7 and "failed" not in counts
    assert engine.db.cached_result("+16502530000", 30) is None


def test_interrupted_job_recovery(tmp_path, make_engine, db):
    source = tmp_path / "in.csv"
    write_csv(source, SAMPLE_ROWS)
    stop = threading.Event()
    client = FakeClient(NUMBERS)
    engine = make_engine(client, batch_size=2, concurrency=1)
    frame = load_file(source)
    job_id = create_job(engine, prepare_job(frame, "phone", str(source)))

    def progress(done, total, _):
        if done >= 2:
            stop.set()

    first = BulkProcessor(engine).run(job_id, progress=progress, stop_event=stop)
    assert first.status == "interrupted"
    assert db.get_job(job_id)["status"] == "interrupted"
    assert job_id in [j["id"] for j in db.resumable_jobs()]
    done_before = len(client.calls)
    assert 0 < done_before < 6
    second = BulkProcessor(engine).run(job_id)
    assert second.status == "completed"
    assert len(client.calls) == 6
    assert sorted(client.calls) == sorted(set(client.calls))


def test_stale_running_job_marked_interrupted(tmp_path, make_engine, db):
    source = tmp_path / "in.txt"
    source.write_text("6502530000\n", encoding="utf-8")
    engine = make_engine()
    job_id = create_job(engine, prepare_job(load_file(source), "phone_number", str(source)))
    db.update_job(job_id, status="running")
    assert db.mark_stale_running_jobs() == 1
    assert db.get_job(job_id)["status"] == "interrupted"


def test_bucket_exports_use_latest_success(tmp_path, make_engine):
    engine, _, _, _ = run_sample(tmp_path, make_engine)
    path, count = exporter.export_bucket_numbers(engine.db, "MOBILE", tmp_path / "out")
    assert count == 1
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert rows[0]["e164"] == "+16502530000"
    voip_path, voip_count = exporter.export_bucket_numbers(engine.db, "VOIP", tmp_path / "out")
    assert voip_count == 1
    other_path, other_count = exporter.export_bucket_numbers(engine.db, "OTHER", tmp_path / "out")
    assert other_count == 1


def test_original_record_stored_verbatim(tmp_path, make_engine):
    engine, _, job_id, _ = run_sample(tmp_path, make_engine)
    records = engine.db.job_records(job_id)
    assert json.loads(records[2]["raw_json"]) == {"name": "Carol", "phone": "not a number", "city": "LA"}


def test_keyboard_interrupt_saves_progress(tmp_path, make_engine, db):
    source = tmp_path / "in.csv"
    write_csv(source, SAMPLE_ROWS)
    client = FakeClient(NUMBERS)
    engine = make_engine(client, batch_size=1, concurrency=1)
    job_id = create_job(engine, prepare_job(load_file(source), "phone", str(source)))

    def progress(done, total, _):
        if done == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        BulkProcessor(engine).run(job_id, progress=progress)
    assert db.get_job(job_id)["status"] == "interrupted"
    assert db.record_status_counts(job_id).get("done", 0) >= 2
    assert BulkProcessor(engine).run(job_id).status == "completed"


def test_csv_with_quoted_commas_and_ragged_rows(tmp_path):
    source = tmp_path / "in.csv"
    source.write_text('name,phone,note\n"Doe, Jane",6502530000\nB,2125551234,"x, y",extra\n', encoding="utf-8")
    table = load_file(source)
    assert table.columns == ["name", "phone", "note", "column_4"]
    assert table.rows[0]["name"] == "Doe, Jane" and table.rows[0]["note"] == ""


def test_formula_like_values_written_as_text(tmp_path, make_engine):
    source = tmp_path / "in.csv"
    source.write_text("name,phone\n=HYPERLINK(1),6502530000\n", encoding="utf-8")
    engine = make_engine(FakeClient(NUMBERS))
    job_id = create_job(engine, prepare_job(load_file(source), "phone", str(source)))
    BulkProcessor(engine).run(job_id)
    folder = exporter.export_job(engine.db, job_id, tmp_path / "exports")
    workbook = load_workbook(folder / "COMPLETE_RESULTS.xlsx")
    cell = workbook["Results"]["A2"]
    assert cell.value == "=HYPERLINK(1)" and cell.data_type == "s"
