# AI Insight and AI Assistant

## Scope

The main window has two optional DeepSeek surfaces:

- a compact **Ask AI** button on the Analysis page;
- a first-class **AI assistant** page between Analysis and Settings for
  follow-up questions about the explicitly linked report.

The top navigation is Hardware → Live Frames → Analysis → AI assistant →
Settings. The assistant is not a separate system window.

Answer mode: the application defaults to **free-form** answers (the model's
text is shown directly). The strict JSON/fact-validated path is opt-in with
`LAGLENS_AI_MODE=structured`; see `docs/EVIDENCE_DIAGNOSIS.md`.

Answer language follows the question language first, then the current UI
language. Switching the UI after a report is linked refreshes the AI context
language; existing transcript messages are not retranslated.

The free-form prompt answers only the current question. Language, capability
and off-topic questions do not get a performance summary; conclusions and
numbers already stated are not repeated in full; the full report is not
rewritten unless the user asks for a new analysis.

The optional `network_vs_local` diagnostic skill is documented separately
in `docs/AI_SKILL.md`. It is a short project-local rule card injected
only when the question or recent conversation needs it; it is not a
plugin and does not run tools.

Both use `ai_insight.build_report_summary`, the same
`deepseek_client.request_insight` request function and the same 4 KiB
final UTF-8 budget. No server, capture change, history change or export
change is involved.

## Configuration

`deepseek_client.get_api_key()` reads `DEEPSEEK_API_KEY` first:

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
.\.venv\Scripts\python.exe main.py
```

If it is absent, the UI asks for the key with a hidden input dialog. The
key is held in memory for the current process only. It is never written
to the INI file, captures, logs or the repository.

The request uses:

- `POST https://api.deepseek.com/chat/completions`
- model `deepseek-flash`
- `thinking: {"type": "disabled"}`
- a 30 second default timeout

The standard library `urllib.request` is used; no new dependency is
added.

## Shared measured report

`build_report_summary` combines:

- the normal swap-chain selection;
- `DisplayedTime` intervals only for displayed-frame behaviour;
- `FrameTime` separately as game-output context, never as a substitute
  for display timing;
- existing diagnostic findings, data-quality markers and local event
  thresholds;
- optional telemetry sidecar medians when available;
- the target FPS and whether it was explicitly set.

If no valid `DisplayedTime` exists, average displayed FPS, longest
display stall and its position are unknown. A normal-looking
`FrameTime` series does not turn missing display data into a normal
verdict.

## Target semantics

`AppSettings.target_fps_explicit` is true only when
`performance/target_fps` is present in the INI. The default value remains
a diagnostic reference.

- `stable_meets_target`: displayed FPS is within 5% of a known target.
- `stable_known_cap_below_default`: a stable median near a common cap
  (30/60/72/90/120/144/165/240) is below the default reference; it is not
  reported as an anomaly.
- `stable_known_cap_below_target`: the same cap is below an explicit
  target. The summary says the overall frame rate is low, while keeping
  the known-cap context.
- `stable_below_target`: stable and below an explicit target, with no
  common-cap evidence. This is the sustained-low case, not an occasional
  hitch.
- `stable_below_default_reference`: stable below the default reference
  when no explicit target exists; it is not judged as passing or failing.
- `stable_target_unknown`: target is unknown; no pass/fail judgment.

## Display classification

The classification uses the display interval distribution, not just the
average:

- median, P95, P99 interval;
- coefficient of variation and P95/median ratio;
- windowed FPS and window spread;
- intervals above `max(50 ms, median × 2)`;
- notable intervals above `max(100 ms, median × 5)`;
- common refresh-cap detection.

Statuses:

- `insufficient_display_data`;
- `stable_meets_target`;
- `stable_known_cap_below_default`;
- `stable_known_cap_below_target`;
- `stable_below_target`;
- `stable_below_default_reference`;
- `stable_target_unknown`;
- `stable_known_cap_target_unknown`;
- `mostly_smooth_with_stalls`;
- `repeated_uneven`;
- `repeated_uneven_with_stalls`.

