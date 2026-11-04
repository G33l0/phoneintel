#!/usr/bin/env sh
# PHONEINTEL launcher for Android Termux and Linux terminals: ./phoneintel.sh
# First run creates a private virtual environment in .venv and installs requirements.
set -e
cd "$(dirname "$0")"

is_termux() {
    [ -n "${TERMUX_VERSION:-}" ] || case "${PREFIX:-}" in *com.termux*) return 0 ;; *) return 1 ;; esac
}

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

if [ ! -x .venv/bin/python ]; then
    if ! PYTHON=$(find_python); then
        echo "[PHONEINTEL] Python 3.11 or newer was not found."
        if is_termux; then
            echo "             Run: pkg update && pkg install python"
        else
            echo "             Install python3 (3.11+) and python3-venv with your package manager."
        fi
        exit 1
    fi
    echo "[PHONEINTEL] Creating virtual environment in .venv ..."
    if ! "$PYTHON" -m venv .venv; then
        echo "[PHONEINTEL] Could not create a virtual environment."
        is_termux || echo "             On Debian/Ubuntu run: sudo apt install python3-venv"
        rm -rf .venv
        exit 1
    fi
fi

if ! cmp -s requirements.txt .venv/requirements.installed; then
    echo "[PHONEINTEL] Installing requirements ..."
    .venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
    .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
    cp requirements.txt .venv/requirements.installed
fi

exec .venv/bin/python main.py "$@"
