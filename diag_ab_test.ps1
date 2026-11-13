
# LagLens - PresentMon A/B Diagnostic
# Windows PowerShell 5.1 compatible
#
# Test A: Intel Graphics Software service running
# Test B: Intel Graphics Software service stopped
#
# Safety:
# - Does not change service startup type
# - Does not force-kill any processes
# - Skips B if Intel service or child process remains
# - Attempts to restore original service state

$ErrorActionPreference = "Stop"

$serviceName = "IntelGraphicsSoftwareService"

$exe = Join-Path $PSScriptRoot "vendor\presentmon\PresentMon-2.6.0-x64.exe"

$project = $PSScriptRoot

$session = "LagLensDiag"

$runId = Get-Date -Format "yyyyMMdd_HHmmss"

$diagDir = Join-Path $project "diag\ab_$runId"


# ------------------------------------------
# Check administrator permissions
# ------------------------------------------

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()

$principal = New-Object Security.Principal.WindowsPrincipal(
    $identity
)

$isAdmin = $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdmin) {
    Write-Host "ERROR: Administrator privileges required." -ForegroundColor Red
    exit 1
}


# ------------------------------------------
# Validate paths and service
# ------------------------------------------

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    Write-Host "ERROR: PresentMon executable not found." -ForegroundColor Red
    exit 1
}

$initialService = Get-Service -Name $serviceName

$initialStatus = $initialService.Status

Write-Host "Original Intel service state: $initialStatus"

if ($initialStatus -ne "Running") {
    Write-Host "Intel service is not running. A/B test cannot begin." -ForegroundColor Yellow
    exit 1
}

New-Item -ItemType Directory -Force -Path $diagDir | Out-Null

Write-Host "Diagnostic directory: $diagDir"


# ------------------------------------------
# Capture ETW session list
# ------------------------------------------

function Save-Sessions {
    param([string]$Label)

    $file = Join-Path $diagDir "sessions_$Label.txt"

    & logman.exe query -ets |
        Out-File -FilePath $file -Encoding UTF8
}


# ------------------------------------------
# Run one PresentMon capture
# ------------------------------------------

function Invoke-Capture {
    param([string]$Label)

    $csvPath = Join-Path $diagDir "$Label.csv"
    $errPath = Join-Path $diagDir "$Label.stderr.txt"
    $outPath = Join-Path $diagDir "$Label.stdout.txt"

    $pmArgs = @(
        "--session_name", $session,
        "--stop_existing_session",
        "--timed", "10",
        "--terminate_after_timed",
        "--v2_metrics",
        "--no_track_gpu",
        "--no_track_input",
        "--no_console_stats",
        "--output_file", $csvPath
    )

    Write-Host ""
    Write-Host "===================================="
    Write-Host "Capture: $Label"
    Write-Host "Scroll Chrome during the next 10 seconds."
    Write-Host "===================================="

    $process = Start-Process `
        -FilePath $exe `
        -ArgumentList $pmArgs `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardError $errPath `
        -RedirectStandardOutput $outPath

    $exitCode = $process.ExitCode

    $fileSize = 0
    $records = 0

    if (Test-Path -LiteralPath $csvPath) {

        $fileSize = (Get-Item -LiteralPath $csvPath).Length

        if ($fileSize -gt 0) {
            try {
                $records = (
                    Import-Csv -LiteralPath $csvPath |
                    Measure-Object
                ).Count
            }
            catch {
                $records = -1
            }
        }
    }

    $errorText = ""

    if (Test-Path -LiteralPath $errPath) {
        $errorText = [string](
            Get-Content -LiteralPath $errPath -Raw
        )
    }

    $match = [regex]::Match(
        $errorText,
        '([\d,]+)\s+ETW events were lost'
    )

    $lost = "Not reported"

    if ($match.Success) {
        $lost = $match.Groups[1].Value
    }

    Write-Host ""
    Write-Host "RESULT: $Label"
    Write-Host "Exit code: $exitCode"
    Write-Host "CSV size: $fileSize bytes"
    Write-Host "Frame records: $records"
    Write-Host "ETW events lost: $lost"

    if ($errorText.Trim()) {
        Write-Host "PresentMon stderr:"
        Write-Host $errorText
    }

    return [pscustomobject]@{
        Test = $Label
        ExitCode = $exitCode
        FileSize = $fileSize
        Records = $records
        ETWLost = $lost
    }
}


