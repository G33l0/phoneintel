# PHONEINTEL for Android

This folder contains a native Android version built with Kivy and packaged with buildozer /
python-for-android. It reuses the same engine modules as the terminal app (validator,
classifier, Telnyx client, database, bulk processor, exporter).

The Lookup screen also offers a **Free offline check** (no API key, 2/day) that validates format, region and a line-type estimate from bundled numbering-plan data without contacting Telnyx.

**Screens:** Home (overview stats, line-type breakdown), Lookup, Bulk (pick a CSV/XLSX/TXT
file, confirm the column, review the cost estimate, run, stop/resume), History (search, details,
export Mobile/Landline/VoIP/Other) and Settings (API key, connection test, engine settings).
The layout adapts to the screen: a bottom bar on phones, a side rail on tablets and in landscape,
and content capped at a readable width.

* Files are opened through Android's system file picker (Storage Access Framework), so the app
  needs no storage permission on Android 10+.
* Exports are saved to `Download/PHONEINTEL/` through MediaStore and can be shared from the app.
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
in the app. The design puts a strong ownership proof in front of any message access:

1. On first launch the app mints an anonymous **18-digit account ID** (no email or phone).
   It is the user's only credential, shown in Settings, stored on-device; only a salted hash
   is ever persisted (`identity.py`).
2. The user enters a number their business owns and requests hosting. The app shows a
   **one-time 6-digit code, visible only in that account's session**.
3. An operator calls the number. Whoever answers must read the code back. The operator
   confirms it from the admin side (`tools/operator_verify.py`). A match proves the person
   who answers the line and the app account are the same party - i.e. the account controls
   the line. Reading a code shown only in-app back over a call is the binding an interception
   attacker cannot satisfy.
4. Only then does the number become **verified**, and only then is any inbound message for it
   stored or shown - and only to the owning account.

Security properties, enforced in code and covered by tests (`tests/test_sms_hosting.py`,
`tests/test_hosting_service.py`):

* Inbound messages are retrievable **only** by the verified-owner account; every read joins
  through `hosted_numbers` with an ownership + verified-state check. There is no code path
  that returns a message without ownership.
* A number is owned by at most one account; a number already claimed cannot be taken over.
* Verification codes and account IDs are stored only as hashes; codes expire (15 min) and
  lock out after 5 wrong attempts; a code is bound to the number it was issued for.
* The app user cannot self-verify - `confirm_ownership` is operator-only and absent from the
  app-facing facade. Releasing a number hard-deletes it and its messages.

**Going live** needs operator-side infrastructure that is out of scope for the app build:
the Telnyx messaging/number-hosting integration (`telnyx_messaging.py`, mocked in tests) with
the **Letter of Authorization Telnyx requires to text-enable a number**, a public inbound-SMS
webhook, and the operator verification running in a secured admin service rather than the
bundled CLI. Telnyx credentials stay operator-side; users never see or enter an API key.

### Engine code

`android/app/` contains its own copy of the engine modules from `../terminal`
(`config.py`, `validator.py`, `classifier.py`, `telnyx_client.py`, `engine.py`, `database.py`,
`bulk_processor.py`, `exporter.py`), so this folder builds on its own. After changing the engine
in `terminal/`, run `python android/sync_core.py`; CI fails if the copies differ
(`python android/sync_core.py --check`).

### Building locally (Linux / WSL)

```sh
pip install buildozer==1.6.0
sudo apt install -y git zip unzip openjdk-17-jdk autoconf automake libtool pkg-config cmake \
    build-essential zlib1g-dev libncurses-dev libffi-dev libssl-dev
cd android && PIP_NO_BINARY=charset-normalizer buildozer android debug
```

The APK appears in `android/bin/`. To run the Kivy UI on a desktop for development:
`pip install kivy==2.3.1 -r terminal/requirements.txt && python android/app/main.py`.
Service tests: `cd android && python -m pytest tests`.

The logo source is `android/design/logo.svg`; `android/design/render.js` regenerates the icon,
adaptive icon layers and splash screen. Fonts: JetBrains Mono (SIL OFL 1.1) and Material Icons
(Apache 2.0).

