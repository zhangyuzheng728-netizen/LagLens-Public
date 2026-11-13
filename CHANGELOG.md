# Changelog

All notable changes to LagLens are documented here. The project follows
[Semantic Versioning](https://semver.org/) for release versions.

## [0.1.0] - 2026-11-13

Initial source preview. No prebuilt LagLens Windows package is published.

### Added

- Local PresentMon 2.6.0 capture with live frame-time, FPS and statistics.
- Legacy `CPUStartTime` CSV analysis and opt-in QPC timestamp support.
- Optional CPU/GPU/target telemetry sidecar with timebase calibration.
- Evidence-based diagnostic engine with confidence and claim levels.
- Plain-language diagnostic summary and collapsible technical evidence.
- Local dynamic frame-time anomaly list with chart/event selection linkage.
- Four-step C-4 troubleshooting guide with local progress and reset.
- Markdown and JSON report export.
- Single main window with Hardware, Live Frames, Analysis and Settings
  pages; analysis content is embedded, not a separate top-level window.
- Analyze Last Capture, recent captures, automatic post-capture analysis
  and Open CSV entry points.
- Re-check entry that returns to Live Frames, verifies the target process
  and never starts capture automatically.
- Runtime English / Simplified Chinese switching.
- Recent captures (maximum 8) stored in the local INI file.
- Windows onedir PyInstaller package with bundled PresentMon, Qt runtime,
  licenses and third-party notices.
- User-writable data location at `%LOCALAPPDATA%\LagLens`, with
  `LAGLENS_DATA_DIR` override.

### Changed

- Analysis is embedded in the main window; the standalone FrameViewer
  window is no longer opened by the application.
- The data directory no longer prefers a developer `D:` or `E:` drive.
- The C-4 guide uses checkbox + wrapped-label rows so narrow windows and
  125%/150% scaling do not create horizontal scrolling.
- Runtime dependencies and build dependencies are split into
  `requirements.txt` and `requirements-build.txt`.

### Fixed

- Repeated diagnostic findings are grouped by category/code for the UI
  and Markdown report while JSON keeps all raw findings and events.
- Periodicity is presented only for the matching subset of events.
- Re-check checks whether the target is running instead of trusting an
  old PID.
- Analysis page preserves the loaded viewer, worker state and report
  state when switching pages.

### Known limitations

- Opening long captures can cause a noticeable delay on the Analysis page.
- The Windows build is unsigned.
- AMD/Intel GPU telemetry, network diagnostics, automatic A/B testing,
  cloud analysis and AI analysis are not implemented.
- Diagnostics are evidence-based leads, not guaranteed root causes.
- C-4 guide state is session-local.

[0.1.0]: docs/RELEASE_NOTES_v0.1.0.md
