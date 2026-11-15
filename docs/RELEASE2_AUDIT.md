# Release-2: GitHub Pre-release Audit

Date: 2026-11-13
Baseline: `e441434` (`ui4-single-window`), 498 tests passing
Target: v0.1.0, first public pre-release
Status: audit complete; final package rebuild and elevated ETW acceptance pending

## 1. Scope and outcome

This audit checked:

- current source and Git history for credentials, personal data and
  developer-only files;
- runtime and build dependencies, licenses and redistribution duties;
- the Windows package, data locations, bundled resources and prompts;
- README, release notes and publication materials;
- automated tests and non-elevated packaged checks.

No API keys, tokens, passwords, private keys or cloud credentials were
found. No repository push, GitHub release, UAC prompt, elevation or game
window operation was performed.

## 2. Findings by severity

### Critical

None.

### High

1. **Git history contains personal author metadata and developer paths.**
   All commits in the pre-audit history use the same personal
   author/committer email. Historical revisions also contain `<repo>`,
   `<data-directory>` and
   `<OneDrive-path>` paths. Making the existing history public
   would disclose a personal email address and machine/institution
   details.
   - Current working tree has been sanitized.
   - The history has **not** been rewritten. Rewriting is destructive and
     needs explicit approval before the first public push.
2. **The previous package preferred a developer data drive.**
   `settings.py` previously preferred `<data-directory>` and
   `<data-directory>` on every machine, then the project drive, and only
   used the home directory last. That is not acceptable for public
   distribution.
   - Fixed in source: packaged builds now use
     `%LOCALAPPDATA%\LagLens`, with `LAGLENS_DATA_DIR` as an explicit
     override.
   - The existing ZIP was built before this fix and must be rebuilt and
     re-verified.
3. **No fresh elevated real-game ETW acceptance with the final package.**
   The application and old package passed automated and non-elevated
   checks, but the audit shell did not create an ETW session. A final
   build must be run elevated on a real game and checked for CPU/GPU,
   QPC, telemetry, auto-analysis and Markdown/JSON export.
4. **Qt binary-distribution notice review is incomplete.**
   Qt/PySide6 is used under LGPL-3.0 with separate, replaceable DLLs.
   LGPL text, source URLs and Qt license texts were added. The shipped
   Qt PDF module is built from Qt WebEngine sources and brings
   PDFium/Chromium-family third-party components; the Qt PDF notice
   bundle still needs legal review before a public binary release.
5. **Final license approval is still a maintainer decision.**
   The repository already contains an MIT `LICENSE`. MIT is compatible
   with the current dynamic Qt/PySide6 use, BSD-3, Apache-2.0, PSF and
   the PyInstaller bootloader exception. It is recommended to retain
   MIT, but this audit does not override the maintainer’s approval.

### Medium

1. **Real capture samples existed in source history.**
   `douyin_test.csv` and `presentmon_test.csv` contained real process
   names, PIDs and swap-chain identifiers. The current tree now uses a
   sanitized `sample_capture.csv`; the unused `presentmon_test.csv` was
   removed. Both original blobs remain in Git history.
2. **Unsigned executable.** Windows SmartScreen may warn on first run.
   The README and distribution README explain how to verify the SHA-256.
   Code signing is a future release task, not a code blocker.
3. **Package size / unused Qt modules.** The ZIP includes Qt PDF, QML,
   Quick, Virtual Keyboard and WebEngine translation data that the
   application does not use directly. This is not a functional blocker,
   but trimming the PyInstaller data would reduce the download and the
   third-party notice surface.
4. **Microsoft VC++ runtime notice.** The package redistributes
   `VCRUNTIME140*.dll` and `MSVCP140*.dll` under Microsoft’s
   redistributable terms. A reference was added; a legal review should
   confirm the wording for the distribution channel.

### Low