Only `stable_below_target`, `mostly_smooth_with_stalls`,
`repeated_uneven` and `repeated_uneven_with_stalls` are
`needs_attention`. Other statuses explicitly tell the model not to hunt
for a bottleneck or schedule a retest.

A normal average cannot hide a notable stall: stall status is checked
before target status. An average-60 pattern that keeps alternating
short and long intervals is classified as uneven even though the mean
meets the target.

## Evidence rules

Evidence is generated only when `needs_attention` is true:

- observed facts;
- supporting or conflicting clues;
- missing information;
- possible investigation directions, explicitly not proven root
  causes;
- up to three representative stall windows.

Stall windows use frame timestamps and telemetry `t_ms`, not the
assumption that `DisplayedTime` and `GPUBusy` on the same CSV row explain
each other. The payload includes an alignment note.

For sustained low frame rate, the report compares game output, displayed
FPS and available CPU/GPU medians. Without a comparison interval or
telemetry it marks that comparison as missing. Low telemetry utilisation
is only a clue against a saturated-component explanation; it is not
proof of another cause.

## Embedded AI assistant page

The Analysis page has a compact **Ask AI** button. Clicking it switches to
the existing AI assistant tab and explicitly links the active report. The
switch itself sends no request and opens no second window.

The assistant page:

- is a normal main-window tab, with the transcript and composer embedded;
- shows the current linked report as `chrome.exe · 本次采集` and a
  **View report** button that switches back to that Analysis page;
- shows **No report linked** on first use; general chat is allowed, but
  the payload explicitly says no capture is linked and must not invent
  frame-rate, stall, CPU/GPU or network facts;
- keeps one scrollable transcript area and a fixed multi-line composer at
  the bottom;
- sends with Enter, inserts a newline with Shift+Enter and does not send
  while an IME preedit/composition is active;
- offers the default quick question **请全面分析本次检测结果，判断是否存在异常、可能的原因，以及是否需要优化。** when a report is linked, plus optional smoothness, hardware, network and optimization prompts; clicking sends the selected prompt and replies in the transcript;
- keeps the conversation and unsent draft when switching tabs;
- keeps one `ChatSession` per report path in `ChatStore`; explicitly
  linking another report switches sessions and drafts without silently
  changing the current report;
- blocks duplicate sends while one request is in flight;
- keeps the question and transcript on failure and exposes Retry.

`ChatStore` is process-local. General chat and each report have separate
sessions. A late reply updates only its own session. Switching the main
Analysis tab to another report does not change the AI page's linked
report; only **Ask AI** (or an explicit future link action) does.

## Chat request budget

Every chat request includes:

- the system prompt and current UI language;
- the compact report summary;
- the latest question;
- recent conversation turns.

The final UTF-8 body is limited to 4 KiB. Trimming order:

1. older conversation turns;
2. optional diagnostic details (segments and detailed findings);
3. representative event windows;
4. the last remaining previous turn.

The report core facts and the latest question are kept. If those alone
exceed the budget, `PromptTooLarge` is raised and the UI asks the user to
shorten the question; nothing is silently cut.

## Verification

Automated tests use mocked HTTP responses; no real API key is needed:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ai_insight tests.test_ai_chat tests.test_ai_ui -v
```

Covered cases include stable target, stable 30 FPS cap with default and
explicit targets, stable explicit-target low FPS, average-60 but uneven,
missing `DisplayedTime`, unknown target, Komadori Inn real-sample values,
continuous follow-up context, page/tab draft retention, report isolation,
late replies, retry, IME composition safety, and long-chat budget
trimming. Main-window tests also verify the tab order, Ask AI linking,
and that selecting another Analysis report does not silently replace the
current AI conversation.

## Current limits

- The local AI run used mocked HTTP responses; no real DeepSeek call was
  made for this change.
- No new ETW capture was performed.
- The AI still cannot prove a root cause and cannot measure input latency
  or network problems.
- Chat history is memory-only and is lost when LagLens exits.