# ------------------------------------------
# A/B experiment
# ------------------------------------------

$resultA = $null
$resultB = $null
$serviceRestored = $false
$validB = $false

try {

    # Stage A
    Write-Host ""
    Write-Host "STAGE A: Intel service running" -ForegroundColor Cyan

    Save-Sessions "A_running"

    $resultA = Invoke-Capture "A_running"

    # Check dependent services before stopping
    $serviceInfo = Get-Service -Name $serviceName

    $activeDependents = @(
        $serviceInfo.DependentServices |
        Where-Object { $_.Status -eq "Running" }
    )

    if ($activeDependents.Count -gt 0) {

        Write-Warning "Intel service has running dependents. Skipping Stage B."

    }
    else {

        # Stage B
        Write-Host ""
        Write-Host "STAGE B: Temporarily stopping Intel service" -ForegroundColor Cyan

        try {
            Stop-Service `
                -Name $serviceName `
                -ErrorAction Stop
        }
        catch {
            Write-Warning "Failed to stop Intel service: $_"
        }

        Start-Sleep -Seconds 5

        $serviceAfterStop = (
            Get-Service -Name $serviceName
        ).Status

        $pmCount = @(
            Get-Process `
                -Name "PresentMonService" `
                -ErrorAction SilentlyContinue
        ).Count

        Write-Host "Intel service state: $serviceAfterStop"
        Write-Host "PresentMonService count: $pmCount"

        # Do not kill processes.
        # A valid B requires the service to be stopped
        # and the child PresentMon process to be gone.

        if (
            $serviceAfterStop -eq "Stopped" -and
            $pmCount -eq 0
        ) {

            Save-Sessions "B_stopped"

            $resultB = Invoke-Capture "B_stopped"

            $serviceAfterB = (
                Get-Service -Name $serviceName
            ).Status

            if ($serviceAfterB -eq "Stopped") {
                $validB = $true
            }
            else {
                Write-Warning "Intel service restarted during Stage B. Results are not a clean comparison."
            }

        }
        else {

            Write-Warning "Stage B skipped. Intel service or PresentMonService is still running."

        }
    }

}
finally {

    # Restore original service state
    Write-Host ""
    Write-Host "RESTORING INTEL SERVICE" -ForegroundColor Yellow

    $currentStatus = (
        Get-Service -Name $serviceName
    ).Status

    if (
        $initialStatus -eq "Running" -and
        $currentStatus -ne "Running"
    ) {

        try {

            Start-Service `
                -Name $serviceName `
                -ErrorAction Stop

            Start-Sleep -Seconds 3

        }
        catch {

            Write-Warning "Automatic restoration failed: $_"

        }
    }

    $finalStatus = (
        Get-Service -Name $serviceName
    ).Status

    $serviceRestored = (
        $finalStatus -eq $initialStatus
    )

    Write-Host "Original state: $initialStatus"
    Write-Host "Final state: $finalStatus"

    if (-not $serviceRestored) {
        Write-Warning "Service state was NOT restored. Manual intervention is needed."
    }
}


# ------------------------------------------
# Results
# ------------------------------------------

Write-Host ""
Write-Host "===================================="
Write-Host "A/B TEST SUMMARY"
Write-Host "===================================="

if ($null -ne $resultA) {
    $resultA | Format-List
}

if ($null -ne $resultB) {
    $resultB | Format-List
}

Write-Host "Stage B valid: $validB"
Write-Host "Service restored: $serviceRestored"
Write-Host "Logs: $diagDir"

Write-Host ""
Write-Host "Done."
