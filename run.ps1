# NeoView launcher for Windows (PowerShell)
# Creates a virtualenv on first run, then launches the app.

$VenvDir = Join-Path $PSScriptRoot ".venv"
$Activate = Join-Path $VenvDir "Scripts\Activate.ps1"

if (-not (Test-Path $Activate)) {
    Write-Host "Creating virtual environment..."
    python -m venv $VenvDir
    & $Activate
    pip install -e "$PSScriptRoot\.[dev]"
} else {
    & $Activate
}

neoview @args
