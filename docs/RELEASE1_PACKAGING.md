# Release-1: Windows Packaging and Distribution Preparation

Date: 2026-11-12
Version: 0.1.0
Status: packaged and non-elevated checks complete; **Release-1 is not fully
passed** because a fresh elevated ETW capture with the packaged build is
still pending.

## 1. Scope

- Build a self-contained Windows x64 distribution from the accepted
  UX-4 codebase.
- Bundle Qt, locales, assets and PresentMon.
- Use user-writable locations for settings, captures and logs.
- Include licenses and third-party notices.
- Do not package captures, test data, developer configuration, logs or
  repository metadata.
- Do not push the repository or publish a GitHub release.

The diagnostic engine, capture command and raw frame calculations were not
changed for packaging.

## 2. Build tooling

| Item | Version |
|---|---|
| Python | 3.12.8 |
| PyInstaller | 6.16.0 |
| pyinstaller-hooks-contrib | 2026.10 |
| PySide6 / shiboken6 | 6.12.0 |
| psutil | 7.2.2 |
| nvidia-ml-py | 13.615.71 |
| PresentMon | 2.6.0 x64 |

Build requirements are pinned in `requirements-build.txt`.

Build command:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\packaging\build_windows.ps1
```

Smoke command:

```powershell
.\packaging\smoke_test_windows.ps1 -DataDir <data-dir>
```

## 3. Distribution layout

```text
LagLens-v0.1.0-win64.zip
└─ LagLens/
   ├─ LagLens.exe
   ├─ _internal/              Python, Qt, locales, assets
   ├─ presentmon/
   │  ├─ PresentMon-2.6.0-x64.exe
   │  ├─ LICENSE.txt
   │  └─ README.md
   ├─ LICENSES/               full third-party license texts
   ├─ LICENSE                 LagLens MIT license
   ├─ README.txt              end-user instructions
   ├─ THIRD_PARTY_NOTICES.txt
   └─ BUILD_INFO.txt          version, commit, hashes, build command
```

PyInstaller onedir was chosen over onefile. It starts faster, keeps Qt
plugins/translations inspectable, and supports replacing Qt DLLs for LGPL
compliance. The package is not optimized for minimum size.

Actual build outputs (generated locally, not committed):

```text
dist/LagLens/LagLens.exe
dist/LagLens-v0.1.0-win64.zip
dist/LagLens-v0.1.0-win64.zip.sha256
dist/LagLens-v0.1.0-win64-files.txt
```

## 4. Runtime paths and permissions

Frozen builds resolve resources from the PyInstaller `_internal` directory
through `runtime_paths.py`. User data is written to the first writable
directory from:

```text
%LOCALAPPDATA%\LagLens
```

`LAGLENS_DATA_DIR` can override the location for portable or test runs.

- Settings: `LagLens.ini`
- Captures: `captures\`
- Logs: `logs\laglens.log`

This avoids writing to the application folder and avoids developer absolute
paths. Chinese paths and paths containing spaces were exercised through the
packaged EXE.

PresentMon is located dynamically:

```text
<app>\presentmon\PresentMon-2.6.0-x64.exe
```

`LAGLENS_PRESENTMON` can override it for advanced use. Legacy source mode
uses `vendor\presentmon\`.

LagLens does not elevate itself. PresentMon/ETW still requires
Administrator or the "Performance Log Users" group; the status bar and
failure dialog explain that requirement. Missing NVML only disables the
NVIDIA GPU card, not capture/CSV analysis.

## 5. Tests

Full automated suite:

```text
Ran 499 tests in 16.670s

