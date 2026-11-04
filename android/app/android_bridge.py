import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.utils import platform

IS_ANDROID = platform == "android"
PICK_REQUEST = 4207
RESULT_OK = -1
SUPPORTED = (".csv", ".xlsx", ".txt")
MIME_EXT = {
    "text/csv": ".csv",
    "text/comma-separated-values": ".csv",
    "application/csv": ".csv",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}
EXT_MIME = {
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

if IS_ANDROID:
    from android import activity, mActivity  # noqa: F401
    from android.runnable import run_on_ui_thread
    from jnius import autoclass, cast

    Intent = autoclass("android.content.Intent")
    Version = autoclass("android.os.Build$VERSION")
    OpenableColumns = autoclass("android.provider.OpenableColumns")
    JString = autoclass("java.lang.String")
else:
    def run_on_ui_thread(func):
        return func


@dataclass
class SavedFile:
    name: str
    location: str
    uri: object = None
    mime: str = "application/octet-stream"


def mime_for(path: Path) -> str:
    return EXT_MIME.get(Path(path).suffix.lower(), "application/octet-stream")


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\- ]+", "_", name).strip() or "input"
    return name[:120]


class AndroidBridge:
    def __init__(self, cache_dir: Path, desktop_downloads: Path | None = None):
        self.cache_dir = Path(cache_dir)
        self.desktop_downloads = desktop_downloads or Path.home() / "Downloads"
        self._pick_callback = None
        self._pick_error = None
        if IS_ANDROID:
            activity.bind(on_activity_result=self._on_activity_result)

    @property
    def can_share(self) -> bool:
        return IS_ANDROID and Version.SDK_INT >= 29

    # ---------- picking ----------

    def pick_file(self, on_picked, on_error) -> bool:
        if not IS_ANDROID:
            return False
        self._pick_callback, self._pick_error = on_picked, on_error
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("*/*")
        mActivity.startActivityForResult(intent, PICK_REQUEST)
        return True

    def _on_activity_result(self, request_code, result_code, intent):
        if request_code != PICK_REQUEST:
            return
        callback, error = self._pick_callback, self._pick_error
        self._pick_callback = self._pick_error = None
        if result_code != RESULT_OK or intent is None or intent.getData() is None:
            return
        try:
            path = self._copy_to_cache(intent.getData())
        except Exception as exc:
            Logger.exception("PhoneIntel: file copy failed")
            message = str(exc) or "Could not open the selected file"
            if error:
                Clock.schedule_once(lambda *_: error(message))
            return
        if callback:
            Clock.schedule_once(lambda *_: callback(path))

    def _copy_to_cache(self, uri) -> Path:
        resolver = mActivity.getContentResolver()
        name = self._display_name(resolver, uri) or "input"
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED:
            mapped = MIME_EXT.get(str(resolver.getType(uri) or ""))
            if not mapped:
                raise ValueError("Unsupported file. Choose a CSV, XLSX or TXT file.")
            name, suffix = name + mapped, mapped
        target_dir = self.cache_dir / "picked"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_name(name)
        descriptor = resolver.openFileDescriptor(uri, "r")
        fd = descriptor.detachFd()
        with os.fdopen(fd, "rb") as source, target.open("wb") as sink:
            shutil.copyfileobj(source, sink, 1024 * 256)
        return target

    @staticmethod
    def _display_name(resolver, uri) -> str | None:
        cursor = resolver.query(uri, None, None, None, None)
        if cursor is None:
            return None
        try:
            if cursor.moveToFirst():
                index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if index >= 0:
                    return cursor.getString(index)
        finally:
            cursor.close()
        return None

    # ---------- saving ----------

    def save_files(self, files: list[Path], subfolder: str, on_done, on_error) -> None:
        files = [Path(f) for f in files]
        if not IS_ANDROID:
            return self._run(lambda: [self._save_desktop(f, subfolder) for f in files], on_done, on_error)
        if Version.SDK_INT >= 29:
            return self._run(lambda: [self._save_mediastore(f, subfolder) for f in files], on_done, on_error)
        self._with_legacy_permission(
            lambda: self._run(lambda: [self._save_legacy(f, subfolder) for f in files], on_done, on_error),
            lambda: on_error("Storage permission is required to save files"))

    @staticmethod
    def _run(task, on_done, on_error) -> None:
        try:
            result = task()
        except Exception as exc:
            Logger.exception("PhoneIntel: save failed")
            on_error(str(exc) or "Could not save files")
            return
        on_done(result)

    def _save_desktop(self, path: Path, subfolder: str) -> SavedFile:
        target_dir = self.desktop_downloads / "PHONEINTEL" / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        shutil.copyfile(path, target)
        return SavedFile(path.name, str(target), None, mime_for(path))

    def _save_mediastore(self, path: Path, subfolder: str) -> SavedFile:
        ContentValues = autoclass("android.content.ContentValues")
        Downloads = autoclass("android.provider.MediaStore$Downloads")
        Columns = autoclass("android.provider.MediaStore$MediaColumns")
        relative = f"Download/PHONEINTEL/{subfolder}".rstrip("/")
        values = ContentValues()
        values.put(Columns.DISPLAY_NAME, JString(path.name))
        values.put(Columns.MIME_TYPE, JString(mime_for(path)))
        values.put(Columns.RELATIVE_PATH, JString(relative))
        resolver = mActivity.getContentResolver()
        uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            raise OSError("Android refused to create the file in Downloads")
        descriptor = resolver.openFileDescriptor(uri, "w")
        fd = descriptor.detachFd()
        with path.open("rb") as source, os.fdopen(fd, "wb") as sink:
            shutil.copyfileobj(source, sink, 1024 * 256)
        return SavedFile(path.name, f"{relative}/{path.name}", uri, mime_for(path))

    def _save_legacy(self, path: Path, subfolder: str) -> SavedFile:
        Environment = autoclass("android.os.Environment")
        base = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).getAbsolutePath()
        target_dir = Path(base) / "PHONEINTEL" / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        shutil.copyfile(path, target)
        return SavedFile(path.name, f"Download/PHONEINTEL/{subfolder}/{path.name}", None, mime_for(path))

    @staticmethod
    def _with_legacy_permission(granted, denied) -> None:
        from android.permissions import Permission, check_permission, request_permissions
        permission = Permission.WRITE_EXTERNAL_STORAGE
        if check_permission(permission):
            return granted()

        def handle(_permissions, results):
            Clock.schedule_once(lambda *_: granted() if results and all(results) else denied())

        request_permissions([permission], handle)

    # ---------- sharing / system ----------

    def share(self, saved: SavedFile, title: str = "Share results") -> bool:
        if not self.can_share or saved.uri is None:
            return False
        intent = Intent(Intent.ACTION_SEND)
        intent.setType(saved.mime)
        intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", saved.uri))
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        chooser = Intent.createChooser(intent, cast("java.lang.CharSequence", JString(title)))
        mActivity.startActivity(chooser)
        return True

    @staticmethod
    def minimize() -> bool:
        if not IS_ANDROID:
            return False
        mActivity.moveTaskToBack(True)
        return True

    @staticmethod
    @run_on_ui_thread
    def style_system_bars(status_hex: str, nav_hex: str) -> None:
        if not IS_ANDROID:
            return
        try:
            Color = autoclass("android.graphics.Color")
            LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
            window = mActivity.getWindow()
            window.clearFlags(LayoutParams.FLAG_TRANSLUCENT_STATUS)
            window.addFlags(LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS)
            window.setStatusBarColor(Color.parseColor(status_hex))
            window.setNavigationBarColor(Color.parseColor(nav_hex))
        except Exception:
            Logger.exception("PhoneIntel: could not style system bars")
