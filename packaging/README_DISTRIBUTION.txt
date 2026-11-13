LagLens v0.1.0
===============

LagLens is a local Windows frame-time and diagnostic tool. It reads
PresentMon frame data and optional hardware telemetry, then shows
plain-language diagnostics, technical details, a troubleshooting guide,
and local Markdown/JSON reports.

Quick start
-----------
1. Extract this ZIP to a normal folder. Do not run it from inside the ZIP.
2. Run LagLens.exe.
3. Choose the running game process, start monitoring, play the same scene,
   then stop. When the capture is complete and valid, LagLens switches to
   the Analysis tab automatically.
4. Read the plain-language diagnosis, then follow the step-by-step guide.
5. Use Quick start / 快速上手 at any time to reopen the three-step intro.

No Python installation is required.

Administrator / ETW permission
------------------------------
PresentMon needs Windows ETW access. Run LagLens as Administrator, or add
your Windows account to the "Performance Log Users" group. LagLens does
not elevate silently; when administrator rights are missing it explains
the requirement and asks before restarting with elevation.

If PresentMon is missing or invalid, the app shows a message. In this
distribution it is bundled at:

  presentmon\PresentMon-2.6.0-x64.exe

NVIDIA GPU telemetry is optional. If NVML is unavailable, the hardware GPU
card reports that monitoring is unavailable; capture and CSV analysis
continue to work.

Where data is stored
--------------------
LagLens uses the current user's local application-data folder:

  %LOCALAPPDATA%\LagLens

Settings (LagLens.ini), captures, telemetry sidecars and logs are stored
there. They are not stored inside the application folder and are not
uploaded anywhere. For portable or test use, set LAGLENS_DATA_DIR to an
explicit writable folder before starting LagLens.

Features in this release
------------------------
- PresentMon capture and legacy CSV analysis
- Optional QPC timebase and telemetry sidecar
- Plain-language diagnostics and technical-details disclosure
- Step-by-step troubleshooting with progress and reset
- Recent captures (up to 8, local INI; no database)
- Automatic analysis after a complete, valid capture
- First-use quick start in English and Simplified Chinese
- Markdown and JSON report export
- Local-only operation; no cloud, network sync or automatic game changes

Privacy
-------
LagLens captures only frame timing and optional hardware telemetry for the
target process. It does not upload data and does not modify game, driver or
Windows settings. Reports use the capture basename and do not include full
user paths.

Licenses
--------
LagLens is MIT licensed. See LICENSE.
Third-party notices and license texts are in THIRD_PARTY_NOTICES.txt and
the LICENSES folder, including Qt 6.12.0 third-party texts under
LICENSES\Qt-6.12.0. PresentMon's MIT license is also included in
presentmon\LICENSE.txt. Qt/PySide6 is used under LGPL-3.0; the Qt DLLs are
shipped as separate, replaceable files.

This build is unsigned. Windows SmartScreen may show a warning the first
time it runs. Verify the source and SHA-256 in BUILD_INFO.txt before
running.
