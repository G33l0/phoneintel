@echo off
rem PHONEINTEL launcher for Windows CMD and PowerShell (.\phoneintel.bat)
rem First run creates a private virtual environment in .venv and installs requirements.
setlocal EnableExtensions
cd /d "%~dp0"
title PHONEINTEL
set "PYTHONUTF8=1"
set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    call :find_python || goto :no_python
    echo [PHONEINTEL] Creating virtual environment in .venv ...
    "%PYTHON_EXE%" -m venv .venv || goto :setup_failed
)

fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
    echo [PHONEINTEL] Installing requirements ...
    "%VENV_PY%" -m pip install --disable-pip-version-check -q --upgrade pip || goto :setup_failed
    "%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :setup_failed
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

"%VENV_PY%" main.py %*
exit /b %errorlevel%

:find_python
set "PYTHON_EXE="
for %%V in (3.14 3.13 3.12 3.11) do (
    if not defined PYTHON_EXE (
        for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
    )
)
if not defined PYTHON_EXE (
    for /f "delims=" %%P in ('python -c "import sys; print(sys.executable) if sys.version_info >= (3, 11) else exit(1)" 2^>nul') do set "PYTHON_EXE=%%P"
)
if not defined PYTHON_EXE exit /b 1
exit /b 0

:no_python
echo [PHONEINTEL] Python 3.11 or newer was not found.
echo             Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
pause
exit /b 1

:setup_failed
echo [PHONEINTEL] Setup failed. Check your internet connection, then delete the .venv folder and try again.
pause
exit /b 1