1. Test fixtures use illustrative `D:\`, `C:\Games` and `C:\Captures`
   paths. They are not real user paths.
2. Development docs mention Palworld and Douyin validation runs. These
   are test context, not credentials or personal account data.
3. `frame_analyzer.py` is a legacy standalone script and is not imported
   by the application. It now points at the sanitized sample.
4. The package includes Qt translation packs for many languages; only
   English and Simplified Chinese are used by the UI.
5. The build is `onedir` and not a single-file executable; this is
   intentional for Qt DLL replaceability and startup time.

## 3. Git history security check

Method: scanned every blob reachable from `git rev-list --objects --all`,
plus commit metadata and commit messages.

| Check | Result |
|---|---|
| Private-key blocks | 0 |
| GitHub/GitLab/AWS/Google/Slack/OpenAI token patterns | 0 |
| Password/secret/API-key assignments | 0 |
| Personal email in commit metadata | present in all pre-audit commits |
| `C:\Users\<name>` paths | 0 |
| `<repo>` | historical revisions of AGENTS.md, docs, scripts |
| `<data-directory>` | historical revisions of docs, README and packaging text |
| `<OneDrive-path>` | historical revisions of AGENTS.md, scripts and older main.py |
| Real capture CSV blobs | `douyin_test.csv`, `presentmon_test.csv` (historical) |
| `.env`, INI, logs, telemetry sidecars, ZIP/build output in history | none found |

Current tree (`HEAD` plus Release-2 changes) has no credentials and no
developer absolute paths in public-facing files. `AGENTS.md` and
`docs/STATUS.md` now use placeholders for the checkout location and
`%LOCALAPPDATA%\LagLens` for user data.

## 4. Dependency and license audit

Verified against the installed package metadata and the packaged files.

| Component | Version | License | Handling |
|---|---|---|---|
| LagLens | 0.1.0 | MIT | `LICENSE`, `LICENSES/MIT-LagLens.txt` |
| Qt / PySide6 / shiboken6 | 6.12.0 | LGPL-3.0-only, or GPL-2.0/3.0/commercial | LGPL option; LGPL text, source URLs, separate replaceable DLLs |
| PresentMon | 2.6.0 | MIT | `presentmon/LICENSE.txt`, `LICENSES/MIT-PresentMon.txt`; SHA-256 recorded |
| psutil | 7.2.2 | BSD-3-Clause | `LICENSES/BSD-3-Clause-psutil.txt` |
| nvidia-ml-py | 13.615.71 | BSD-3-Clause | `LICENSES/BSD-3-Clause-nvidia-ml-py.txt`; NVML driver not bundled |
| Python runtime | 3.12.8 | PSF License | `LICENSES/PSF-Python.txt` |
| PyInstaller bootloader | 6.16.0 | GPL-2.0-or-later with bootloader exception | `LICENSES/PyInstaller.txt` |
| pyinstaller-hooks-contrib | 2026.10 | GPL-2.0-or-later build hooks; Apache-2.0 runtime hooks | build-only; Apache-2.0 text included |
| altgraph | 0.17.5 | MIT | build-only |
| pefile | 2023.2.7 | MIT | build-only |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | build-only |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | build-only |
| setuptools | 84.2.1 | MIT | build-only |
| OpenSSL runtime | 3.0.15 | Apache-2.0 | `LICENSES/Apache-2.0.txt` |
| Microsoft VC++ runtime | 14.x | Microsoft redistributable terms | `THIRD_PARTY_NOTICES.txt` reference |
| libffi / bzip2 / liblzma | bundled with Python | permissive/PSF notices | covered by `PSF-Python.txt` |

Qt license texts were retrieved from the official Qt repositories at tag
`v6.12.0` and placed under `packaging/LICENSES/Qt-6.12.0/`:

- `qtbase` (Core, Gui, Widgets, Network, Svg)
- `qtdeclarative` (QML/Quick)
- `qtvirtualkeyboard`

The authoritative Qt third-party list is
<https://doc.qt.io/qt-6/licenses-used-in-qt.html>. Qt PDF is built from
Qt WebEngine sources; its separate PDFium/Chromium notice bundle remains
a high-priority legal review item.

Qt LGPL compliance measures in the package:

- Qt DLLs and plugins are separate files in `_internal/PySide6`, not
  statically linked into `LagLens.exe`.
- Users can replace them with compatible builds.
- LGPL-3.0 text and Qt/PySide6 source URLs are included.
- LagLens does not modify Qt.
- The application source is MIT and available in the repository.

This is an engineering compliance check, not legal advice. A maintainer
or counsel should review the final notice bundle before publication.

## 5. Windows package audit

The pre-audit package from `e441434` was replaced by a rebuild from the
Release-2 commit. The final artifacts are:

```text
<release-build>\LagLens\LagLens.exe
<release-build>\LagLens-v0.1.0-win64.zip
<release-build>\LagLens-v0.1.0-win64.zip.sha256
```

Rebuilt-package checks:

- `BUILD_INFO.txt` records the Release-2 commit and the EXE/PresentMon
  SHA-256 values.
- ZIP has 520 entries and no CSV, log, INI, JSONL, PDB, PYC, `.git`,
  tests or capture files.
- The package bundles `LagLens.exe`, `_internal` runtime, PresentMon,
  Qt platform plugins, locales, assets, `BUILD_INFO.txt`, `LICENSE`,
  `README.txt`, `THIRD_PARTY_NOTICES.txt` and `LICENSES/`.
- The application’s `_internal/locales` contains only `en.json` and
  `zh_CN.json`; PySide6 Qt translation packs and third-party license
  texts are also bundled.
- EXE startup and normal close passed the non-elevated smoke test.
- The extracted-ZIP smoke test also passed.
- Starting with no `LAGLENS_DATA_DIR` created data only under the
  configured `%LOCALAPPDATA%\LagLens` path.
- Packaged UI checks passed for the embedded Analysis page, English and
  Chinese tabs, QPC + telemetry sidecar, legacy `CPUStartTime` CSV,
  recent captures, re-check (Live tab, prefilled target, missing-process
  message, no capture started, no new capture file) and Markdown/JSON
  export.
- The JSON export contained 9 findings and 8 events, matching the
  in-memory report; Markdown and JSON contained no full user path.
- A binary scan found no user profile path, OneDrive path, QQ email or
  repository path in the package files.
- No Python installation is required.

Exact SHA-256 values are recorded in `BUILD_INFO.txt` and the `.sha256`
file next to the ZIP.

## 6. Data location and admin behavior

- Packaged data root: `%LOCALAPPDATA%\LagLens`.
- Override: `LAGLENS_DATA_DIR`.
- Files: `LagLens.ini`, `captures/`, `logs/`.
- Source-mode captures remain under the repository `captures/` folder,
  which is ignored by Git.
- PresentMon is located at `presentmon/PresentMon-2.6.0-x64.exe` relative
  to the executable, with `LAGLENS_PRESENTMON` as an explicit override.
- Missing/invalid PresentMon shows a localized warning and does not start
  a capture.
- ETW permission is explained before capture. The application asks before
  restarting elevated; it does not elevate silently.
- No developer drive is required at runtime.

## 7. Tests and regression evidence

Full automated suite after the Release-2 changes:

```text
Ran 499 tests

