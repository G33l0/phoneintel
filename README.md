# PHONEINTEL v1.0

Phone-number line-type intelligence powered by the official
[Telnyx Number Lookup API](https://developers.telnyx.com/api-reference/number-lookup/lookup-phone-number-data).
It classifies numbers as mobile, landline, VoIP (fixed / non-fixed / other), toll-free, other,
unknown or invalid using carrier, line-type and portability data only.

The repository holds two independent apps:

| Folder | What it is | Runs on | Start with |
|--------|------------|---------|------------|
| [`terminal/`](terminal/README.md) | Interactive hacker-style terminal app (Rich) | Windows CMD, PowerShell, Android Termux, Linux, macOS | `phoneintel.bat` (Windows) / `./phoneintel.sh` (Termux, Linux) |
| [`android/`](android/README.md) | Native Android app (Kivy) packaged as an APK | Android 7.0+ | Install the APK from the CI artifact |

The apps also include a **free offline validation** tier (2/day, no API key) and the Android app adds **Business SMS** - receiving texts for a business line the user owns, gated behind a call-back ownership proof (see `android/README.md`).

Both apps include a **free offline validation** tier (2/day, no API key). The Android app also
adds **Business SMS** — receiving texts for a business line the user owns, gated behind a
call-back ownership proof (details in [`android/README.md`](android/README.md)).

Each folder is self-contained: you can copy `terminal/` to a PC or a Termux home directory
without anything from `android/`, and `android/` builds its APK without `terminal/`.

## Quick start

**Windows (CMD / PowerShell):** install Python 3.11+ from python.org, then
```bat
git clone https://github.com/g33l0/phoneintel.git
cd phoneintel\terminal
phoneintel.bat
```

**Android Termux:**
```sh
pkg install python git
git clone https://github.com/g33l0/phoneintel.git
cd phoneintel/terminal
./phoneintel.sh
```

**Android APK:** open the latest successful **PHONEINTEL CI** run under the repository's
*Actions* tab, download the `phoneintel-apk` artifact, unzip it and install the `.apk`.

Both apps ask for your Telnyx API key on first use and store it locally (a git-ignored `.env`
for the terminal app, app-private storage for the APK). No key is ever committed or bundled.

## Repository layout

```
terminal/            terminal app + engine + tests + launchers (phoneintel.bat, phoneintel.sh)
android/             Kivy app (app/), buildozer.spec, logo sources (design/), UI snapshot tool, tests
.github/workflows/   CI: tests on Linux and Windows, launcher smoke tests, UI render check, APK build
```
