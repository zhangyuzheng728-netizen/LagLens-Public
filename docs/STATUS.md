# LagLens Development Status

Last updated: 2026-11-14

## Repository

- Path: `<repo>` (the checkout location is machine-specific)
- Branch: `feature/game-performance`
- Latest tag: `release2-request-budget` (exact AI request body budget)
- Working tree: 2.0 request-body budget fix committed locally
- Tests: **762 passing** (751 before the request-body fix)

```powershell
cd <repo>
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

## Completed

| Area | State | Tag |
|---|---|---|
| Capture pipeline (PresentMon stdout, CSV validation) | working, real captures verified | `phase1-baseline` |
| CSV integrity (truncated rows, quality counts) | done | `p2-1-csv-integrity` |
| Frame statistics (P50/P95/P99, 1% Low, stutters) | done | `p2-2-frame-stats` |
| Reliability (async close, Job Object, stop-on-exit) | done | `p2-5-phase1..3` |
| Live capture regression fix | done | `p2-5-live-fix` |
| Swap-chain selection algorithm + GUI | done | `p2-3-swap-selection`, `p2-3-algorithm-v2`, `p2-3-gui` |
| Palworld launcher/renderer process fix | done | `fix-process-selection` |
| Phase A-1 i18n infrastructure + settings | done | `p2-a1-i18n-core` |
| Phase A-2 Settings tab + main window i18n | done | `p2-a2-settings-i18n` |
| Phase A-3 analysis window + failure codes + chain reasons | done | `p2-a3-analysis-i18n` |
| failure_code damaged-CSV classification fix | done | `fix-failure-classification` |
| Phase A-3 manual UI acceptance | passed 2026-11-12 | `a3-ui-accepted` |
| Phase B-1 process catalog, ranking, path memory | accepted 2026-11-12 | `p2-b1-process-catalog` |
| B-1 memory fix: only verified captured PIDs | accepted 2026-11-12 | `p2-b1-memory-fix` |
| Phase B-2 process-selection dialog | accepted 2026-11-12 | `p2-b2-process-dialog` |
| Phase B-3 settings memory, success recording, launcher guidance, target lock | accepted 2026-11-12 | `p2-b3-integration` |
| Phase B final acceptance (real Palworld capture) | passed 2026-11-12 | `phase-b-accepted` |
| Phase UI-1 typography, high-DPI and chart clarity | accepted 2026-11-12 | `ui-1-clarity`, `ui-1-accepted` |
| Phase UI-2 Modern Design System (tokens, Fusion, controls, states) | accepted 2026-11-12 | `ui-2-design-system`, `ui-2-accepted` |
| Phase UI-3 page-level layout and responsive refresh | accepted visually 2026-11-12 | `ui-3-page-refresh`, `ui-3-accepted` |
| Phase UI (UI-1 + UI-2 + UI-3) | visually accepted | `ui-1-accepted`, `ui-2-accepted`, `ui-3-accepted` |
| Phase UI real Palworld regression | passed for core capture + CSV analysis workflow; edge cases not covered | `ui-regression-accepted` |
| Phase C design | approved 2026-11-12 | `docs/PHASE_C_DESIGN.md` |
| Phase C-1 hardware telemetry + timebase | done, accepted data layer | `c1-telemetry` |
| Phase C-1.1 real timebase + overhead validation | accepted 2026-11-12 | `c1-1-timebase-validation` |
| Phase C-2.0 QPC time synchronization | accepted 2026-11-12 | `c2-0-qpc-integration` |
| Phase C-2.1 evidence-based diagnostic engine | accepted 2026-11-12 | `c2-1-diagnostics` |
| Phase C-2.2 diagnostic reliability + false-positive validation | accepted 2026-11-12 | `c2-2-reliability` |
| Phase C-3 diagnostic UI + JSON/Markdown reports | complete; visual polish done | `c3-diagnostic-ui`, `c3-ui-polish` |
| Phase C-4 guided troubleshooting + re-check entry | complete, awaiting combined review | `c4-guided-troubleshooting` |
| UX-4 plain-language diagnostics + technical disclosure | complete, accepted 2026-11-12 | `ux4-plain-language` |
| UX-4 auto-analysis, recent captures, first-use quick start | complete, awaiting final UX-4 review | `ux4-workflow` |
| Release-1 Windows packaging + distribution preparation | packaged; blocked on fresh elevated ETW acceptance | `release-1-packaging` |
| Pre-release grouped diagnostics + concise reports | complete, awaiting review | `release-1-grouped-diagnostics` |
| UI-4 single-window navigation + embedded analysis | accepted 2026-11-13 | `ui4-single-window` |
| Release-2 public-source audit + release materials | complete, awaiting acceptance | `docs/RELEASE2_AUDIT.md` |
| Analysis inline full report + grouped findings/events | complete, awaiting review | `docs/ANALYSIS_INLINE_REPORT.md` |
| Generic AI streaming (DeepSeek real SSE, provider-neutral contract) | complete, awaiting review | `docs/AI_STREAMING.md` |
| Multi-provider AI (DeepSeek, OpenAI, Claude, Gemini) | complete; DeepSeek real GUI verified, others automated | `docs/MULTI_PROVIDER.md` |
| Release-2 AI stutter summary (event totals, alignment wording) | complete; source GUI real DeepSeek verified, packaged acceptance pending | `docs/AI_STUTTER_SUMMARY.md` |
| LagLens 2.0 exact AI request-body budget | implemented; 762 tests; packaged acceptance pending | `docs/AI_REQUEST_BUDGET.md` |
| Report loading/switch/scroll performance | complete, awaiting review | `docs/PERFORMANCE_LOADING.md`, `docs/ACCEPTANCE_PERF_LOADING.md` |

## Pending

1. **Fresh elevated ETW capture with the final v0.1.0 package.**
   The packaged EXE/ZIP and non-elevated checks are complete, but the
   audit shell cannot create an ETW session. Do not mark the release
   fully passed until a final-build capture (CPU/GPU, QPC, telemetry,
   auto-analysis, report export) completes on an elevated Windows host.
2. **Git-history privacy decision.** Commit metadata contains a personal
   email address and historical commits contain developer absolute paths.
   Rewriting history is destructive and requires explicit approval.
3. **Final license approval.** The repository already contains an MIT
   `LICENSE`; the maintainer must confirm it before publication.
4. **GitHub publication / repository push** (not performed; requires
   separate approval).

UX-4 plain-language diagnostics and workflow are accepted. The packaged
application uses the same diagnostic/capture engine. C-4 is complete;
C-3 visual polish is complete; C-2.2 is accepted. Legacy `CPUStartTime`
remains the default; QPC is a default-off opt-in with verified mapping.

Phase B is complete and accepted. The UI design audit found that the
application ignores the current Windows text scale (182%) because QSS
hard-codes 13px `Segoe UI` instead of the 15.75pt system font; this is
the main clarity root cause. See `docs/PHASE_UI_DESIGN.md`,
`docs/ACCEPTANCE_PHASE_B.md`, `docs/PHASE_B1_DESIGN.md`,
`docs/PHASE_B2_DESIGN.md`, `docs/PHASE_B3_DESIGN.md` and
`docs/ACCEPTANCE_A3.md`.

## Key data locations

- Settings: `%LOCALAPPDATA%\LagLens\LagLens.ini`
- Successful-target memory: settings key `processes/successful_targets`
  (path, executable, last_success; never PID)
- Packaged captures/logs: `%LOCALAPPDATA%\LagLens\captures\` and
  `%LOCALAPPDATA%\LagLens\logs\`
- Source-mode captures/logs: `<repo>\captures\` (ignored by Git)
- Phase B acceptance: `docs/ACCEPTANCE_PHASE_B.md`
- Phase UI design audit: `docs/PHASE_UI_DESIGN.md`
- UI-1 implementation notes: `docs/UI1_IMPLEMENTATION.md`
- UI-1 acceptance: `docs/ACCEPTANCE_UI1.md`
- UI-2 implementation notes: `docs/UI2_IMPLEMENTATION.md`
- UI-2 acceptance: `docs/ACCEPTANCE_UI2.md`
- UI-3 implementation notes: `docs/UI3_IMPLEMENTATION.md`
- UI-3 acceptance: `docs/ACCEPTANCE_UI3.md`
- Palworld UI regression checklist:
  `docs/REGRESSION_CHECKLIST_PALWORLD_UI.md`
- Palworld UI regression acceptance:
  `docs/ACCEPTANCE_UI_REGRESSION_PALWORLD.md` (core flows tested;
  edge cases not covered)
- Phase C design: `docs/PHASE_C_DESIGN.md`
- C-1 implementation: `docs/C1_IMPLEMENTATION.md`
- C-1.1 real timebase/overhead validation:
  `docs/C1_TIMEBASE_VALIDATION.md`
- C-2.0 QPC time synchronization integration:
  `docs/C2_0_QPC_INTEGRATION.md`
- C-2.1 evidence-based diagnostic engine:
  `docs/C2_1_DIAGNOSTICS.md`
- C-2.2 reliability and false-positive validation:
  `docs/C2_2_RELIABILITY.md`
- C-3 diagnostic UI and reports: `docs/C3_IMPLEMENTATION.md`
- C-3 real-data screenshots:
  `captures/c3_diagnostics_en.png`,
  `captures/c3_diagnostics_zh.png`
- C-4 guided troubleshooting: `docs/C4_IMPLEMENTATION.md`
- C-4 real-data screenshots:
  `captures/c4_troubleshooting_en.png`,
  `captures/c4_troubleshooting_zh.png`
- UX-4 plain-language diagnostics: `docs/UX4_PLAIN_LANGUAGE.md`
- UX-4 real-data screenshots:
  `captures/ux4_plain_en.png`,
  `captures/ux4_plain_zh.png`,
  `captures/ux4_technical_en.png`,
  `captures/ux4_technical_zh.png`
- UX-4 capture workflow / first-use help: `docs/UX4_WORKFLOW.md`
- UX-4 workflow screenshots:
  `captures/ux4_live_onboarding_en.png`,
  `captures/ux4_live_onboarding_zh.png`,
  `captures/ux4_auto_analysis_en.png`
- Release-1 packaging documentation: `docs/RELEASE1_PACKAGING.md`
- Release-1 build script: `packaging/build_windows.ps1`
- Release-1 PyInstaller config: `packaging/LagLens.spec`
- Release-1 EXE: `dist/LagLens/LagLens.exe`
- Release-1 ZIP: `dist/LagLens-v0.1.0-win64.zip`
- Release-1 file list: `dist/LagLens-v0.1.0-win64-files.txt`
- Release-1 packaged screenshots:
  `captures/release1_exe_live_en.png`,
  `captures/release1_exe_live_zh.png`,
  `captures/release1_exe_recent_en.png`,
  `captures/release1_exe_analysis_en.png`,
  `captures/release1_exe_analysis_zh.png`,
  `captures/release1_exe_legacy_en.png`
- Grouped diagnostics fix: `docs/GROUPED_DIAGNOSTICS.md`
- Grouped diagnostics screenshots:
  `captures/grouped_summary_en.png`,
  `captures/grouped_event_detail_en.png`,
  `captures/grouped_summary_zh.png`
- UI-4 single-window implementation: `docs/UI4_SINGLE_WINDOW.md`
- UI-4 screenshots:
  `captures/ui4_analysis_en.png`,
  `captures/ui4_analysis_zh.png`,
  `captures/ui4_analysis_min_zh.png`
- Analysis page now shows the full report inline: overview metrics, every
  grouped finding with severity/confidence/evidence/limits/advice, and all
  anomaly events with expandable CPU/GPU detail. See
  `docs/ANALYSIS_INLINE_REPORT.md`.
- Inline report screenshots:
  `captures/analysis_inline_en.png`,
  `captures/analysis_inline_report_en.png`,
  `captures/analysis_inline_events_en.png`,
  `captures/analysis_inline_zh_min.png`
- Release-2 audit: `docs/RELEASE2_AUDIT.md`
- Report loading/switch/scroll performance: `docs/PERFORMANCE_LOADING.md`
- Performance GUI acceptance: `docs/ACCEPTANCE_PERF_LOADING.md`
- AI streaming contract and acceptance: `docs/AI_STREAMING.md`
- Multi-provider AI design and acceptance: `docs/MULTI_PROVIDER.md`
- Release-2 stutter summary fix: `docs/AI_STUTTER_SUMMARY.md`
- LagLens 2.0 request-body budget: `docs/AI_REQUEST_BUDGET.md`
- AI streaming screenshots: `captures/ai_stream_partial_zh.png`,
  `captures/ai_stream_done_zh.png`
- Performance screenshots: `captures/perf_loading_zh.png`,
  `captures/perf_analysis_komadori_zh.png`,
  `captures/perf_chart_komadori_zh.png`,
  `captures/perf_scroll_komadori_zh.png`,
  `captures/perf_after_switch_zh.png`,
  `captures/perf_loading_en.png`,
  `captures/perf_analysis_komadori_en.png`
- Public release materials: `README.md`, `README_zh-CN.md`,
  `CHANGELOG.md`, `CONTRIBUTING.md`,
  `docs/RELEASE_NOTES_v0.1.0.md`, `docs/GITHUB_RELEASE_v0.1.0.md`
- Packaged data root: `%LOCALAPPDATA%\LagLens`; override with
  `LAGLENS_DATA_DIR`. Do not reintroduce developer-drive paths.
- Real douyin regression report comparison:
  `<release-validation>\douyin_before.md`,
  `<release-validation>\douyin_after.md`
- UI screenshots:
  - `captures/ui_a2_en_live.png`, `ui_a2_zh_live.png`
  - `captures/ui_a3_en_analysis.png`, `ui_a3_zh_analysis.png`
  - `captures/ui_b2_en_recommended.png`, `ui_b2_zh_recommended.png`
  - `captures/ui_b2_en_all_collision.png`, `ui_b2_zh_all_collision.png`
  - `captures/ui_b2_en_main.png`, `ui_b2_zh_main.png`
  - `captures/ui_b3_en_dialog.png`, `ui_b3_zh_dialog.png`
  - `captures/ui_b3_en_launcher.png`, `ui_b3_zh_launcher.png`
  - `captures/ui_b3_en_main_locked.png`, `ui_b3_zh_main_locked.png`

## Current limitations

- Raw PresentMon logs and technical CSV details remain English by design.
- Detailed metric tooltips/reference ranges and target FPS are Phase C.
- Analysis window selection is not persisted between windows yet.
- Swap-chain choices are labelled by address, not window names.
- No real-game hardware validation for the i18n phases.
- Process recommendations are heuristic. Visible-window user apps such
  as Chrome can appear; Windows shell/system paths are excluded.
- The dialog's recommendation-signal column can truncate long text; the
  selected reason panel and tooltip show the complete text.
- Success memory requires the process to still be running and its
  creation time to be verifiable. Immediate exit means no record.
- PID reuse is guarded by the capture CSV cutoff plus a 5-second
  tolerance; a reuse inside that tolerance is theoretically possible.
- Launcher detection relies on visible top-level windows; an unusual
  hidden or full-screen process may be treated as a launcher.
- Phase B final acceptance included a real Palworld PresentMon/ETW
  capture (11,385 frames, ~161 s) that validated capture, analysis,
  success path memory and dialog ranking.
- The B-3 launcher guidance, damaged-CSV memory rejection, PID-reuse
  rejection and target lock were not exercised by that real run; they
  remain automated-test/controlled-screenshot evidence only.
- B-3 UI screenshots show controlled/synthetic states, not the real
  Palworld session.
- UI-1 replaced the 13px QSS fonts with system-anchored point-size
  roles, tabular numbers, font-aware chart gutters and pixel-aligned
  chart grids. UI-2/UI-3 still need to unify the design system and
  page-level layout.
- UI-1 verification used simulated 125%/150% display scaling via
  `QT_SCALE_FACTOR` and simulated 100% text scale; these are not
  physical monitor tests. See `docs/UI1_IMPLEMENTATION.md`.
- UI-3 adds page-level capture/metric/chart cards, responsive KPI
  grids, a centered settings column with data locations, analysis
  section cards and process-dialog subtitles.
- Phase UI passed a real Palworld regression for the core capture and
  CSV analysis workflow. Process-dialog edge cases, failure paths,
  missing-NVML, physical multi-monitor/DPI scaling, VRR and several
  other scenarios remain unverified in the real-game run.
- C-1 now writes timestamped JSONL telemetry sidecars at 4 Hz
  nominal (configurable) with explicit missing values, GPU identity and
  PID-reuse handling.
- C-1.1 real validation confirmed that PresentMon stdout buffering
  makes row-arrival time 1–2 s shorter than the CSV span. The default
  CSV timebase is therefore `untrusted` in practice; C-2 must not use
  it for frame-level correlation.
- PresentMon QPC output (`--qpc_time_ms` / `--qpc_time`) was verified
  to share the Python monotonic/QPC epoch within 0.01 ms. C-2.0 now
  exposes `--qpc_time_ms` as a default-off opt-in; the default CSV
  remains legacy `CPUStartTime`.
- QPC capture uses `CPUStartQPCTime`; the parser normalizes it with a
  recorded capture-start origin and preserves the raw value plus
  timebase/sync metadata. A missing sidecar falls back to a first-frame
  origin and relative-only analysis.
- Observed 4 Hz cadence is about 264 ms (3.78 Hz) because of Windows
  wait-timer granularity; exact 4 Hz would need a separate
  high-resolution timer change.
- 4 Hz sampler overhead measured about 0.34% of one logical core in
  isolation and about 0.53% inside the real LagLens process; whole
  process at 4 Hz averaged about 0.99% versus 0.42% with telemetry off.
- Per-process GPU/VRAM attribution is not implemented; GPU association
  is marked unknown.
- C-2.0 QPC mode has automated tests and real hidden-window capture
  evidence, but no separate visual/screenshot acceptance yet.
- C-3 attaches the C-2 diagnostics to FrameViewer: localized summary,
  finding list/detail, local stutter events linked to the chart and
  selected-frame panel, time-sync/telemetry status, conservative advice
  and JSON/Markdown report export.
- C-3 normal UI never emits `confirmed_by_control`; the engine default
  keeps controlled confirmation disabled. Suggestions are experiments,
  not confirmed causes.
- C-2.1 real validation found that the current C-1 sidecar's target
  CPU samples were all 0.0 in the QPC run. C-2.2 fixed the sampler
  process-object lifecycle; a real busy process and a post-fix QPC
  sidecar now produce non-zero target CPU values. Pre-fix sidecars
  remain 0.0 and diagnostics still flag them.
- C-2.2 tightens local-event independence (overlapping windows merged),
  adds positive/negative/boundary and synthetic reliability-matrix tests,
  and requires comparable scenario/settings/duration/frame-count A/B
  metadata before `confirmed_by_control`.
- C-2.1/C-2.2 rule thresholds are initial hypotheses calibrated with
  synthetic fixtures and real captures, not a labeled real-game corpus.
- C-2.2/C-3 have no real confirmed A/B cause; all real findings remain
  observational. C-3 screenshots are static real-data captures;
  simulated 125%/150% and 980x760 minimum-window checks passed, but
  physical monitor/DPI and full interactive manual acceptance remain
  pending.
- C-3 UI now separates fixed-threshold stutters from local dynamic
  anomalies, shrinks small event/finding lists, and uses a
  summary/Why/Evidence/Limitations hierarchy.
- C-4 adds four-step localized guides for CPU/GPU/mixed/memory/
  presentation/data-quality findings. Guide completion is in memory per
  category and is not persisted between windows.
- C-4 re-check only prefills the target and switches to the Live tab; it
  does not start a capture or change PresentMon/QPC settings.
- C-4 guides are general category checklists, not automatic per-finding
  plans. No automatic A/B comparison, network diagnostics or cloud
  functionality was added.
- UX-4 makes plain-language diagnosis the default UI. Raw metrics,
  claim levels, QPC/telemetry state and engine evidence are available in
  a collapsed technical section rather than being removed.
- UX-4 glossary and technical sections start collapsed. Raw engine
  evidence/caveats remain English technical text; Markdown keeps a
  technical subsection and JSON remains the canonical structured export.
- Missing telemetry or untrusted time alignment is explained in the
  plain view; the UI never fills in unavailable hardware data.
- UX-4 auto-analysis opens only for complete, valid captures after the
  worker has fully finished and telemetry has been closed. Empty,
  incomplete, cancelled or abnormal captures do not auto-open.
- Recent captures are stored in the existing INI (maximum 8, no
  database). Missing files, damaged CSVs and missing sidecars degrade to
  warnings or normal analysis with limited hardware context.
- The UX-4 quick-start card is non-modal and dismissible; dismissal is
  stored in `ui/onboarding_seen`. A fresh elevated ETW capture remains
  pending because this session's shell was not elevated.
- C-3 report export is local Markdown/JSON only. Release-1 packaging is
  prepared locally; GitHub publication/push has not been performed.
- Release-1 packaged EXE/ZIP were built successfully and non-elevated UI
  checks passed. A fresh elevated ETW capture remains the release blocker;
  it was not performed because this session's shell is not elevated.
- Pre-release grouped diagnostics merges repeated findings by
  category/code, shows one anomaly summary and one event table, and keeps
  event details hidden until a row is selected. Markdown is grouped;
  JSON retains all raw findings/events.
- Periodicity is presentation-only and calculated from event timestamps.
  It reports only the matching subset (for example 7 of 8) and never
  assigns a cause.
- UI-4 replaces the standalone analysis window with an embedded Analysis
  tab. Analysis entry points share one viewer page; re-check returns to
  Live Frames without starting capture or reusing a PID.
- UI-4 embedded C-4 steps use checkbox + wrapped-label rows so minimum
  window and 125%/150% simulated scaling do not introduce horizontal
  scrolling.
- Live/Analysis content scrolls vertically at the current 182% text
  scale; this is intentional so text is not clipped.
- Narrow process-dialog path cells can middle-elide; tooltips contain
  the full path.
- UI-2 uses Fusion plus a global tokenized stylesheet; some native
  subcontrols (such as spin-box arrows) remain Fusion-rendered with the
  dark palette.
- UI-2 assets (`assets/check.svg`, `assets/chevron-down.svg`) must be
  included if the application is packaged as a frozen executable.
- Optional AI insight and an embedded AI assistant page are implemented
  in `docs/AI_INSIGHT.md`. Both use one shared report summary from
  `ai_insight.build_report_summary`; `deepseek_client.py` remains the
  only HTTP client and reads `DEEPSEEK_API_KEY` or an in-memory hidden
  prompt key. The Analysis page classifies stable target, known 30 FPS
  cap with default/explicit target, sustained explicit-target low FPS,
  repeated unevenness, stalls and missing display data. Evidence is
  generated only for attention statuses, with stall windows aligned by
  frame timestamps and telemetry `t_ms`. The AI assistant is a top-level
  main-window page (Analysis → Ask AI), not a separate window. It stores
  one session and draft per report path, keeps the transcript scrollable
  and the composer fixed, blocks duplicate sends, keeps questions for
  retry, isolates late replies, and trims older turns and optional detail
  before the latest question/core facts under the 4 KiB body limit.
  Mocked-HTTP tests cover success, failure and follow-up context; no real
  DeepSeek key or new capture was used. No server, deployment, push or
  release was added.
- Real gateway/public network sampling is implemented in
  `docs/NETWORK.md`. The Network tab runs standalone or with a game
  capture, reuses one sampler, writes `<capture>.network.jsonl` only for
  samples inside the capture window, and leaves old reports labelled
  **未采集网络**. Analysis shows network and display verdicts together,
  a MAD-based recent variation, timeouts and a separate chart on the same
  capture-relative x-axis. No game-server probe exists. Real standalone
  ICMP probes succeeded on this machine (gateway 192.168.50.1, public
  target 1.1.1.1). A real joint ETW capture is **not accepted**; the
  original PresentMon error (`access denied`, exit 6) and the shortest
  manual acceptance steps are in `docs/JOINT_CAPTURE_VALIDATION.md`.
- Every normal monitoring session now starts frame capture, hardware
  telemetry and gateway/public probes together from the single Start
  button. The old Local/Online mode choice was removed. A running
  standalone Network test is reused; a capture-started sampler stops
  with the capture, and a capture does not stop a standalone test.
- Each capture now has a `*.session.json` identity file plus
  `session_id` in telemetry/network metadata, a shared
  `perf_counter_ns` origin and wall-clock mapping. Frames, telemetry and
  network use that same origin; QPC frames use the capture origin rather
  than assuming CSV timestamps equal network timestamps.
- Network samples now carry wall time, source, interval and validity.
  Reports distinguish not started, start failed, no valid reply,
  session mismatch, non-overlapping time, normal and abnormal states.
  Telemetry/network from another session is isolated.
- Analysis now starts with a local **Conclusion** card: frame verdict,
  measured-network verdict, and next action. It distinguishes network
  not captured, probes with no valid response, and measured/no obvious
  problem. A separate hardware card shows only telemetry saved with this
  capture and marks unrecorded metrics as not captured. The frame and
  network charts keep separate y-axes and the same capture-relative time
  axis.
- AI requests now share one joint report summary across the quick question
  and follow-up chat. The summary includes display facts, actually saved
  hardware telemetry with process/system/per-frame scope, gateway/public
  network aggregates, missing markers, and 1–2 capture-relative evidence
  windows with nearby baselines. Evidence is preserved ahead of optional
  rules and old conversation under the 4 KiB budget; latest question and
  core/missing facts remain. The default quick question now asks for a
  full analysis (是否存在异常、可能原因、是否需要优化) and optional
  prompts cover smoothness, hardware, network and optimization.
- The "that moment felt wrong" shortcut is deliberately NOT implemented
  until the real joint capture acceptance passes.
- DeepSeek key persistence and provider settings are implemented in
  `docs/AI_SETTINGS.md`. The key is stored in Windows Credential Manager,
  saved key takes priority over `DEEPSEEK_API_KEY`, removal keeps the
  environment fallback visible, and **Test connection** sends only a
  minimal request after a click. The AI assistant offers **前往 AI 设置**
  when no key is available.
- Project-local diagnostic skill `network_vs_local` is implemented in
  `docs/AI_SKILL.md` and `ai_skills.py`. It is a short rule card injected
  only for network/stutter/differentiation questions, including
  context-dependent follow-ups, and not for metric explanations or normal
  "需要改吗" questions. LagLens has no network sampler: reports without
  network data say so, and synthetic probe data is used only in tests.
  The card is optional in the 4 KiB budget; it is dropped before core
  facts, missing-data markers and the latest question. No extra model
  call is made to select it.
- Evidence-driven diagnosis is implemented in `diagnosis_pipeline.py`
  and `docs/EVIDENCE_DIAGNOSIS.md`. Python owns scenario detection,
  data-quality checks, fact IDs, the local evidence-strength ceiling and
  the allowed conclusions; the AI may only produce observations,
  hypotheses and one low-risk action through those fact IDs. Video,
  browser and unknown scenarios cannot conclude `local_performance`;
  `video_source_fps` is an explicit unknown; a missing probe total never
  yields a timeout rate; unverified time alignment rejects simultaneous
  network/frame claims.
- The AI answer is validated once, repaired once, then replaced by a
  local fact fallback if still invalid. The Analysis verdict card offers
  a scenario override, and a change refreshes only the chat session with
  the same `report_key`.
- The Analysis header has an in-window report switcher
  (`docs/REPORT_SWITCHER.md`). It reuses `recent_captures`, sorts by
  capture time descending, shows program, capture time, duration and
  data status, validates the selected file and calls `show_analysis`.
  It never starts PresentMon or calls AI; the current report is kept on
  cancel or on a missing/damaged file. `report_key` and `session_id` are
  updated with the new report, and the chat does not relink until the
  user asks AI on the new report.
- The AI default quick question now asks for a full assessment: whether
  an anomaly exists, possible causes, and whether optimization is needed.
  Optional prompts cover smoothness, hardware, network and optimization.
  The validator rejects hardware-bottleneck claims without valid
  CPU/GPU/memory facts, network-normal claims without network data, and
  advice without a supporting fact or missing-evidence note.
- Numeric validation now attributes each number to the cited fact's own
  `value`, event time (`time_s`) or capture/sample window (`window_s`).
  The real chrome capture with a 5.695 s stall at 11.125 s accepts “at
  about 11 秒”; “12 秒”, the same number under the wrong fact, and
  `verified_qpc` treated as network health are still rejected.
  `session_status=unknown` stays unknown with a “missing metadata, not
  success” limit. A failed repair now shows a plain-language note instead
  of raw internal strings.
- AI requests write a bounded local JSONL diagnostic log
  (`docs/AI_DIAGNOSTICS.md`) under `%LOCALAPPDATA%\LagLens\logs`: model,
  hashed report ID, basename, session ID, scenario, quality, parse and
  validation types, failed fact IDs/numbers/units, repair result, final
  AI/fallback and token usage when available. Keys, chat text, raw
  responses and full paths are excluded; 5 MiB active + 5 MiB backup,
  backups older than 7 days pruned.
- The AI assistant now defaults to the older free-form answer mode: the
  model's text is shown directly without JSON/number validation, so it no
  longer falls back when a fact ID or unit is misattributed. The local
  report and facts remain in Analysis. The strict structured diagnosis is
  retained as an opt-in with `LAGLENS_AI_MODE=structured`; structured
  tests remain. This was chosen after the strict path produced repeated
  fallback on real captures.
- Free-form real acceptance on 2026-11-14: the same `douyin.exe` capture
  used 1 API call and 1,320 tokens; `mode=freeform`, `final_source=ai`,
  `structured=false`, and the text was displayed directly (no fallback).
  The answer treated the 27 FPS as possibly source/app-limited, asked for
  the playback context around the 1 s stall, and did not recommend blind
  setting changes. Free-form answers are not structurally fact-validated.
- AI answer language follows the question language first, then the current
  UI language. The linked report context refreshes its language even if the
  UI is switched after linkage; existing messages are not retranslated.
  This fixes the “switched to English but still got Chinese” path.
- English verification on 2026-11-14: linked the Chinese douyin report,
  switched the UI to English, and asked the English full-analysis question.
  The log recorded `language=en`; 1 free-form call, 1,330 tokens, and the
  answer was in English. The UI was then returned to system/Chinese while
  the English answer stayed in the transcript.
- The free-form prompt now answers only the current question: language,
  capability and off-topic questions get a direct answer without a
  performance summary; conclusions/numbers already stated are not repeated
  in full; no full report rewrite unless a new analysis is requested.
- No-repeat verification on 2026-11-14: a prior performance summary was
  seeded in history, then “Can you speak Japanese?” was sent. The real
  free-form call (1 request, 932 tokens) answered only “Yes, I can speak
  Japanese. What would you like to know?” and did not repeat the summary.
- Automated coverage is 762 tests, including the Douyin regression:
  27 FPS with high `CPUBusy` and low GPU utilization is not accepted as a
  CPU bottleneck. A real joint ETW capture is still unverified.
- Real AI acceptance on 2026-11-14: after saving a valid key, the Chrome
  capture completed in the GUI with 2 API calls (first answer + one
  repair), 2,684 tokens, `final_source=ai`, `repair_ok=true`, conclusion
  `insufficient_evidence`. It reported the 5.695 s stall at 11.125 s
  separately, listed the browser/CPU facts, said network data was
  unavailable, and recommended a repeat capture. The first answer was
  rejected only because it used 60 FPS for `display_fps`; the repair fixed
  it. An earlier attempt with the old environment key returned HTTP 401
  and produced no tokens.
- One Qt6Core access-violation crash occurred during the earlier v2
  attempt after two failed/fallback cycles; it was not reproduced during
  the successful v3 attempt. Treat it as an open risk until reproduced.
- Report loading/switch/scroll performance is implemented and verified
  on 2026-11-14 (`docs/PERFORMANCE_LOADING.md`,
  `docs/ACCEPTANCE_PERF_LOADING.md`). On a real 140,699-frame capture,
  click-to-report went from 9,381 ms to 3,446 ms (offscreen) / 3,472 ms
  (native GUI) while `show_analysis` returns in ~2 ms; local stutter
  detection went from 5.27 s to 0.091 s with identical events; the chart
  paints 1,378 display points instead of 140,699 and costs 11.5 ms
  instead of 762.8 ms. Statistics, stutter detection, export and AI
  facts still use every frame. A late large-report load never overrides a
  newer report; the AI page follows the active report's `report_key`.
  Remaining limits: one ~250 ms main-thread hitch while the viewer is
  built, and the packaged EXE was only verified for start/close, not
  click-through loading.
- The AI assistant uses a provider-neutral streaming contract
  (`ai_stream.py`) and DeepSeek's real SSE endpoint
  (`deepseek_client.stream_insight`). The chat layer only consumes text
  deltas and a completion marker; it does not parse provider fields and
  never shows `reasoning_content`. The first delta appears before the
  answer finishes; the UI coalesces renders at 40 ms. Free-form chat
  streams; the opt-in structured diagnosis keeps its buffered validate-
  then-show path.
- Stop, disconnect and timeout keep the visible partial reply, mark it
  `complete=False` and show a localized “incomplete/stopped” note. Such
  a reply is excluded from the next request's history, is never
  auto-resent, and a manual retry is a fresh request. Each request is
  guarded by a request id, so a late delta cannot touch a newer reply; a
  report A stream keeps writing only its own session while B is active.
- Real DeepSeek acceptance on 2026-11-14 (native Windows GUI, saved key,
  one report-level question): first text at 0.688 s, first visible at
  0.829 s, completion at 1.531 s, 37 incremental growth events, usage
  present, main-thread max gap 80 ms. Two earlier runs showed 0.844/1.016/
  1.985 s and 1.282/1.282/2.219 s. Screenshots:
  `captures/ai_stream_partial_zh.png`,
  `captures/ai_stream_done_zh.png`. Key, question and answer text were not
  printed or logged.
- Stop takes effect at the next received chunk; a fully stalled socket
  keeps the connection until the socket timeout. Only DeepSeek has been
  verified; OpenAI/Claude/Gemini must each use their own real streaming
  protocol and repeat the “first segment visible before completion”
  acceptance.
- Multi-provider support is implemented on the same streaming contract
  (`docs/MULTI_PROVIDER.md`): DeepSeek (Responses-style SSE), OpenAI
  Responses API, Claude Messages API and Gemini streamGenerateContent.
  Settings → AI service selects provider and model and stores each key in
  its own Credential Manager target; the DeepSeek target is unchanged, so
  existing keys keep working. Switching only persists the selection and
  never sends a request. A request snapshots provider/model/key at send
  time and records them on the reply.
- Real multi-provider GUI check on 2026-11-14 used the douyin capture.
  DeepSeek passed: first text 0.672 s, first visible 0.781 s, completion
  0.859 s, 8 chunks, usage present. OpenAI was called with gpt-4.1 and
  returned HTTP 401 from the environment key, so its real stream is NOT
  verified. Claude and Gemini had no key: the missing-key path was
  verified in the GUI (no request, settings hint), real calls are not
  verified. Never report a 401 as a streaming pass.
- Strict structured diagnosis (`LAGLENS_AI_MODE=structured`) remains
  DeepSeek-only; other providers use free-form streaming.
- The shared AI summary now carries the abnormal long-frame total, the
  count of events ≥1 s and the event time span, not only the longest
  event (`docs/AI_STUTTER_SUMMARY.md`). On the real Cyberpunk 2077
  capture (12 events, 10 ≥1 s, longest 3.538 s) the DeepSeek answer
  reported both totals and said the telemetry timebase was unverified,
  so CPU/GPU could not be blamed; gateway/public probe timeouts were
  explicitly not attributed to the game server. The 4 KiB stream budget
  needed compact-mode tightening (3,992 bytes for the standard quick
  question) while statistics, stutter detection, export and fact values
  still use every frame.
- Release-2 packaged in-game acceptance (fresh 2–3 min Cyberpunk capture
  from the ZIP EXE, report open/export, real DeepSeek answer) is still
  pending and requires the game and an elevated capture shell.
- The AI request body is now measured exactly as the provider adapter
  sends it (`docs/AI_REQUEST_BUDGET.md`). The fixed 64 B reserve is gone;
  a 4,096 B body is allowed to send and an incompressible 4,097 B body is
  rejected locally. The two-minute Douyin capture that was rejected at
  4,034 B vs 4,032 B now fits. The two-hour simulated 432,000-frame
  report exports Markdown with a second-half 4.2 s event and produces a
  4,001 B DeepSeek body while keeping total frames, P95/P99, event totals,
  ≥1 s count, longest event, network timeout/rate and telemetry alignment.
  The compact text drops only secondary facts; failure reasons distinguish
  an over-long question from a summary that cannot be compressed, and the
  diagnostic log records only bytes/limit/stage.
- LagLens 2.0 packaged acceptance with the new `LagLens-v2.0.0-win64.zip`
  (open the existing 5,620-frame Douyin record, real DeepSeek full
  analysis and compare numbers) is pending; the 2–3 minute real game
  capture/export is also pending user operation.

## Modular map

| File | Responsibility |
|---|---|
| `capture_core.py` | PresentMon command, log decoding, CSV validation, failure codes |
| `main.py` | Single main window, hardware/live/analysis/AI assistant/settings tabs, recent captures and first-use help |
| `frame_viewer.py` | Embeddable analysis widget, charts, chain panel, diagnostics, guided troubleshooting and AI report context |
| `ai_insight.py` | Shared local report classification, network evidence, one-shot/chat payloads and 4 KiB budget |
| `diagnosis_pipeline.py` | Scenario detection, data quality, fact IDs, evidence ceiling and structured-answer validation |
| `ai_skills.py` | Optional project-local diagnostic rule cards and trigger selection |
| `ai_chat.py` | Embedded AI assistant page, per-report sessions, drafts, retry and context isolation |
| `ai_settings.py` | Settings → AI service key and connection-test UI |
| `capture_session.py` | Shared session ID, monotonic/wall timebase and sidecar metadata |
| `network_sampler.py` | ICMP gateway/public sampler, capture recorder and network sidecar |
| `network_page.py` | Live Network tab and shared sampler controls |
| `network_chart.py` | Capture-aligned gateway/public latency chart |
| `credential_store.py` | Windows Credential Manager read/write/delete |
| `frame_stats.py` | FPS/percentile/1% Low/stutter statistics |
| `deepseek_client.py` | Standard-library DeepSeek client, saved/env/session key precedence and typed errors |
| `swap_chains.py` | Chain grouping, selection, translatable reason parts |
| `process_catalog.py` | Process enumeration, ranking, path memory |
| `process_dialog.py` | Independent Recommended/All process picker |
| `ui_theme.py` | Design tokens, global dark theme, fonts, high-DPI setup, chart/table typography |
| `telemetry.py` | C-1 JSONL schema, sidecar IO, timebase calibration |
| `hardware_sampler.py` | C-1 CPU/RAM/GPU/target sampler thread |
| `frame_timebase.py` | C-2.0 legacy/QPC frame time detection, origin and sync quality |
| `diagnostics.py` | C-2.1 pure-Python evidence/confidence diagnostic engine |
| `diagnostic_text.py` | C-3/C-4/UX-4 localized plain, evidence, advice and guide text; grouped anomaly summaries |
| `diagnostic_report.py` | C-3/UX-4 local grouped Markdown/JSON report export |
| `assets/` | Check and combo-chevron SVG indicators |
| `i18n.py` / `locales/` | Language manager and JSON catalogs |
| `settings.py` | Persistent INI settings, recent captures, onboarding state |
| `runtime_paths.py` | Frozen/source resource and application-directory resolution |
| `packaging/` | PyInstaller spec, version info, build/smoke scripts, license notices |
| `vendor/presentmon/` | PresentMon 2.6.0 and its MIT license |
| `win32_support.py` | Single-instance guard, Job Object |
| `tests/` | 710 automated tests |
