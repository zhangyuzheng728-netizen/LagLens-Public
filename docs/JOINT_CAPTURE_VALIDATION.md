# Joint Capture Validation

## Status

**Real PresentMon + network joint capture is NOT accepted yet.**

The current development shell is not elevated and is not in the Windows
Performance Log Users group. The original PresentMon attempt produced:

```text
warning: PresentMon requires elevated privilege in order to query processes that are
         short-running or started on another account.  Without it, those processes will
         be listed as '<unknown>' and they can't be targeted by --process_name nor trigger
         --terminate_on_proc_exit.
error: failed to start trace session: access denied.
       PresentMon requires either administrative privileges or to be run by a user in the
       "Performance Log Users" user group.  View the readme for more details.
exit code: 6
```

No real joint ETW capture, no real joint sidecar and no real "reopen the
saved joint report" acceptance were performed. A real old CSV plus a
synthetic network sidecar is a layout test only, not acceptance.

## Shortest real acceptance steps

1. Run the new packaged EXE as administrator, or from an account in
   **Performance Log Users**.
2. Open **Live Frames**.
3. Select a running game process, for example Palworld's renderer.
4. Press the single **Start monitoring** button and play normally for
   30–60 seconds. Frames, hardware telemetry and network probes start
   together.
5. Stop. Confirm the new capture has both:
   - a populated `.csv`;
   - a corresponding `.network.jsonl`.
7. Open the automatic Analysis page. Confirm:
   - the first **Conclusion** card has frame and network verdicts;
   - the hardware card shows only telemetry saved with this capture;
   - the network chart uses the same capture-relative x-axis.
8. Close LagLens completely, reopen it from the desktop shortcut, open
   the same capture from Recent Captures, and confirm the network data
   still appears and does not change while the Network page runs live.
9. Separately choose **Local performance**, capture again, and confirm no
   `.network.jsonl` is created for that capture.
10. Start a standalone Network test, then start an online capture, and
    confirm there is only one sampler and the standalone test is still
    running after the capture stops.

Do not implement the "that moment felt wrong" shortcut until this real
acceptance passes.
