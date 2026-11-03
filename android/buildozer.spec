[app]
title = PHONEINTEL
package.name = phoneintel
package.domain = io.github.g33l0
source.dir = app
source.include_exts = py,kv,png,ttf,txt
source.exclude_dirs = __pycache__
source.exclude_patterns = picked/*
version = 1.1.0

# Pure-Python dependencies only. The kivy recipe already brings requests, urllib3, idna,
# certifi and chardet. phonenumberslite provides the same "phonenumbers" API without the
# large geocoder/carrier datasets. charset-normalizer is listed explicitly so p4a does not
# pick its Android binary wheel (which the host pip cannot install); build with
# PIP_NO_BINARY=charset-normalizer so its pure-Python sdist is used.
requirements = python3,kivy==2.3.1,pyjnius,android,sqlite3,openssl,charset-normalizer==3.5.2,phonenumberslite==9.0.42,python-dotenv==1.2.4,openpyxl==3.1.5,et_xmlfile==2.0.0

icon.filename = %(source.dir)s/assets/icon.png
icon.adaptive_foreground.filename = %(source.dir)s/assets/adaptive_fg.png
icon.adaptive_background.filename = %(source.dir)s/assets/adaptive_bg.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #030604

orientation = portrait, landscape, portrait-reverse, landscape-reverse
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE, (name=android.permission.WRITE_EXTERNAL_STORAGE;maxSdkVersion=28)
android.api = 34
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = False
android.accept_sdk_license = True
android.enable_androidx = True
android.debug_artifact = apk
android.release_artifact = apk

p4a.branch = v2026.05.09
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 0
