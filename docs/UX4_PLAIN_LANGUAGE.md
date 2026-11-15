# UX-4: Plain-Language Diagnostics

Date: 2026-11-12
Status: accepted 2026-11-12. Remaining UX-4 workflow tasks are tracked
in `docs/UX4_WORKFLOW.md`.
Scope: presentation and wording only. The diagnostic engine, capture
pipeline and raw calculations are unchanged.

## 1. Summary

- The default diagnostic view now uses a player-friendly order:
  1. **What we found**
  2. **Why this appears**
  3. **How certain is this?**
  4. **What this does not tell you**
  5. **What you can do next**
- Numeric evidence, raw engine strings, claim/confidence/severity, QPC
  and telemetry status moved into a collapsed
  **Show technical details / 查看专业数据** area.
- The C-4 guided-troubleshooting steps now follow the plain diagnosis
  directly. The older duplicated advice block was removed from the UI;
  the guide is the single action checklist.
- Added a collapsed **Explain these numbers / 解释这些数值** glossary for
  FPS, 1% Low, P99, frame time, QPC and telemetry.
- Updated EN/ZH copy for CPU, GPU, mixed, memory, presentation, data
  quality and insufficient-evidence findings.
- Markdown reports use the same plain-language order and include a
  technical subsection. JSON remains the structured technical artifact
  with `schema_version: 1`.
- Full suite: **454 tests in 14.489 s, OK**.

## 2. Default UI flow

The diagnostic card now reads in this order:

```text
Findings
What we found
Why this appears
How certain is this?
What this does not tell you
What you can do next
Step-by-step troubleshooting
Show technical details
Local dynamic anomalies
```

The plain block explains the finding without showing raw metric names.
For example, an observed CPU association says:

```text
This is a possible link, not a confirmed cause. The evidence is moderate.
```

It does not say that the CPU is faulty, too weak, or the confirmed cause.

### Missing evidence

When telemetry is missing, the plain block adds:

```text
No telemetry sidecar was found. PresentMon frame-level CPU/GPU timing is
still available, but LagLens cannot connect the extra CPU, GPU or RAM
samples to individual frames, so hardware explanations are limited.
```

When the timebase cannot be trusted for frame alignment, it explains that
hardware/frame links are approximate and that a specific slow frame must
not be treated as reliably matched to a hardware sample. Incomplete
telemetry is also called out explicitly. The exact QPC and telemetry state
remains available in the technical section.

## 3. Technical details

The technical section is collapsed by default. It shows:

- localized category and raw category identifier;
- raw `claim_level` plus localized claim label;
- raw confidence plus localized label;
- severity;
- target FPS and frame budget;
- fixed-threshold stutter threshold;
- finding window;
- numeric metrics;
- raw engine evidence strings;
- raw caveats;
- QPC sync, telemetry sample count/completeness and alignment status.

No technical evidence was removed. It is only moved behind a disclosure
control. Raw engine evidence stays in its original English technical form,
consistent with the project rule that raw PresentMon/diagnostic logs remain
technical English.

## 4. Term glossary

A collapsed glossary under the capture summary explains:

| Term | Plain explanation |
|---|---|
| FPS | Frames per second; an average can hide short slow moments |
| 1% Low | Average FPS of the slowest 1% of frames |
| P99 | Frame time slower than 99% of frames |
| Frame time | Milliseconds per frame; lower is better |
| QPC | Windows high-resolution timer used for frame/hardware alignment |
| Telemetry | Optional CPU/GPU/RAM samples; missing telemetry limits hardware/frame links |

## 5. C-4 integration

The existing C-4 guide is kept unchanged in behavior:

- four steps per category;
- checkbox progress and reset;
- per-category in-memory state;
- re-check target prefill without starting capture.

The old standalone advice block was removed because it repeated the guide.
The plain block ends with a short pointer to the guide, then the guide
appears immediately.

## 6. Reports

### Markdown

Each finding now uses:

```text
### category — summary

**What we found**: ...
**Why this appears**: ...
**How certain**: ...
**What this does not tell you**: ...
**What you can do next**: ...

#### Technical details

- Claim: ... (`observed_association`)
- Confidence: ...
- Severity: ...
- Window: ...
- metric lines...
```

The same plain strings are used by the UI and Markdown through
`diagnostic_text`, so the two cannot drift apart. Missing-telemetry and
untrusted-timebase warnings are also included in Markdown.

### JSON

`build_json()` is unchanged. It continues to export
`schema_version: 1` and the structured `report.to_dict()` payload,
including claim levels, metrics, raw evidence, caveats and events.
No compatibility keys were removed.

## 7. Tests

Added or extended:

- `tests/test_diagnostic_ui.py`:
  - plain-language section order;
  - no raw metrics in the default finding detail;
  - technical section collapsed by default, expand/collapse and contents;
  - glossary collapsed by default and term coverage;
  - missing-telemetry and untrusted-timebase explanations;
  - EN/ZH switching for plain text, technical labels and glossary;
  - every category has non-empty plain why/limit/advice copy in EN/ZH;
  - insufficient-evidence certainty wording;
  - finding/event list wrapping without horizontal scroll.
- `tests/test_diagnostics.py`:
  - localized Markdown plain sections and technical subsection;
  - missing-telemetry warning in Markdown;
  - JSON still contains structured evidence and claim levels.

Full suite:

```text
Ran 454 tests in 14.489s

OK
```

## 8. Screenshots

Real Palworld QPC capture:

```text
Palworld-Win64-Shipping.exe_20261112_145654_215377.csv
615 frames, 9.86 s, 39 telemetry samples
```

Committed screenshots:

```text
captures/ux4_plain_en.png
captures/ux4_plain_zh.png
captures/ux4_technical_en.png
captures/ux4_technical_zh.png
```

The plain screenshots show the default collapsed state and the first C-4
step checked. The technical screenshots show both the glossary and
technical details expanded.

## 9. Validation notes

- Minimum window 980×760 checked in EN/ZH.
- Simulated `QT_SCALE_FACTOR` 1.25 and 1.50 checked in EN/ZH.
- Finding/event lists now use `QListView.ResizeMode.Adjust` and disable
  horizontal scrolling, so long plain-language summaries wrap instead of
  being clipped at larger simulated scales.
- These are simulated scaling checks, not physical monitor/DPI tests.

## 10. Limitations

- Raw engine evidence and caveats remain English technical text.
- The glossary and technical section are collapsed by default; their
  expanded state is session-only and is not persisted between windows.
- Markdown's technical subsection keeps localized labels and numeric
  metrics; JSON remains the canonical full structured artifact.
- No diagnostic rules, capture behavior, automatic A/B comparison,
  network diagnostics, cloud features or packaging were added.
