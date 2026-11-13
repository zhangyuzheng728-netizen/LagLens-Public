param(
    [string]$Version = "0.1.0",
    [string]$DistRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Spec = Join-Path $PSScriptRoot "LagLens.spec"

if (-not $DistRoot) {
    $DistRoot = Join-Path $Root "dist"
}
elseif (-not [System.IO.Path]::IsPathRooted($DistRoot)) {
    $DistRoot = Join-Path $Root $DistRoot
}

$AppDir = Join-Path $DistRoot "LagLens"
$WorkDir = Join-Path $Root "build\pyinstaller"
$ZipName = "LagLens-v$Version-win64.zip"
$ZipPath = Join-Path $DistRoot $ZipName
$HashPath = "$ZipPath.sha256"

$PresentMonSource = Join-Path $Root "vendor\presentmon"
$PresentMonName = "PresentMon-2.6.0-x64.exe"
$PresentMonPath = Join-Path $PresentMonSource $PresentMonName

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

if (-not (Test-Path -LiteralPath $Spec)) {
    throw "PyInstaller spec not found: $Spec"
}

if (-not (Test-Path -LiteralPath $PresentMonPath)) {
    throw "Bundled PresentMon not found: $PresentMonPath"
}

Write-Host "Cleaning generated packaging output..."
if (Test-Path -LiteralPath $AppDir) {
    Remove-Item -LiteralPath $AppDir -Recurse -Force
}
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
if (Test-Path -LiteralPath $HashPath) {
    Remove-Item -LiteralPath $HashPath -Force
}
if (Test-Path -LiteralPath $WorkDir) {
    Remove-Item -LiteralPath $WorkDir -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null

Write-Host "Running PyInstaller (onedir)..."
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $DistRoot `
    --workpath $WorkDir `
    $Spec

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath (Join-Path $AppDir "LagLens.exe"))) {
    throw "Packaged EXE not found: $AppDir\LagLens.exe"
}

Write-Host "Copying PresentMon and distribution documents..."
$PresentMonTarget = Join-Path $AppDir "presentmon"
New-Item -ItemType Directory -Force -Path $PresentMonTarget | Out-Null
Copy-Item -LiteralPath $PresentMonPath -Destination $PresentMonTarget
Copy-Item -LiteralPath (Join-Path $PresentMonSource "LICENSE.txt") -Destination $PresentMonTarget
Copy-Item -LiteralPath (Join-Path $PresentMonSource "README.md") -Destination $PresentMonTarget

Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination (Join-Path $AppDir "LICENSE")
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README_DISTRIBUTION.txt") -Destination (Join-Path $AppDir "README.txt")
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "THIRD_PARTY_NOTICES.txt") -Destination (Join-Path $AppDir "THIRD_PARTY_NOTICES.txt")
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LICENSES") -Destination $AppDir -Recurse

$Commit = "unknown"
try {
    $Commit = (& git -C $Root rev-parse HEAD 2>$null).Trim()
}
catch {
    $Commit = "unavailable"
}
$Dirty = ""
try {
    $Status = (& git -C $Root status --short 2>$null)
    if ($Status) {
        $Dirty = " (dirty working tree)"
    }
}
catch {
}

$ExeHash = (Get-FileHash -LiteralPath (Join-Path $AppDir "LagLens.exe") -Algorithm SHA256).Hash
$PresentMonHash = (Get-FileHash -LiteralPath (Join-Path $PresentMonTarget $PresentMonName) -Algorithm SHA256).Hash

$BuildInfo = @"
LagLens v$Version Windows x64 distribution
==========================================

Build date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss K")
Git commit: $Commit$Dirty
Python: $(& $Python --version 2>&1)
PyInstaller: $(& $Python -m PyInstaller --version 2>&1)
PySide6: $(& $Python -c "import PySide6; print(PySide6.__version__)" 2>&1)
PresentMon: 2.6.0
Data directory: %LOCALAPPDATA%\LagLens (LAGLENS_DATA_DIR overrides)

LagLens.exe SHA-256:
$ExeHash

PresentMon SHA-256:
$PresentMonHash

Build command:
  .\packaging\build_windows.ps1

Layout:
  LagLens.exe
  _internal\          Qt/Python runtime, locales, assets
  presentmon\         PresentMon 2.6.0 + MIT license
  LICENSES\           third-party license texts
  README.txt
  THIRD_PARTY_NOTICES.txt
  LICENSE
"@
$BuildInfo | Set-Content -LiteralPath (Join-Path $AppDir "BUILD_INFO.txt") -Encoding UTF8

$Required = @(
    (Join-Path $AppDir "LagLens.exe"),
    (Join-Path $AppDir "README.txt"),
    (Join-Path $AppDir "LICENSE"),
    (Join-Path $AppDir "THIRD_PARTY_NOTICES.txt"),
    (Join-Path $AppDir "BUILD_INFO.txt"),
    (Join-Path $AppDir "presentmon\$PresentMonName"),
    (Join-Path $AppDir "presentmon\LICENSE.txt"),
    (Join-Path $AppDir "_internal\locales\en.json"),
    (Join-Path $AppDir "_internal\locales\zh_CN.json"),
    (Join-Path $AppDir "_internal\assets\check.svg"),
    (Join-Path $AppDir "_internal\assets\chevron-down.svg")
)
foreach ($Path in $Required) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required distribution file missing: $Path"
    }
}

$PlatformPlugin = Get-ChildItem -LiteralPath $AppDir -Recurse -Filter "qwindows.dll" -File | Select-Object -First 1
if ($null -eq $PlatformPlugin) {
    throw "Qt Windows platform plugin qwindows.dll is missing"
}

$Forbidden = Get-ChildItem -LiteralPath $AppDir -Recurse -File | Where-Object {
    $_.Extension -in @(".csv", ".log", ".ini", ".jsonl", ".pdb", ".pyc") -or
    $_.Name -eq "stdout_test.txt" -or
    $_.FullName -match "\\captures\\" -or
    $_.FullName -match "\\tests\\" -or
    $_.FullName -match "\\\.git\\"
}
if ($Forbidden) {
    throw "Forbidden development/capture files found in distribution: $($Forbidden.FullName -join ', ')"
}

Write-Host "Creating ZIP..."
Compress-Archive -LiteralPath $AppDir -DestinationPath $ZipPath -CompressionLevel Optimal -Force
$ZipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash
"$ZipHash  $ZipName" | Set-Content -LiteralPath $HashPath -Encoding ASCII

$FileListPath = Join-Path $DistRoot "LagLens-v$Version-win64-files.txt"
Get-ChildItem -LiteralPath $AppDir -Recurse -File |
    ForEach-Object {
        $Relative = $_.FullName.Substring($AppDir.Length + 1)
        "{0}`t{1}" -f $Relative, $_.Length
    } |
    Sort-Object |
    Set-Content -LiteralPath $FileListPath -Encoding UTF8

Write-Host ""
Write-Host "Build complete."
Write-Host "EXE: $AppDir\LagLens.exe"
Write-Host "ZIP: $ZipPath"
Write-Host "ZIP SHA-256: $ZipHash"
Write-Host "File list: $FileListPath"
