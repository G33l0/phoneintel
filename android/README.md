# PHONEINTEL for Android

This folder contains a native Android version built with Kivy and packaged with buildozer /
python-for-android. It reuses the same engine modules as the terminal app (validator,
classifier, Telnyx client, database).

The Lookup screen also offers a **Free offline check** (no API key, 5/day) that validates format,
region and a line-type estimate from bundled numbering-plan data without contacting Telnyx.

**Screens:** Home (overview stats, line-type breakdown), Lookup (single number), SMS (Business
SMS hosting — see below), History (recent lookups, search) and Settings (account ID, API key,
connection test, engine settings). The layout adapts to the screen: a bottom bar on phones, a
side rail on tablets and in landscape, and content capped at a readable width.

* The API key is entered in the app and stored in the app's private storage. **No key is
  bundled in the APK**, and Android backups are disabled for the app.

### Getting the APK

Every pull request and push to `main` runs the **PHONEINTEL CI** workflow
(`.github/workflows/ci.yml`): tests (Linux + Windows) → UI render check → APK build. Download the
`phoneintel-apk` artifact from the workflow run, copy the `.apk` to your phone and install it
(allow "Install unknown apps" for your browser/file manager). It is a debug-signed APK for
sideloading, built for `arm64-v8a` and `armeabi-v7a`, Android 7.0+ (API 24).

### Business SMS (receive texts for a line you own)

The **Business SMS** screen lets a user receive inbound SMS for a business line *they own*,
in the app. Ownership is verified by the operator/super-admin, and the data gate is enforced
in code:

1. On first launch the app mints an anonymous **18-character account ID** (mixed letters and digits, ~93 bits; no email or phone).
   It is the user's only credential, shown in Settings, stored on-device; only a salted hash
   is ever persisted (`identity.py`).
2. The user enters a number their business owns and submits a hosting request. The number is
   `pending_verification`.
3. The **super-admin validates the business's Letter of Authorization (LOA)** for the line —
   the same proof the carrier (Telnyx) requires to host/text-enable a number — and records the
   verification from the admin side (`tools/operator_verify.py verify <e164> <loa-ref>`, the
   stand-in for the admin portal). The LOA reference and operator id are stored for audit.
4. Only then does the number become **verified**, and only then is any inbound message for it
   stored or shown — and only to the owning account.

Security properties, enforced in code and covered by tests (`tests/test_sms_hosting.py`,
`tests/test_hosting_service.py`):

* Inbound messages are retrievable **only** by the verified-owner account; every read joins
  through `hosted_numbers` with an ownership + verified-state check. There is no code path
  that returns a message without ownership.
* A number is owned by at most one account; a number already claimed cannot be taken over.
* Account IDs are stored only as hashes; verification requires an LOA reference and is recorded
  with the operator id and time.
* The app user cannot self-verify — `verify_ownership` is operator-only and absent from the
  app-facing facade. Releasing a number hard-deletes it and its messages.

See [`../SECURITY.md`](../SECURITY.md) for the full threat model, including why coins, pricing
and verification are server-authoritative and why no client can be made "uncrackable".

**Going live** needs operator-side infrastructure that is out of scope for the app build:
the Telnyx messaging/number-hosting integration (`telnyx_messaging.py`, mocked in tests) with
the **Letter of Authorization Telnyx requires to text-enable a number**, a public inbound-SMS
webhook (signature-verified), and the admin verification running in the secured portal rather
than the bundled CLI. Telnyx credentials stay operator-side; users never see or enter an API key.

### Super-admin configuration (fallback provider & SMS pricing)

Operator-only settings live in the `admin_settings` table and are edited through
`AdminConfig` (`admin_config.py`) - from the admin portal in a real deployment, or the
bundled `terminal/admin_tool.py` CLI. End users never see or change these.

* **Fallback validation provider**: the free offline validator is primary. If it is ever
  unavailable/errors and a provider (`twilio` or `telnyx`) is configured, the engine falls
  back to that provider for a carrier-grade line type. Note: provider line-type lookups are
  **billable** (Twilio Lookup line-type intelligence and Telnyx number lookup both charge per
  query) - only the offline validator is free. Provider credentials stay in the operator's
  environment (`TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`, `TELNYX_API_KEY`), never in the app.
* **SMS pricing / margins**: `billable = provider_cost * (1 + margin_percent/100)`, editable
  per direction. Defaults: **110%** margin on receiving, **200%** on sending (sending is off
  until `sms_send_enabled` is turned on and a provider that sends is wired up). Currency and
  both wholesale costs are editable too.

The free offline check **cannot reliably tell landline from wireless** in markets with number
portability (e.g. the US, where most geographic numbers resolve to "fixed line or mobile").
That distinction needs a real-time carrier lookup - the paid Telnyx path, or the configured
provider fallback.

### Engine code

`android/app/` contains its own copy of the engine modules from `../terminal`
(`config.py`, `validator.py`, `classifier.py`, `telnyx_client.py`, `engine.py`,
`free_validate.py`, `validation_provider.py`, `admin_config.py`, `database.py`), so this folder
builds on its own. After changing the engine in `terminal/`, run `python android/sync_core.py`;
CI fails if the copies differ (`python android/sync_core.py --check`).

### Building locally (Linux / WSL)

```sh
pip install buildozer==1.6.0
sudo apt install -y git zip unzip openjdk-17-jdk autoconf automake libtool pkg-config cmake \
    build-essential zlib1g-dev libncurses-dev libffi-dev libssl-dev
# constrain pip and charset-normalizer for the python-for-android build (see ci.yml)
printf 'pip<26.3\ncharset-normalizer<3\n' > /tmp/pi-constraints.txt
cd android && PIP_CONSTRAINT=/tmp/pi-constraints.txt buildozer android debug
```

The APK appears in `android/bin/`. To run the Kivy UI on a desktop for development:
`pip install kivy==2.3.1 -r terminal/requirements.txt && python android/app/main.py`.
Service tests: `cd android && python -m pytest tests`.

The logo source is `android/design/logo.svg`; `android/design/render.js` regenerates the icon,
adaptive icon layers and splash screen. Fonts: JetBrains Mono (SIL OFL 1.1) and Material Icons
(Apache 2.0).

