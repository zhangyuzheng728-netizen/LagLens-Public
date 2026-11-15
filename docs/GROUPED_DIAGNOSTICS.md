# Grouped Diagnostics and Concise Reports

Date: 2026-11-12
Scope: presentation/report consolidation before Release-1 acceptance.
No diagnostic rule, threshold, capture command or raw calculation was
changed.

## 1. Real regression sample

Input:

```text
<capture-dir>\douyin.exe_20261112_184509_333905.csv
6106 frames, 136.49 s
telemetry sidecar: 543 samples, complete
timebase: QPC, verified
```

The engine produced:

- 8 local frame-time anomalies;
- 9 findings before grouping (1 global CPU finding + 8 repeated local
  CPU findings).

The event times are:

```text
8.08   28.65   49.22   69.79   90.36   104.36   110.93   131.50 s
```

The dominant interval is approximately **20.57 s**. Seven events fit that
interval; the event at **104.36 s** (48.30 ms) is outside that pattern.
The report does not claim that all eight events share the period and does
not infer a cause.

## 2. UI changes

### Concise overview

A new **Anomaly summary / 异常摘要** block appears once at the top of the
diagnostic card:

```text
Detected 8 local frame-time anomalies.
7 of 8 events follow approximately 20.57 s spacing; 1 event falls outside this pattern.
The interval is calculated from event timestamps only; it does not identify a cause.
All 8 anomalies were associated with increased CPU frame work.
These are observed associations, not confirmed causes.
User-perceived stutter cannot be confirmed from this capture.
```

### Grouped findings

Findings are grouped by `(category, code)` for presentation:

- one global CPU finding;
- one local CPU-anomaly group containing 8 events;
- the local group is shown once with `· 8 events`.

The group detail explains the shared finding once. It does not repeat the
same paragraph eight times.

### Event table

The old per-event list is replaced by one table:

| Time | Duration | Type | Pattern | Key evidence |
|---|---|---|---|---|
| 8.08 s | 129.93 ms | CPU side | Regular | CPU +109.0 ms · GPU +0.3 ms |
| ... | ... | ... | ... | ... |
| 104.36 s | 48.30 ms | CPU side | Extra | CPU +27.4 ms · GPU +0.2 ms |
| ... | ... | ... | ... | ... |

- The table is compact and scrollable.
- Detailed CPUBusy/GPUBusy/GPUWait/display data appears only after the user
  selects an event row.
- Selecting a row also updates the existing chart marker and selected-frame
  panel.
- The local anomaly summary is not repeated per row.

### Technical details

For a grouped anomaly, the technical-details area shows the shared claim,
confidence and severity, plus the group count. It directs the user to the
event table for per-event metrics rather than showing one event's metrics
as if they represented all eight.

## 3. Markdown report

The report now starts with:

```text
## Anomaly summary
- ...
```

Findings are merged by `(category, code)`, with one shared explanation and
at most one advice block per category. The event table follows. JSON keeps
the complete original `findings` and `events` arrays.

### Before / after on the real sample

| Metric | Before | After |
|---|---:|---:|
| Markdown bytes | 11,983 | 3,823 |
| Markdown lines | 230 | 82 |
| Repeated local explanation | 16 occurrences | 2 (heading + What we found) |
| CPU advice occurrences | 9 | 1 |
| Event rows | list of 8 | table of 8 |
| JSON findings/events | 8 / 8 | 8 / 8 |

The two remaining occurrences of the local summary are the group heading
and the required "What we found" field; they are not per-event repeats.

## 4. Periodicity algorithm

`diagnostic_text.event_periodicity()` is a presentation helper:

1. sort only the event timestamps;
2. cluster repeated consecutive intervals within a relative tolerance;
3. require at least two similar intervals and at least three matching
   events;
4. fit a conservative lattice (`max(250 ms, 2% of period)` tolerance);
5. mark matching events as `Regular` and the remainder as `Extra`.

It does not inspect CPU/GPU metrics to decide periodicity and does not
claim a cause. If a pattern is weak or too short, the summary says no
consistent interval was found or that there are too few events.

## 5. Tests

Added `tests/test_diagnostic_grouping.py`:

- 7-of-8 interval fit at approximately 20.57 s;
- extra event remains outside the pattern;
- all-regular and irregular cases;
- empty report;
- repeated finding grouping;
- mixed CPU/GPU group separation;
- event table regular/extra labels;
- one advice block per category;
- Markdown table and JSON raw-data preservation;
- Chinese summary/table localization.

Extended `tests/test_diagnostic_ui.py` for grouped UI, default-hidden event
details, table selection, single event-explanation text, and runtime
language switching.

Full suite:

```text
Ran 487 tests in 14.953s

OK
```

## 6. Screenshots

```text
captures/grouped_summary_en.png
captures/grouped_event_detail_en.png
captures/grouped_summary_zh.png
```

The first/third show the concise summary, grouped findings and table. The
second shows the detailed evidence after selecting the extra 104.36 s
event.

## 7. Boundaries and remaining work

- Diagnostic engine, thresholds and capture pipeline are unchanged.
- C-4 guide remains one guide for the selected category/group.
- JSON remains backward compatible.
- No game window was launched, moved or automated for this regression.
- Release-1 remains blocked on a fresh elevated ETW capture using the
  final packaged build. This CSV regression does not satisfy that item.
