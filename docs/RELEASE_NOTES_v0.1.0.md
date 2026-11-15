# LagLens v0.1.0 — Initial Pre-release

LagLens is a free, open-source Windows frame-time capture and
evidence-based performance diagnostic tool. This is the first public
pre-release.

## Highlights

- **Single-window workflow** — Hardware, Live Frames, Analysis and
  Settings pages. Analysis is embedded in the main window.
- **Plain-language diagnosis first** — what was found, why it matters,
  how confident the evidence is, and what to try next.
- **Technical evidence on demand** — frame statistics, anomaly events,
  timebase/telemetry status and raw event details.
- **Guided troubleshooting** — a four-step C-4 checklist per finding with
  local progress and reset.
- **Local reports** — Markdown and JSON export, no cloud upload.
- **Legacy and QPC analysis** — old `CPUStartTime` CSVs remain supported;
  QPC is an opt-in timestamp mode with explicit sync quality.
- **English and Simplified Chinese** UI switching at runtime.
- **Bundled runtime** — the ZIP includes Python, Qt/PySide6, PresentMon
  2.6.0 and license notices; no Python installation is required.

![LagLens Analysis page](../captures/ui4_analysis_en.png)

## Requirements

- Windows 10/11 x64.
- Administrator rights or membership in the **Performance Log Users**
  group for ETW capture.
- Optional NVIDIA GPU telemetry requires a compatible NVIDIA driver with
  NVML.

## Install

1. Download `LagLens-v0.1.0-win64.zip`.
2. Extract the whole archive to a normal writable folder.
3. Run `LagLens.exe`.
4. Compare the SHA-256 with `BUILD_INFO.txt` and the `.sha256` file next
   to the ZIP. The build is unsigned, so SmartScreen may warn.

## Data location

Settings, captures, telemetry sidecars and logs are stored under:

```text
%LOCALAPPDATA%\LagLens
```

Set `LAGLENS_DATA_DIR` to use a different writable folder. LagLens does
not upload captures or telemetry.

## Known issues and release-blocking checks

- A fresh elevated real-game ETW capture with this final package is still
  required before final release acceptance. Until then, treat this as a
  pre-release.
- The executable is unsigned.
- AMD/Intel GPU telemetry, network diagnostics, automatic A/B testing,
  cloud analysis and AI analysis are not implemented.
- Diagnostics are evidence-based leads, not guaranteed root causes.
- C-4 checklist state is kept for the current session only.
- VRR, overlays, multi-monitor DPI, capture-method changes and some
  anti-cheat/ETW restrictions are not fully validated.

## Checksums

The build script writes:

```text
LagLens/BUILD_INFO.txt          # EXE and PresentMon SHA-256
LagLens-v0.1.0-win64.zip.sha256 # ZIP SHA-256
```

Verify before running:

```powershell
Get-FileHash .\LagLens-v0.1.0-win64.zip -Algorithm SHA256
Get-Content .\LagLens-v0.1.0-win64.zip.sha256
```

## License

LagLens is distributed under the MIT License. Qt/PySide6 is used under
LGPL-3.0 with separate, replaceable DLLs. PresentMon is MIT licensed.
See `LICENSE`, `THIRD_PARTY_NOTICES.txt` and `LICENSES/` in the ZIP.

## Disclaimer

LagLens reports evidence and suggestions; it does not guarantee a fix and
does not modify games, drivers or Windows settings automatically.
