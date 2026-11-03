# PHONEINTEL for Android

This folder contains a native Android version built with Kivy and packaged with buildozer /
python-for-android. It reuses the same engine modules as the terminal app (validator,
classifier, Telnyx client, database, bulk processor, exporter).

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
cd android && buildozer android debug
```

The APK appears in `android/bin/`. To run the Kivy UI on a desktop for development:
`pip install kivy==2.3.1 -r terminal/requirements.txt && python android/app/main.py`.
Service tests: `cd android && python -m pytest tests`.

The logo source is `android/design/logo.svg`; `android/design/render.js` regenerates the icon,
adaptive icon layers and splash screen. Fonts: JetBrains Mono (SIL OFL 1.1) and Material Icons
(Apache 2.0).

