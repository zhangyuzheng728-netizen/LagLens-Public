# Bundled PresentMon

- Product: PresentMon 2.6.0, x64
- Source: https://github.com/GameTechDev/PresentMon
- License: MIT (see `LICENSE.txt`)
- SHA-256: `B2A706BC6AD475749E3B7E3409263AA1E6906D45BDCF993F6DBC0F660188F1AF`

LagLens invokes this executable only as a capture helper. PresentMon
requires an elevated ETW session; LagLens itself is not elevated.

The PyInstaller build copies this file to the distribution folder:

```text
presentmon/PresentMon-2.6.0-x64.exe
presentmon/LICENSE.txt
```
