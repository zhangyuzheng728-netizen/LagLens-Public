# Contributing to LagLens

Thank you for helping improve LagLens. This is a Windows desktop tool for
local frame-time capture and evidence-based diagnostics.

## Before you start

- Use Python 3.12 on Windows 10/11 x64.
- Do not add runtime dependencies without maintainer agreement.
- Do not change the PresentMon capture pipeline, frame statistics,
  swap-chain selection or diagnostic algorithms as part of an unrelated
  change.
- Do not operate game windows, trigger UAC/elevation or run ETW captures
  automatically in tests.

## Development setup

```powershell
git clone <your-fork-url>
cd LagLens-Public
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

For packaging work, first download the [PresentMon CLI](vendor/presentmon/README.md):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\packaging\build_windows.ps1
```

## Tests

- Add or update tests for behavior changes.
- Run the full suite before opening a pull request.
- State whether a test was automated, simulated (for example
  `QT_SCALE_FACTOR`), or performed on real hardware. Do not describe a
  simulated display-scaling test as a physical monitor test.
- ETW/real-game capture results are manual acceptance evidence; do not
  claim they passed unless they actually ran.

## Privacy and captures

Do not commit or attach:

- real PresentMon CSV/log files, telemetry sidecars or diagnostic reports
  without removing process names, PIDs, swap-chain identifiers, account
  names and other personal data;
- `LagLens.ini`, local settings, caches or build output;
- screenshots containing user paths, account names or unrelated desktop
  content.

Use synthetic CSV fixtures whenever possible. If a real capture is
essential to reproduce a bug, sanitize it first and describe what was
removed.

## Code style

- Keep the existing structure, naming and localized-string patterns.
- Use `i18n.tr()` keys for user-facing text; keep technical identifiers
  such as FPS, CPU, GPU, RAM, PID, CSV and ms untranslated.
- Preserve the dark theme and existing layout unless the change is
  specifically a UI task.
- Prefer small, focused commits with a clear message.

## Pull requests

Include:

- what changed and why;
- user-visible behavior changes;
- test commands and actual results;
- any manual checks, clearly labeled;
- screenshots for UI changes;
- license implications for new dependencies or assets.

## License

LagLens is distributed under the MIT License. By contributing, you agree
that your contribution can be distributed under the project license.
Do not copy code, assets or license text from an unverified source.
