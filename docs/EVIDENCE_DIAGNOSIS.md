# Evidence-driven diagnosis

Status: implemented and tested, but **not the default AI mode** since
2026-11-14. The application defaults to free-form AI answers; set
`LAGLENS_AI_MODE=structured` to enable the JSON/fact-validated path. The
pipeline, validators and tests remain in the codebase.

Real joint ETW capture remains outside this verification. The structured
path was exercised once with a real provider call on 2026-11-14; it is no
longer the application default.

## Why

The free-form AI prompt could turn “27 FPS”, a high `CPUBusy` and a low GPU
utilization into “CPU bottleneck”, even when the captured application was a
short-video player whose source frame rate was never measured. The report also
had no fact identifiers, so a reply could quote a number that was never
captured and nothing could check it.

The pipeline separates responsibilities:

| Owner | Responsibility |
|---|---|
| Python (`diagnosis_pipeline.py`) | Scenario, data quality, fact IDs, validity, evidence ceiling, allowed conclusions, answer validation |
| AI | Observation, hypothesis, alternatives, missing evidence and one low-risk action, expressed only through fact IDs |
| User | Optional scenario override in the Analysis verdict card |

## Stages

1. **Scenario** — `detect_scenario()` classifies the captured application as
   `game`, `video`, `browser`, `desktop` or `unknown`. A process-name match has
   `medium` confidence for video/game and `low` for browser/desktop, because
   the name does not prove the current activity. The user override in the
   verdict card has `high` confidence and always wins.
2. **Facts** — `build_facts()` produces stable IDs with value, unit, source,
   sample count, time range, `valid` and a plain-language `limit`. Displayed
   FPS is never labelled as video source FPS.
3. **Quality** — `_quality_checks()` reports duration, display samples,
   telemetry samples, network samples/replies/status and timebase. Missing
   required checks lower the status to `limited`; too short or no display data
   makes it `insufficient`.
4. **Evidence strength** — `_strength()` computes a ceiling:
   `insufficient_evidence` for unusable data or an untrusted timebase,
   `limited_evidence` for limited quality/unknown scenario/no network,
   `moderate_evidence` only with verified time and aligned telemetry. The AI
   answer may not exceed it.
5. **Validation** — `validate_structured()` rejects unknown or invalid fact
   IDs, unsupported conclusions, too-strong evidence, more than one action,
   unsafe advice, missing fact support for a hypothesis, misquoted numbers
   (with `%`/ratio and `s`/`ms` equivalence), video “dropped frames” without
   source-FPS evidence, simultaneous network/frame claims without verified
   alignment and network data, hardware-bottleneck claims without valid
   CPU/GPU/memory facts, network “normal” claims when no network data exists,
   and an action with no supporting fact and no missing-evidence note.
6. **Numeric attribution** — each cited fact exposes its own numbers: the
   main `value`, an event time `time_s`, and a capture/sample window
   `window_s`. A number is accepted only when it matches one of the cited
   fact's fields after unit conversion. This distinguishes a stall's timestamp
   (“at 11 s”) from its duration (“5.695 s”), and a capture window from a
   frame interval. A number mentioned under the wrong fact is still rejected.
7. **Fact-ID format repair** — the report lists one fact per line
   (`- display_fps: 67.76 FPS`). If a model copies the whole
   `display_fps=67.76FPS` token as the ID, `normalize_structured_ids()`
   reduces it to the known ID before validation. The number is still checked
   against that fact, so a copied ID with a wrong number remains invalid.
8. **Answer posture** — the prompt asks for “is there a problem?” first:
   `no_clear_issue`, `insufficient_evidence` and “no optimization needed” are
   valid answers. Observations stay factual; causes belong in hypotheses with
   `likely`/`possible`/`unclear`, and an observed anomaly is not a proven
   cause. `verified_qpc` only means the frame timebase is trustworthy; it is
   not a network measurement and cannot rule out a network problem.
8. **Fallback** — when validation still fails after one repair, the chat shows
   the local facts and a plain-language note about what was rejected. Raw
   internal error strings are not presented as diagnostic facts.

## Scenario rules

`game` allows `local_performance`, `network`, `both`, `no_clear_issue` and
`insufficient_evidence` when network data exists.

`video`, `browser` and `unknown` remove `local_performance`. `video` also adds
`video_source_fps` as an invalid/unknown fact with the limit “do not infer
video dropped frames from PresentMon”. Without network measurements,
`network` and `both` are removed for every scenario.

## Network evidence rules

- Facts keep `samples`, `timeouts`, `responses` and `timeout_rate` separately.
- When `samples` is 0, `timeout_rate` stays `None`, `valid=False`, and its
  limit says the total probe count is unknown.
- The rate is `timeouts / samples`; 9 timeouts out of 20 and 9 out of 1000
  produce `0.45` and `0.009`.
- Public probes are never presented as game-server latency.
- Correlation wording (“同时/重合/一起”) is rejected unless
  `network_alignment` is `verified_qpc` or `capture_relative`.

## Repair and fallback

The chat path validates the first answer. On validation errors it makes one
bounded repair request containing the compact report, the original question,
the previous answer and the validation errors. If the repair is also invalid
(or the request fails), the user sees `fallback_text()`: scenario, quality
status and the local fact list. No third call is made and no invalid answer is
stored as a normal reply.

## 4 KiB budget

The structured JSON schema in the system prompt is about 1 KiB. `ai_insight`
therefore trims in this order:

1. older conversation turns;
2. optional diagnostic details and event tables;
3. the optional skill card;
4. compact level 1: drop the duplicate `FrameTime` line, derivable
   `*_responses` facts and the verbose limit section, but keep display,
   network, hardware and fact IDs;
5. compact level 2: drop the human-readable network/hardware lines (the fact
   ID table still carries the values);
6. reduce evidence windows from all to one, then to zero;
7. drop analysis notes.

The latest question, core facts, missing markers, scenario/quality and time
alignment are kept longest. `build_repair_payload()` uses compact level 2,
no evidence windows and byte-limited invalid/error text.

## Real capture regression

`chrome.exe_20261113_171411_475047.csv` reports 67.76 displayed FPS with a
5.695 s longest display stall at 11.125 s. An AI observation such as “at about
11 s there was a 5.695 s stall” was rejected because the validator compared
“11 秒” only with the fact's `value` (the duration). This was a validator
false positive, not a fabricated number.

The fact now carries `time_s=11.125` and `window_s=[0, 26.431]`. The same
answer validates, while “12 秒”, “11 秒” cited as `display_interval_median`,
or an unknown fact ID are still rejected. The regression tests use the real
fact values, including `5.695 s ↔ 5695 ms`, the 26.4 s capture window, browser
scenario wording and the missing-network case.

## Limits of this phase

- Scenario detection is process-name based and can be wrong; the user override
  exists for that reason.
- Browser and `unknown` scenarios deliberately cannot conclude a local
  performance problem.
- `video_source_fps` is not captured and stays unknown.
- The numeric check only inspects numbers followed by `ms`, `%`, `秒`, `s` or
  `FPS`; free-form numbers without a unit are not cross-checked.
- The 4 KiB budget means a long report may lose network evidence windows in
  chat; the facts and data-quality markers remain.
- No performance work, streaming or multi-provider support is included.
