# Optional PresentMon capture helper

LagLens can analyze existing CSVs without PresentMon. Live capture and local
Windows packaging need the PresentMon 2.6.0 x64 CLI. It is not included in
this source repository.

1. Download `PresentMon-2.6.0-x64.exe` from the
   [upstream v2.6.0 release](https://github.com/GameTechDev/PresentMon/releases/tag/v2.6.0).
2. Place it in this directory as `PresentMon-2.6.0-x64.exe`.
   For running from source you can also select its location in the UI or
   set `LAGLENS_PRESENTMON`. The packaging script expects the default path.

The SHA-256 of the helper used in local Windows builds was
`B2A706BC6AD475749E3B7E3409263AA1E6906D45BDCF993F6DBC0F660188F1AF`.
The upstream MIT notice is in [LICENSE.txt](LICENSE.txt).
