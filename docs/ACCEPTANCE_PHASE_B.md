# Phase B Manual Acceptance Record

Date: 2026-11-12
Scope: Phase B — B-1 process catalog/path memory, B-2 selection
dialog, B-3 settings memory/success recording/launcher guidance.
Result: **PASS**

## Real-game validation

The final Phase B acceptance used a real game session:

- Game: **Palworld / 幻兽帕鲁**
- Capture path: real PresentMon 2.6 + ETW capture
- Result: **11,385 frames, approximately 161 seconds, valid CSV**
- The frame-analysis window opened and displayed normally.
- After reopening the process-selection dialog,
  `Palworld-Win64-Shipping.exe` was **first in the recommended list**
  and showed its historical successful-capture record.

This confirms on real hardware that:

- the PresentMon/ETW capture path still works;
- CSV validation and the analysis window work with a real capture;
- successful executable-path memory is written and read back;
- the stored path participates in real recommendation ranking.

No screenshot of the real Palworld run was committed to the repository;
the statement above is the acceptance result reported by the user.

## B-1 acceptance

Status: **accepted after the captured-PID memory fix**.

Delivered:

- process enumeration with best-effort `psutil` metadata;
- per-process graceful degradation for access-denied or missing paths;
- explainable ranking with path memory, visible windows, memory use and
  a path-based Windows system filter;
- successful-target memory keyed by executable path, never PID;
- memory fix that records only paths verified by ProcessIDs actually
  present in the capture CSV, with no same-name fallback;
- PID-reuse cutoff support.

Evidence:

- commits `11dd859`, `1d8949d`;
- tags `p2-b1-process-catalog`, `p2-b1-memory-fix`;
- 63 B-1 tests at the fix close;
- real Palworld run confirmed path memory and recommendation ranking.

Not exercised on real hardware:

- access-denied path behavior;
- PID reuse;
- same-name/different-path memory rejection.

## B-2 acceptance

Status: **accepted by visual/manual review on 2026-11-12**.

Delivered:

- independent process-selection dialog;
- Recommended / All processes modes;
- live search by name, path and window title;
- refresh with selection preservation only for the same PID/path;
- columns for name, PID, window title, full path, recommendation
  signals;
- no default row selection and disabled Select until the user acts;
- same-name collision warning and explicit name-based targeting note;
- main-window button that only updates the target text and never starts
  a capture.

Evidence:

- commit `0444437`, tag `p2-b2-process-dialog`;
- 21 B-2 tests; full suite 290 passing at B-2 close;
- screenshots:
  - `captures/ui_b2_en_recommended.png`
  - `captures/ui_b2_zh_recommended.png`
  - `captures/ui_b2_en_all_collision.png`
  - `captures/ui_b2_zh_all_collision.png`
  - `captures/ui_b2_en_main.png`
  - `captures/ui_b2_zh_main.png`
- final real Palworld run confirmed the dialog ranks the remembered
  renderer first.

## B-3 acceptance

Status: **accepted as the final Phase B checkpoint on 2026-11-12**.

Delivered:

- `settings.successful_targets` passed into the dialog;
- success recording only from the `info.ok` branch, using CSV
  ProcessIDs and verified executable paths;
- damaged CSVs and failed captures do not create success records;
- PID-reuse protection using the capture CSV cutoff plus a 5-second
  tolerance;
- launcher/renderer hint built on the existing
  `similar_process_names()` detection and visible-window/memory
  signals; suggestions never switch the target silently;
- target controls locked while a capture worker runs;
- English/Chinese texts and runtime language switching;
- full recommendation-reason tooltip and selected-reason panel.

Evidence:

- commit `782e964`, tag `p2-b3-integration`;
- 22 B-3 tests; full suite 312 passing at B-3 close;
- screenshots:
  - `captures/ui_b3_en_dialog.png`
  - `captures/ui_b3_zh_dialog.png`
  - `captures/ui_b3_en_launcher.png`
  - `captures/ui_b3_zh_launcher.png`
  - `captures/ui_b3_en_main_locked.png`
  - `captures/ui_b3_zh_main_locked.png`
- final real Palworld run confirmed settings memory and ranking.

Not exercised in the real Palworld run:

- the launcher/renderer warning triggered by a real launcher, and the
  suggested-renderer result;
- success-memory behavior for damaged CSV or failed capture;
- PID-reuse rejection;
- manual observation of the target lock during a real running capture;
- runtime language switching during a real capture.

Those behaviors are covered by automated tests and/or controlled UI
screenshots, but are **not** claimed as real-hardware validation.

## Final test status

The last full suite run before this acceptance document was:

```text
Ran 312 tests in 9.729s

OK
```

Per the user's instruction, the 312 tests were not rerun for this
documentation-only acceptance checkpoint.

## Phase B closure

Phase B is complete and accepted. The next stage is Phase C:

- metric explanations and reference ranges;
- target FPS;
- remaining Phase C UI and validation work.

## Residual limitations

- Success memory requires the captured process to still be running and
  its creation time to be verifiable. Immediate exit means no record.
- PID reuse inside the 5-second tolerance is theoretically possible.
- Launcher detection depends on visible top-level windows; unusual
  hidden/full-screen processes may be misclassified.
- The recommendation-signal table column can truncate; the tooltip and
  selected-reason panel show the complete text.
