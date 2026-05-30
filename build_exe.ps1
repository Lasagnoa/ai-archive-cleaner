$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path ".venv")) {
    py -3 -m venv .venv
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements-build.txt

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "AIArchiveCleaner"
)

if (Test-Path "favicon.ico") {
    $PyInstallerArgs += @("--icon", "favicon.ico")
}

$PyInstallerArgs += "app.py"
& $Python -m PyInstaller @PyInstallerArgs

Remove-Item -LiteralPath (Join-Path $ProjectRoot "build") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $ProjectRoot "AIArchiveCleaner.spec") -Force -ErrorAction SilentlyContinue

Write-Host "Built: dist\AIArchiveCleaner.exe"
