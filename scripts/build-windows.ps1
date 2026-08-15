# Build the Windows onedir app: dist\Piczop\Piczop.exe
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment .venv ..."
    python -m venv .venv
}

& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")
& $VenvPython (Join-Path $Root "scripts\generate_icon.py")
& $VenvPython -m PyInstaller --noconfirm (Join-Path $Root "piczop.spec")

$Exe = Join-Path $Root "dist\Piczop\Piczop.exe"
if (-not (Test-Path $Exe)) {
    throw "Build finished but $Exe was not found."
}

$Lib = Join-Path $Root "dist\Piczop\PiczopLibrary"
$Template = Join-Path $Root "assets\PiczopLibrary"
New-Item -ItemType Directory -Force -Path $Lib | Out-Null
foreach ($name in @("photos", "videos", "thumbs", "review", "trash")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Lib $name) | Out-Null
}
if (Test-Path $Template) {
    Copy-Item -Path (Join-Path $Template "*") -Destination $Lib -Recurse -Force
}

Write-Host "Built $Exe"
Write-Host "First-run library folder (when writable): $Lib"
Write-Host "If the app dir is read-only (e.g. Program Files), library uses %LOCALAPPDATA%\Piczop\PiczopLibrary."
Write-Host "Portable: copy the entire dist\Piczop folder to a USB stick."
Write-Host "Installer: powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1"
