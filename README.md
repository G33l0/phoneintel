# PHONEINTEL v1.0

Interactive terminal application for phone-number line-type intelligence, powered by the
official [Telnyx Number Lookup API](https://developers.telnyx.com/api/number-lookup).

PHONEINTEL validates and normalizes numbers to E.164, queries Telnyx for **carrier, line type and
portability only**, classifies the provider-reported line type, stores everything in SQLite and
exports separated result files. It runs from the same source code on Windows CMD, Windows
PowerShell, Android Termux and Linux terminals.

```
python main.py
```

The first screen is the PHONEINTEL main menu.

---

## Features

| # | Menu option | What it does |
|---|-------------|--------------|
| 1 | Single Phone Number Lookup | Validate, normalize and look up one number (uses cache; can force a fresh lookup) |
| 2 | Bulk Phone Number Classification | Process CSV / XLSX / TXT files, resume interrupted jobs |
| 3 | View Previous Results | Recent lookups, search, bulk job history/details, re-export a job |
| 4 | Export Mobile Numbers | Latest successful MOBILE result per number → CSV |
| 5 | Export Landline Numbers | LANDLINE → CSV |
| 6 | Export VoIP Numbers | FIXED_VOIP, NON_FIXED_VOIP, OTHER_VOIP → CSV |
| 7 | Export Other Numbers | TOLL_FREE and OTHER → CSV |
| 8 | View Processing Statistics | Totals, statuses, classification breakdown, recent jobs |
| 9 | Telnyx API Configuration | Set/remove API key (hidden input), tune concurrency, throttle, cache, cost |
| 10 | Test API Connection | Calls `GET /v2/balance` to verify the key (no lookup charge) |
| 11 | Application Information | Version, paths, data policy |
| 12 | Exit | |

### Classifications

`MOBILE`, `LANDLINE`, `FIXED_VOIP`, `NON_FIXED_VOIP`, `OTHER_VOIP`, `TOLL_FREE`, `OTHER`,
`UNKNOWN`, `INVALID` (plus lookup status `FAILED` for requests that did not complete).

* The line type comes from Telnyx `carrier.type`; if that is absent, `portability.line_type`
  is used, and the source field is recorded.
* A line type is **never inferred** from area codes or prefixes. If Telnyx returns no type, or an
  ambiguous one such as `fixed line or mobile`, the result is `UNKNOWN`.
* Numbers that fail local validation are `INVALID` and are never sent to the API. Numbers that
  Telnyx reports as `valid_number: false` are also `INVALID`.
* Network, rate-limit and API errors produce `FAILED` results. They are never cached and are
  retried when a bulk job is resumed.

### Bulk processing

* Input: `.csv` (comma, semicolon, tab or pipe; header or headerless), `.xlsx` (first sheet),
  `.txt` (one number per line).
* Automatic phone-column detection (column name hints + validation ratio) with manual override.
* E.164 normalization, validation and duplicate detection — each unique number is looked up once.
* A cost estimate (rows, invalid, duplicates, cached, API lookups needed, estimated USD) is shown,
  and the job only starts after you confirm.
* Configurable concurrency, global requests-per-second throttle, retries with exponential backoff,
  `Retry-After` support on HTTP 429 (which also pauses all workers).
* Every row is written to SQLite before processing; results are committed per batch.
  Ctrl+C, a crash or an authentication failure leaves the job resumable from option 2.

Each job writes a folder `exports/job_<id>_<timestamp>/` containing:

```
MOBILE.csv  LANDLINE.csv  VOIP.csv  OTHER.csv  UNKNOWN.csv  INVALID.csv  FAILED.csv
COMPLETE_RESULTS.xlsx   (sheets: Results, Summary)
```

All original columns are preserved in their original order, rows keep their input order, and
PHONEINTEL appends `pi_*` columns (row, E.164, country, carrier, line type, classification,
portability, status, duplicate-of row, error, timestamp). If a job is still incomplete, a
`PENDING.csv` is also written.

### Data and privacy

* Requests use `GET https://api.telnyx.com/v2/number_lookup/{number}?type=carrier` with
  `Authorization: Bearer <key>`. Caller-name (CNAM) lookups are never requested.
* Only whitelisted portability fields are stored (ported status/date, line type, SPID/carrier,
  OCN, LRN). City/state fields are discarded.
* The API key lives in a local `.env` file (permission `600` on Linux/Termux), is entered with
  hidden input, and is only ever displayed masked (e.g. `KEY0********abcd`). `.env`, `data/` and
  `exports/` are git-ignored.

---

## Installation

Requires **Python 3.11+**. No administrator/root privileges are needed.

### Windows (CMD)

```bat
git clone https://github.com/g33l0/phoneintel.git
cd phoneintel
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python main.py
```

### Windows (PowerShell)

```powershell
git clone https://github.com/g33l0/phoneintel.git
cd phoneintel
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

If PowerShell blocks the activation script, allow it for your user only (no admin needed):
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Windows Terminal gives the best colours;
classic CMD also works.

When asked for a file path you can paste a path from Explorer's "Copy as path" — surrounding
quotes and a PowerShell drag-and-drop `& '...'` prefix are stripped automatically.

### Android (Termux)

Install Termux from F-Droid or GitHub (the Play Store build is outdated), then:

```sh
pkg update && pkg upgrade
pkg install python git
termux-setup-storage          # optional: lets you read files from /sdcard
git clone https://github.com/g33l0/phoneintel.git
cd phoneintel
pip install -r requirements.txt
python main.py
```

`pandas` may have to compile on Termux, which is slow. If `pip install` fails on pandas/numpy,
install the prebuilt packages and retry:

```sh
pkg install tur-repo
pkg install python-numpy python-pandas
pip install requests python-dotenv rich phonenumbers openpyxl
```

Files from shared storage are reachable as e.g. `/sdcard/Download/numbers.csv` or
`~/storage/downloads/numbers.csv` after `termux-setup-storage`.

### Linux

```sh
git clone https://github.com/g33l0/phoneintel.git
cd phoneintel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## Usage

1. Run `python main.py`.
2. Choose **9** → **K** and paste your Telnyx API key (create one in the Telnyx Mission Control
   portal under *API Keys*). Alternatively copy `.env.example` to `.env` and edit it, or set the
   `TELNYX_API_KEY` environment variable.
3. Choose **10** to confirm the key is accepted.
4. Choose **1** for a single number, e.g. `(650) 253-0000` or `+44 20 7946 0958`. Numbers without
   a `+` prefix use the default region (`US`, configurable in option 9).
5. Choose **2** for a file. Confirm the detected column, decide whether to force fresh lookups,
   review the estimate and confirm. Press **Ctrl+C** at any time to stop; progress is saved and the
   job appears as resumable the next time you choose option 2.
6. Options **4–7** export the latest successful classification for every number in the database.

### Settings (option 9)

| Setting | Default | Meaning |
|---------|---------|---------|
| default_region | US | Region for numbers without `+` |
| concurrency | 4 | Parallel worker threads (1–20) |
| requests_per_second | 5 | Global API throttle (0.2–50) |
| max_retries | 3 | Retries for 429 / 5xx / network errors |
| request_timeout | 15 | HTTP timeout in seconds |
| cache_days | 30 | Successful results reused for this many days (0 disables cache) |
| batch_size | 100 | Numbers committed to SQLite per batch |
| cost_per_lookup | 0.0025 | USD used for cost estimates — **verify against your Telnyx pricing** |

Keep `requests_per_second` within the rate limit of your Telnyx account. On HTTP 429 PHONEINTEL
waits for `Retry-After` (or backs off exponentially) before continuing.

`PHONEINTEL_HOME=/some/dir` relocates `.env`, `data/` and `exports/` (useful for Termux shared
storage or per-project workspaces).

---

## Architecture

```
main.py            entry point (python main.py)
interface.py       Rich terminal UI — the only module that imports Rich
config.py          paths, .env handling, setting defaults and validation
validator.py       phonenumbers-based validation and E.164 normalization
classifier.py      LookupResult model, Telnyx response parsing, line-type mapping, export buckets
telnyx_client.py   HTTP client: auth, throttling, retries, error types
engine.py          PhoneIntelEngine: validate → cache → Telnyx → classify → persist
bulk_processor.py  file loading, column detection, duplicates, estimates, resumable jobs
database.py        SQLite schema and queries
exporter.py        CSV / XLSX export
tests/             pytest suite with mocked HTTP responses
```

SQLite tables: `phone_numbers`, `lookup_results`, `bulk_jobs`, `job_records`, `job_statistics`,
`settings`.

The engine has no terminal dependency, so it can be reused from a FastAPI service, a Kivy app
or other Python code:

```python
from config import AppConfig
from engine import PhoneIntelEngine

engine = PhoneIntelEngine.from_config(AppConfig())
result = engine.lookup("+16502530000")
print(result.classification, result.carrier, result.to_dict())
```

`BulkProcessor.run()` accepts a `progress(done, total, result)` callback and a
`threading.Event` to stop a job, so any front end can drive it.

**Android/web note:** do not ship the Telnyx key inside an APK or browser bundle. Run the engine
behind your own backend (e.g. FastAPI or the Laravel site) and let mobile/web clients call that
backend.

---

## Tests

```sh
pip install -r requirements-dev.txt
python -m pytest
```

All Telnyx calls in the test suite are mocked. The suite covers validation, E.164 normalization,
classification mapping, Telnyx client behaviour (auth errors, 429 with `Retry-After`, 5xx retries,
network failures, malformed JSON), CSV/XLSX/TXT processing, duplicate detection, SQLite persistence
and cache expiry, interrupted-job recovery, exports, and driving the interactive menu end to end.
