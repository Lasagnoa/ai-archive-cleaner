param([switch]$InstallDependencies)
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location -LiteralPath $ProjectRoot

$OutputDirectory = Join-Path $ProjectRoot "dist"
if ((Split-Path -Leaf $ProjectRoot) -eq "Development") {
    $OutputDirectory = Join-Path (Split-Path -Parent $ProjectRoot) "Release"
}

if (-not (Test-Path -LiteralPath ".venv/Scripts/python.exe")) {
    py -3.13 -m venv .venv
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

# These intermediate paths are cleaned at the end of this build.
foreach ($Intermediate in @("build", "AIArchiveCleaner.spec")) {
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot $Intermediate)) {
        throw "Existing build input preserved: $Intermediate. Use a clean checkout or rename it first."
    }
}
$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--distpath", $OutputDirectory,
    "--name", "AIArchiveCleaner", "--version-file", "version_info.txt"
)

if (Test-Path "favicon.ico") {
    $PyInstallerArgs += @("--icon", "favicon.ico", "--add-data", "favicon.ico;.")
}

$PyInstallerArgs += "app.py"
& $Python -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$OutputExe = Join-Path $OutputDirectory "AIArchiveCleaner.exe"
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

Write-Host "Built: $OutputExe"