OK
```

Real grouped-diagnostics regression, using the original capture:

```text
capture: douyin.exe_20261112_184509_333905.csv
frames: 6106
timebase: qpc_ms, verified_qpc
telemetry: 543 samples, complete
findings: 9 (1 global CPU pressure + 8 local CPU-associated anomalies)
events: 8
JSON findings: 9
JSON events: 8
Markdown: 3,706 bytes, 82 lines
```

The JSON export keeps every raw finding and event; grouping affects only
the display/Markdown presentation. This confirms 8 local anomaly events
are retained without data loss, plus the separate global finding.

Non-elevated source checks covered the single main window, four tabs,
embedded Analysis viewer, EN/ZH switching, legacy/QPC CSV analysis,
sidecar loading, recent captures, re-check return, Markdown/JSON export
and page switching without stopping the worker.

The rebuilt package was also exercised without elevation:

- opened the QPC `douyin.exe` recent capture with its sidecar;
- opened a legacy `CPUStartTime` `chrome.exe` CSV;
- rendered the embedded Analysis page in English and Chinese;
- exported Markdown and JSON from the packaged UI;
- invoked re-check and confirmed the Live tab, prefilled target,
  missing-process message, no capture start and no new capture file.

The final elevated ETW capture is still a separate manual acceptance
item and is not claimed here.

## 8. Fixes applied in this audit

- Replaced the developer-drive data preference with
  `%LOCALAPPDATA%\LagLens`.
- Added data-location regression tests and updated the test baseline.
- Sanitized the tracked sample CSV and removed the unused real DWM
  sample; updated the standalone viewer/analyzer defaults.
- Removed the hardcoded `douyin.exe` process auto-selection.
- Replaced developer paths in scripts and docs with repository-relative
  or placeholder paths.
- Improved `.gitignore` for logs, INI, JSONL, ZIP, secrets, build output
  and local executables.
- Split runtime and build requirements.
- Added Qt 6.12.0 license texts, OpenSSL/Apache-2.0 text, MSVC runtime
  reference and a Qt source/notice README.
- Added README, Chinese README, CHANGELOG, release notes, contributing
  guide and GitHub release materials.
- Extended the build script’s forbidden-file check to logs, INI, JSONL,
  PDB and PYC files.

## 9. Release blockers and recommendation

Release blockers before any public GitHub release:

1. Perform a fresh elevated real-game ETW capture with the final package
   and verify CPU/GPU telemetry, QPC, sidecar, auto-analysis and
   Markdown/JSON export. This is not a source-code checklist item; it
   requires a real elevated run.
2. Decide whether to accept or rewrite the Git history disclosure of the
   personal email and developer paths. Do not push until this is decided.
3. Confirm the final MIT license choice.
4. Complete legal review of the Qt PDF/third-party notice bundle and the
   final distribution notices.

Recommendation: **do not publish yet**. The source and package are ready
for a private review, and the non-elevated package checks pass, but the
elevated ETW acceptance and the Git-history/license decisions must be
completed first. After those are closed, a private repository review
followed by a public pre-release is reasonable.
