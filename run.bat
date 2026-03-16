@echo off
:: NeoView launcher for Windows
:: Creates a virtualenv on first run, then launches the app.

set VENV=%~dp0.venv

if not exist "%VENV%\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv "%VENV%"
    call "%VENV%\Scripts\activate.bat"
    pip install -e ".[dev]"
) else (
    call "%VENV%\Scripts\activate.bat"
)

neoview %*
