# GitHub Release Materials — v0.1.0

Status: prepared locally, **not published**. Do not create the public
repository, push, upload assets or publish a release without explicit
maintainer approval.

## Repository description

> Local Windows frame-time capture and evidence-based game performance diagnostics.

## Topics

```text
windows
windows-11
gaming
performance
frame-time
fps
presentmon
etw
diagnostics
pyside6
qt
python
open-source
```

## Release title

```text
LagLens v0.1.0 — Initial pre-release
```

## Release body

Use `docs/RELEASE_NOTES_v0.1.0.md`. Keep the pre-release warning and the
known limitations section. Do not claim that the final elevated ETW
acceptance has passed.

## Suggested assets

```text
LagLens-v0.1.0-win64.zip
LagLens-v0.1.0-win64.zip.sha256
```

The ZIP contains `LagLens/BUILD_INFO.txt`, `LICENSE`,
`THIRD_PARTY_NOTICES.txt`, `LICENSES/` and PresentMon’s MIT license.

## Pre-publication checklist

- [ ] Maintainer approves the final license (currently MIT).
- [ ] Maintainer decides whether to rewrite Git history to remove the
      personal author email and historical developer paths.
- [ ] Final source tests pass.
- [ ] Final package is built from the approved commit.
- [ ] `BUILD_INFO.txt` commit matches the approved source commit.
- [ ] EXE and ZIP SHA-256 values are recorded.
- [ ] ZIP is extracted and smoke-tested on a clean folder.
- [ ] No captures, logs, settings, tests or developer files are in the ZIP.
- [ ] A fresh elevated real-game ETW capture with the final package passes.
- [ ] Repository is created privately first, then reviewed before public.
- [ ] Do not push this working branch to an existing public remote.
