# Build dist\Piczop-Setup.exe via Inno Setup 6 (ISCC).
# Ensures dist\Piczop exists (runs build-windows.ps1 if needed), finds or installs ISCC.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Find-ISCC {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "C:\ProgramData\chocolatey\bin\ISCC.exe"
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            return (Resolve-Path -LiteralPath $path).Path
        }
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }
    return $null
}

function Install-InnoSetup {
    # IMPORTANT: do not let installer stdout become this function's return value.
    Write-Host "Inno Setup 6 not found. Trying to install..."

    $choco = Get-Command choco.exe -ErrorAction SilentlyContinue
    if ($choco) {
        Write-Host "Installing Inno Setup via Chocolatey..."
        & choco.exe install innosetup -y --no-progress --confirm *> $null
        $found = Find-ISCC
        if ($found) { return $found }
    }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Installing Inno Setup via winget..."
        & winget.exe install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements *> $null
        $found = Find-ISCC
        if ($found) { return $found }
    }

    $tmp = Join-Path $env:TEMP "innosetup-installer.exe"
    $urls = @(
        "https://jrsoftware.org/download.php/is.exe",
        "https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/innosetup-6.4.3.exe"
    )
    foreach ($url in $urls) {
        try {
            Write-Host "Downloading Inno Setup from $url ..."
            Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
            if ((Test-Path -LiteralPath $tmp) -and ((Get-Item -LiteralPath $tmp).Length -gt 1MB)) {
                Write-Host "Running Inno Setup silent install..."
                $proc = Start-Process -FilePath $tmp -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=`"${env:ProgramFiles(x86)}\Inno Setup 6`"" -Wait -PassThru
                if ($null -ne $proc.ExitCode -and $proc.ExitCode -ne 0) {
                    Write-Warning "Installer exit code: $($proc.ExitCode)"
                }
                $found = Find-ISCC
                if ($found) { return $found }
            }
        }
        catch {
            Write-Warning "Download/install failed from $url : $_"
        }
    }
    return $null
}

$Exe = Join-Path $Root "dist\Piczop\Piczop.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    Write-Host "dist\Piczop missing - running build-windows.ps1 ..."
    & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\build-windows.ps1")
    if (-not (Test-Path -LiteralPath $Exe)) {
        throw "Build finished but $Exe was not found."
    }
}
else {
    Write-Host "Using existing $Exe"
}

$Iss = Join-Path $Root "installer\piczop.iss"
if (-not (Test-Path -LiteralPath $Iss)) {
    throw "Missing $Iss"
}
if (-not (Test-Path -LiteralPath (Join-Path $Root "assets\piczop.ico"))) {
    throw "Missing assets\piczop.ico - run scripts\build-windows.ps1 first."
}

$Iscc = Find-ISCC
if (-not $Iscc) {
    # Capture only the returned path (suppress accidental pipeline noise).
    $Iscc = [string](Install-InnoSetup | Select-Object -Last 1)
    if ([string]::IsNullOrWhiteSpace($Iscc) -or -not (Test-Path -LiteralPath $Iscc)) {
        $Iscc = Find-ISCC
    }
}
if (-not $Iscc -or -not (Test-Path -LiteralPath $Iscc)) {
    Write-Host ""
    Write-Host "Could not install Inno Setup automatically."
    Write-Host "Install from https://jrsoftware.org/isinfo.php then re-run this script,"
    Write-Host "or compile manually:"
    Write-Host '  & "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" .\installer\piczop.iss'
    Write-Host ""
    Write-Host "Fallback (portable zip, no installer):"
    $zip = Join-Path $Root "dist\Piczop-Windows.zip"
    if (Test-Path -LiteralPath $zip) {
        Write-Host "  Already present: $zip"
    }
    else {
        Compress-Archive -Path (Join-Path $Root "dist\Piczop\*") -DestinationPath $zip -Force
        Write-Host "  Created: $zip"
    }
    throw "ISCC.exe not available - produced portable zip fallback only."
}

Write-Host "Compiling installer with $Iscc ..."
& $Iscc $Iss
if ($LASTEXITCODE -ne 0) {
    throw "ISCC failed with exit code $LASTEXITCODE"
}

$Setup = Join-Path $Root "dist\Piczop-Setup.exe"
if (-not (Test-Path -LiteralPath $Setup)) {
    throw "Expected output missing: $Setup"
}

$sizeMb = [math]::Round((Get-Item -LiteralPath $Setup).Length / 1MB, 1)
Write-Host "Built $Setup ($sizeMb MB)"
Write-Host "Install dir default: {autopf}\Piczop (Program Files when elevated; per-user Programs otherwise)."
Write-Host "Library: next to exe when writable; else %LOCALAPPDATA%\Piczop\PiczopLibrary."
