# Builds the Windows app and its installer, build\Award-Wallet-Setup.exe. GitHub runs this for each
# pull request and release; to build one yourself on a Windows PC, run this in PowerShell from this
# folder (the README's "Build it yourself" walks through it):
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
# With SKIP_TESTS=1 set, it skips the tests, as GitHub does after running them on their own.

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$AppName = "Award Wallet"
$Version = (Select-String -LiteralPath pyproject.toml -Pattern '^version = "(.*)"').Matches[0].Groups[1].Value

# Runs a program and stops the build when it fails, which PowerShell doesn't do by itself.
function Invoke-Program([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program $($Arguments -join ' ') failed (exit code $LASTEXITCODE)"
    }
}

if ($env:OS -ne "Windows_NT") {
    Write-Host "Build this on Windows: Setup.exe can only be made there."
    exit 1
}
$UvFolder = Join-Path $env:USERPROFILE ".local\bin"
if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath (Join-Path $UvFolder "uv.exe"))) {
    # uv's installer puts it here, and a PowerShell window opened before the install doesn't look there.
    $env:PATH = "$UvFolder;$env:PATH"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv is missing. Install it with this line, then open a new PowerShell window and try again:"
    Write-Host '  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    exit 1
}

Write-Host "==> Installing dependencies"
Invoke-Program uv @("sync", "--locked", "--extra", "desktop")

if ($env:SKIP_TESTS -ne "1") {
    Write-Host "==> Running tests"
    Invoke-Program uv @("run", "pytest")
}

Write-Host "==> Building $AppName $Version"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -LiteralPath "build\dist", "build\work"
Invoke-Program uv @(
    "run", "pyinstaller", "--noconfirm", "--clean", "--windowed",
    "--name", $AppName,
    "--icon", "$PWD\packaging\AppIcon.ico",
    "--collect-data", "award_wallet",
    "--add-data", "$PWD\src\award_wallet\migrations;award_wallet\migrations",
    "--collect-submodules", "award_wallet",
    "--collect-submodules", "uvicorn",
    "--distpath", "build\dist", "--workpath", "build\work", "--specpath", "build",
    "packaging\award_wallet_app.py"
)

Write-Host "==> Checking that the app starts"
# A new, empty data folder and a hidden Chrome, never your own data: see self_test in desktop.py.
# The app has no console to print to, so it writes how it went to a file.
$App = Join-Path $PWD "build\dist\$AppName\$AppName.exe"
$Report = Join-Path $PWD "build\self-test.txt"
Remove-Item -Force -ErrorAction SilentlyContinue -LiteralPath $Report
$Run = Start-Process -FilePath $App -ArgumentList "--self-test `"$Report`"" -PassThru
if (-not $Run.WaitForExit(300000)) {
    Stop-Process -Id $Run.Id -Force
    throw "The app's self-test didn't finish in five minutes."
}
if (-not (Test-Path -LiteralPath $Report)) {
    throw "The app didn't start: it wrote no self-test report."
}
$Result = [string](Get-Content -LiteralPath $Report -Raw -Encoding UTF8)
Write-Host $Result
if (-not $Result.StartsWith("ok")) {
    throw "The app's self-test failed."
}

Write-Host "==> Packing Award-Wallet-Setup.exe"
function Find-InnoSetup {
    $Command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    # Where its installer puts it, for everyone or for you alone; the newest if there are several.
    Get-ChildItem -ErrorAction SilentlyContinue -Path @(
        "${env:ProgramFiles(x86)}\Inno Setup *\ISCC.exe",
        "$env:ProgramFiles\Inno Setup *\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup *\ISCC.exe"
    ) | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
$Iscc = Find-InnoSetup
if (-not $Iscc -and $env:CI) {
    Invoke-Program choco @("install", "innosetup", "--yes", "--no-progress")
    $Iscc = Find-InnoSetup
}
if (-not $Iscc) {
    Write-Host "Inno Setup is missing. Install it with this line, then try again:"
    Write-Host "  winget install --exact --id JRSoftware.InnoSetup"
    exit 1
}
Invoke-Program $Iscc @("/DAppVersion=$Version", "packaging\windows\award_wallet.iss")

Write-Host ""
Write-Host "Done: build\Award-Wallet-Setup.exe"
