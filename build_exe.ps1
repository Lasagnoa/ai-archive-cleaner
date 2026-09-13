param([switch]$InstallDependencies)
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath ".venv/Scripts/python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    $InstallDependencies = $true
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if ($InstallDependencies) {
    & $Python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed" }
}
& $Python -m unittest -q test_cleanup
if ($LASTEXITCODE -ne 0) { throw "Tests failed; build cancelled" }

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "AIArchiveCleaner", "--version-file", "version_info.txt"
)

if (Test-Path "favicon.ico") {
    $PyInstallerArgs += @("--icon", "favicon.ico", "--add-data", "favicon.ico;.")
}

$PyInstallerArgs += "app.py"
& $Python -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$OutputExe = Join-Path $ProjectRoot "dist/AIArchiveCleaner.exe"
if (-not (Test-Path -LiteralPath $OutputExe)) { throw "Build output missing" }

foreach ($RelativeOutput in @("build", "AIArchiveCleaner.spec")) {
    $CleanupTarget = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $RelativeOutput))
    if (-not $CleanupTarget.StartsWith($ProjectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Invalid build cleanup path"
    }
    if (Test-Path -LiteralPath $CleanupTarget) {
        $CleanupItem = Get-Item -LiteralPath $CleanupTarget -Force
        if ($CleanupItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw "Refusing linked build output" }
        Remove-Item -LiteralPath $CleanupTarget -Recurse -Force
    }
}

Write-Host "Built: dist\AIArchiveCleaner.exe"
