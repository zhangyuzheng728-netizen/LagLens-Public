# A-3 Manual Acceptance Record

Date: 2026-11-12
Scope: Phase A-3 localized analysis window, failure codes and chain reasons.
Result: **PASS**

## Evidence

- `captures/ui_a3_en_analysis.png` and `captures/ui_a3_zh_analysis.png`:
  the same `FrameViewer` instance was switched between English and
  Chinese at runtime.
- `captures/ui_a3_en_failure.png` and `captures/ui_a3_zh_failure.png`:
  a damaged CSV reported as `csv_unusable` in the Live Frames tab.
- A read-only acceptance probe checked option widths, wrapped-label
  heights, the failure code/title/message and live retranslation. The
  probe did not modify project source files.

## Checklist

| Check | Result | Evidence |
|---|---|---|
| Live language switching | PASS | One open analysis window changed language without restart: heading, summary, metric help, chain panel, threshold control, chart axis labels, detail hint and bottom note all switched. |
| Technical identifiers | PASS | FPS, CPU, GPU, RAM, PID, CSV, ms, P50/P95/P99 and 1% Low stayed untranslated in both languages. |
| Text truncation | PASS | All 6 swap-chain options fit the combo in both languages (English max 230 px, Chinese max 218 px, 767 px available). Chain reason height was 35 px for 35 px needed; failure status height was 16 px for 16 px needed. Long labels use word wrap. |
| Layout and theme | PASS | At 1100x760 the panels, chart and controls kept the same geometry and dark theme in both languages; no overlap or clipping was visible. |
| Swap-chain options | PASS | Automatic (recommended) plus 5 chain choices were present; every option was localized, and the confidence badge switched between "high confidence" and "高置信度". |
| Failure prompt | PASS | A CSV missing required columns was classified as `csv_unusable`, not `no_frames`. The dialog title switched between "Capture Failed" and "抓取失败"; the high-level message switched languages; the inline status line remained visible. |
| Retranslation safety | PASS | Switching language after a failure updated the status text without reopening the modal dialog. |

## Notes

- The CSV column detail (`CPUStartTime`, `ProcessID`, `SwapChainAddress`)
  remains English in the Chinese message. This is a raw technical
  diagnostic, consistent with the project rule that PresentMon/CSV
  diagnostics stay untranslated.
- Screenshots are generated under `captures/`, which git ignores.