OK
```

The pre-release grouped-diagnostics regression used the real
`douyin.exe_20261112_184509_333905.csv` capture:

- 8 anomalies;
- 7 fit the ~20.57 s interval;
- 1 extra at 104.36 s;
- Markdown reduced from 11,983 bytes / 230 lines to 3,823 bytes / 82
  lines on the same capture;
- JSON remained at 8 findings and 8 events.

Included runtime-path tests for source resources and the bundled
PresentMon path.

Packaged/non-elevated verification:

| Check | Result |
|---|---|
| EXE startup | pass (`smoke_test_windows.ps1`) |
| Normal close | pass |
| Forced process kill | settings INI remained valid; relaunch pass |
| English UI | pass, packaged screenshot |
| Chinese UI | pass, packaged screenshot |
| First-use quick start | pass, packaged screenshot + dismiss persisted |
| Recent captures | pass, packaged list and click-to-analysis |
| QPC + sidecar analysis | pass, real Palworld QPC capture |
| Legacy CSV analysis | pass, packaged 34,484-frame legacy capture |
| Plain diagnosis | pass, packaged screenshot |
| Technical disclosure | source automated tests pass |
| Step-by-step guide | source automated tests pass |
| Markdown export | pass from packaged EXE to Chinese + space path |
| JSON export | pass from packaged EXE to Chinese + space path |
| Auto-analysis window logic | source automated tests pass |
| Embedded Analysis page (UI-4) | source tests + packaged screenshot pass |
| Fresh elevated ETW capture | **blocked / not run** |

The current shell reports `capture_core.is_elevated() == False`, so it
cannot create a new ETW session. This is a release blocker, not silently
waived.

## 6. Packaged screenshots

```text
captures/release1_exe_live_en.png
captures/release1_exe_live_zh.png
captures/release1_exe_recent_en.png
captures/release1_exe_analysis_en.png
captures/release1_exe_analysis_zh.png
captures/release1_exe_legacy_en.png
```

These are screenshots of the packaged `dist/LagLens/LagLens.exe`, not the
source interpreter.

## 7. Dependency and license audit

| Component | License | Handling |
|---|---|---|
| LagLens | MIT | `LICENSE`, `LICENSES/MIT-LagLens.txt` |
| Qt / PySide6 / shiboken6 6.12.0 | LGPL-3.0-only (LGPL option chosen) | `LICENSES/LGPL-3.0.txt`; Qt DLLs remain separate/replaceable; Qt 6.12.0 third-party texts in `LICENSES/Qt-6.12.0/` |
| psutil 7.2.2 | BSD-3-Clause | `LICENSES/BSD-3-Clause-psutil.txt` |
| nvidia-ml-py 13.615.71 | BSD-3-Clause | `LICENSES/BSD-3-Clause-nvidia-ml-py.txt`; NVML driver not bundled |
| Python 3.12 | PSF License | `LICENSES/PSF-Python.txt` |
| PresentMon 2.6.0 | MIT | `presentmon/LICENSE.txt`, `LICENSES/MIT-PresentMon.txt` |
| PyInstaller 6.16.0 bootloader | GPL-2.0-or-later with Bootloader-exception | `LICENSES/PyInstaller.txt` |
| OpenSSL 3.0.15 runtime | Apache-2.0 | `LICENSES/Apache-2.0.txt` |
| Microsoft VC++ runtime | Microsoft redistributable terms | `THIRD_PARTY_NOTICES.txt` reference |

PresentMon source: https://github.com/GameTechDev/PresentMon
PresentMon SHA-256:
`B2A706BC6AD475749E3B7E3409263AA1E6906D45BDCF993F6DBC0F660188F1AF`

Build-only packages (altgraph, pefile, packaging, setuptools,
pywin32-ctypes) are not intended as runtime components.

## 8. Security / privacy audit

- No database, cloud upload, telemetry upload or network sync exists.
- Reports contain capture basename and target name, not full user paths.
- The distribution excludes `.git`, `tests`, `captures`, CSVs, `.ini`
  files, logs and development artifacts; the build script enforces a
  forbidden-file check.
- Hardcoded developer PresentMon path was removed. Source mode uses
  `vendor/presentmon`; frozen mode uses the application `presentmon`
  directory, with an optional environment override.
- `C:\Windows` remains only as a Windows system-root fallback in process
  filtering, not as a developer path.
- Targeted Git-history searches for private-key blocks, common API tokens,
  passwords and secrets returned no matches. Historical commits contain
  development absolute paths, but no credentials were found.
- No repository push or GitHub release was performed.

## 9. Remaining blockers / manual work

1. Run the packaged EXE elevated on a Windows machine.
2. Perform at least one fresh real game capture (recommended ≥3 minutes).
3. Verify CPU/GPU, QPC, telemetry sidecar, automatic analysis and
   Markdown/JSON export on that fresh capture.
4. If successful, update `docs/STATUS.md` and mark Release-1 fully passed.
5. Only then prepare any public GitHub release/push, with separate approval.

Until step 1–4 complete, Release-1 remains **packaged but not fully
accepted**.
