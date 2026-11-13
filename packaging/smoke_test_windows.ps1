param(
    [string]$Exe = "",
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
if (-not $Exe) {
    $Exe = Join-Path $Root "dist\LagLens\LagLens.exe"
}

if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Packaged EXE not found: $Exe"
}

if ($DataDir) {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $env:LAGLENS_DATA_DIR = $DataDir
}

$process = Start-Process -FilePath $Exe -PassThru
try {
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        $process.Refresh()
        if ($process.HasExited) {
            throw "LagLens exited during startup with code $($process.ExitCode)"
        }
        if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
            break
        }
    }
    if ($process.MainWindowHandle -eq [IntPtr]::Zero) {
        throw "LagLens main window did not appear within 20 seconds"
    }
    if (-not $process.Responding) {
        throw "LagLens main window is not responding"
    }

    Write-Output "startup_ok=True"
    Write-Output "title=$($process.MainWindowTitle)"
    Write-Output "exe=$Exe"
}
finally {
    if (-not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        if (-not $process.WaitForExit(8000)) {
            $process.Kill()
            throw "LagLens did not close within 8 seconds"
        }
    }
    if ($DataDir) {
        Remove-Item Env:LAGLENS_DATA_DIR -ErrorAction SilentlyContinue
    }
}

Write-Output "close_ok=True"
