# Changelog

All notable changes to LagLens are documented here. The project follows
[Semantic Versioning](https://semver.org/) for release versions.

## [Unreleased]

### Added

- OpenAI, Claude and Gemini support on the same provider-neutral
  streaming contract. Settings → AI service selects the provider and
  model (DeepSeek remains the default); each provider stores its key in
  its own Windows Credential Manager target, and the DeepSeek target is
  unchanged so existing keys keep working. Switching the selection only
  persists it and never sends a request. A request snapshots provider,
  model and key at send time. Missing keys and auth failures point to
  Settings and never switch providers or retry automatically.
- Provider-neutral AI streaming. `ai_stream.py` defines text-delta,
  completion, usage and error events; `deepseek_client.stream_insight`
  implements DeepSeek's real SSE protocol and ignores
  `reasoning_content`. The chat layer only consumes those events, so a
  new provider needs an adapter, not UI changes. Free-form answers now
  appear while they are generated, with a localized **Stop** button.
  Stopped, disconnected or timed-out replies keep their partial text,
  are marked incomplete (and excluded from the next request's history),
  and are never auto-resent.
- Background report loading: `show_analysis` returns in about 2 ms and
  shows a localized loading page while `analysis_loader` computes CSV,
  timebase, chains, statistics, diagnostics and the AI summary on a
  worker thread. Each request carries a generation number, so a late
  result from an older report never replaces the report the user is
  looking at, and a failed load keeps the current report usable. The AI
  page follows the newly installed report's own `report_key`.
- Optional self-use AI insight on the Analysis page. It sends only a
  small `DisplayedTime` summary to DeepSeek after an explicit click,
  runs in the background, and keeps the local report visible if the
  request fails. The API key comes from `DEEPSEEK_API_KEY` or a hidden
  in-memory prompt.
- Shared performance classification that separates stable target,
  known 30 FPS cap, sustained explicit-target low FPS, repeated
  unevenness, notable stalls and insufficient display data. Cause
  evidence is generated only for attention statuses, with display and
  telemetry windows aligned by timestamps.
- Embedded AI assistant page between Analysis and Settings, with an
  explicit Ask AI link from a report, per-report in-memory chat and
  draft, continuous follow-up, retry after failure, late-reply isolation
  and 4 KiB context trimming.
- Optional project-local `network_vs_local` diagnostic skill card,
  injected only for network/stutter/differentiation questions. Reports
  without network measurements say so explicitly; synthetic probe data
  is used only in tests.
- Real Windows ICMP gateway/public network sampling, standalone Network
  tab and optional joint capture, with capture-window sidecar and
  time-aligned network chart in Analysis. Public probes are never
  presented as game-server latency.
- Every Live Frames session now records frames, hardware telemetry and
  network probes from the single Start button; the old detection-mode
  choice was removed. Captures have a shared session ID, monotonic/
  wall-clock origin, session metadata and per-sample network timestamps/
  source/interval/validity. Reports distinguish start failure, no valid
  reply, missing data, session mismatch, non-overlapping time and
  normal/abnormal states.
- AI quick question and chat now share joint frame/hardware/network
  evidence, scope-labelled metrics, capture-relative evidence windows
  with nearby baselines, explicit missing/alignment markers and a new
  network-vs-local quick question, under the existing 4 KiB budget.
- Settings → AI service with Windows Credential Manager key storage,
  saved > environment > session precedence, explicit environment
  fallback, remove, and manual minimal connection test. Existing keys
  are never written to INI, logs or reports.
- Evidence-driven diagnosis layer (`diagnosis_pipeline.py`): scenario
  detection with user override (game/video/browser/desktop/unknown),
  data-quality checks, fact IDs with validity and limits, local
  evidence-strength ceiling, and allowed-conclusion filtering.
- In-window report switcher on the Analysis page. It reuses the recent
  captures list, sorts newest first, shows program, capture time,
  duration and data status, and reloads the selected report inside the
  main window. It never starts PresentMon or calls AI; cancel and
  missing/damaged files keep the current report. `report_key` and
  `session_id` follow the new report, and the AI chat does not relink
  until the user asks AI from that report.
- AI quick questions now start with a full assessment (anomaly, possible
  cause, optimization needed) while optional prompts cover smoothness,
  hardware, network and optimization. The validator also rejects
  hardware-bottleneck claims without CPU/GPU/memory facts,
  network-normal claims without network data, and advice with no
  supporting fact or missing-evidence note.
- Structured AI answers validated against local facts: unknown fact IDs,
  misquoted numbers (including `%`/ratio and `s`/`ms` equivalents), too
  strong claims, unsafe advice, unsupported conclusions, video
  “dropped frames” without source FPS, and unverified network/frame
  correlation are rejected once and repaired; a failed repair falls
  back to the local fact summary. Analysis shows the scenario selector
  and diagnosis metadata, and a scenario change refreshes only the
  matching chat context.

### Changed

- AI service settings now show the current provider and model and let
  you switch between DeepSeek, OpenAI, Claude and Gemini without
  re-entering keys or sending a test request. The connection test uses
  the selected provider. Error messages are provider-neutral and
  auth/missing-key failures include a “check Settings” hint.
- Free-form AI answers stream from the provider instead of waiting for
  the full response; the transcript re-renders at most about 25 times per
  second. The structured (`LAGLENS_AI_MODE=structured`) diagnosis keeps
  its buffered validate-then-show path, so unvalidated content is not
  displayed early. Real DeepSeek check on the native Windows GUI: first
  text at 0.688 s, first visible at 0.829 s, completion at 1.531 s, 37
  incremental chunks and usage present.
- Large reports no longer block the window. On a real 140,699-frame
  capture, click-to-report fell from 9,381 ms to 3,446 ms (offscreen) /
  3,472 ms (native GUI), with one ~250 ms hitch while the viewer is
  built. The frame chart now draws peak-preserving, pixel-bucketed
  downsampled points (about 1,400 instead of 140,699) and caches them,
  cutting a paint from 762.8 ms to 11.5 ms. Downsampling is display-only:
  statistics, stutter detection, export and AI facts still use every
  frame, and a chart click maps back to the original frame index.
- Local stutter detection uses a sliding sorted window with a MAD early
  exit: 5.27 s → 0.091 s on the same capture with identical merged
  events.
- The AI assistant now defaults to the older free-form answer mode: the
  model's text is shown directly and is not forced through JSON/number
  validation, so a misattributed fact ID no longer replaces the answer with
  a local fact list. The local report remains available in Analysis. Set
  `LAGLENS_AI_MODE=structured` to opt back into the evidence-validated JSON
  path.
- AI answer language follows the question language first, then the current
  UI language. Switching the UI after a report is linked now refreshes the
  AI context language; existing transcript messages stay in their original
  language.
- The free-form prompt now answers only the current question. Language,
  capability and off-topic questions do not get a performance summary;
  already-stated conclusions/numbers are not repeated in full.
- AI requests now write bounded local diagnostics under
  `%LOCALAPPDATA%\LagLens\logs\ai_diagnostics.jsonl`. The log records
  request/model/report/session identity, scenario/quality, JSON and
  validation outcomes, failed fact IDs/numbers/units, repair result,
  final AI/fallback source and optional token usage. API keys, chat text,
  raw responses and full capture paths are never recorded; the file is
  capped at 5 MiB plus one 5 MiB backup and old backups are pruned.

### Fixed

- AI requests are now measured as the exact UTF-8 body each provider
  adapter sends, including model, messages and streaming fields, and the
  measured bytes are sent unchanged. The fixed 64-byte reserve is gone:
  a 4,096-byte body is allowed and an incompressible 4,097-byte body is
  rejected locally before transport. A two-minute Douyin capture that
  was rejected at 4,034 B against a 4,032 B limit now fits. If the body
  is over, the summary is compressed in priority order (older turns,
  optional details, skills, compact text, secondary facts) and re-measured;
  total frames, P95/P99, anomaly totals, ≥1 s count, longest event,
  network timeout/rate and telemetry alignment are never dropped.
  Over-long questions and an incompressible summary now produce different
  messages, and diagnostics record only bytes/limit/stage, never the key
  or request body. A local 432,000-frame two-hour simulation exports its
  Markdown with a second-half 4.2 s event and produces a 4,001-byte
  DeepSeek body.
- The shared AI summary now keeps the abnormal long-frame total, the
  count of events of at least one second and the event time span, not
  only the longest event. On the Cyberpunk 2077 capture (12 events,
  10 ≥1 s, longest 3.538 s) the answer reports both totals instead of a
  single stall. When the diagnostics timebase is untrusted, the summary
  says hardware samples exist but cannot be aligned per event, never
  “telemetry missing”, and does not blame CPU/GPU. Gateway/public probe
  timeouts are explicitly not attributed to the game server. The compact
  chat text still fits the 4 KiB budget by dropping derivable facts, not
  the event totals or the longest event.
- A late large-report load no longer overwrites the newer report's
  chart, status or AI context, and a damaged CSV only shows a warning
  instead of clearing a valid report. The failed-load path also no
  longer raises `AttributeError` on the empty state.
- Structured diagnosis no longer rejects a correct stall timestamp as if it
  were the stall duration. Each fact now exposes its main value, event time
  and capture window; the validator accepts a number only when it matches one
  of the cited fact's own fields. The real chrome capture with a 5.695 s
  stall at 11.125 s is covered by regression tests.
- Report facts are listed one per line with `fact_id: value`, and a copied
  `display_fps=67.76FPS` fact ID is reduced to the known ID before
  validation. The numeric check still rejects a wrong value under that ID.
- Browser/video guidance now says a single long display interval uses
  `no_clear_issue` or `insufficient_evidence`; observations state the stall
  rather than calling it a stutter.
- `verified_qpc` is no longer presented as evidence that the network is
  normal. `network_available` is a separate fact, and network claims without
  network data are rejected.
- `session_status=unknown` is kept as unknown with an explicit “missing
  metadata, not success” limit.
- A failed structured answer now shows a plain-language note about what was
  rejected instead of exposing raw internal validation strings.

## [0.1.0] - 2026-11-13

Initial public pre-release.

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

- A fresh elevated real-game ETW capture with the final v0.1.0 package is
  still required before final release acceptance.
- The Windows build is unsigned.
- AMD/Intel GPU telemetry, network diagnostics, automatic A/B testing,
  cloud analysis and AI analysis are not implemented.
- Diagnostics are evidence-based leads, not guaranteed root causes.
- C-4 guide state is session-local.

[0.1.0]: docs/RELEASE_NOTES_v0.1.0.md
