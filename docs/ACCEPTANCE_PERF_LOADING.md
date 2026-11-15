# 报告加载/切换/滚动性能验收（2026-11-14）

对应实现说明：`docs/PERFORMANCE_LOADING.md`。
基线提交：`5079870`；本轮改动单独一条本地提交（未推送、未发 Release）。

## 1. 构建产物

| 项目 | 值 |
|---|---|
| 构建命令 | `.\packaging\build_windows.ps1 -Version 0.1.0 -DistRoot "D:\LagLensData\perf_loading"` |
| EXE | `D:\LagLensData\perf_loading\LagLens\LagLens.exe` |
| ZIP | `D:\LagLensData\perf_loading\LagLens-v0.1.0-win64.zip` |
| ZIP SHA-256 | `0932E6322A40860360DD3038660F09B897DCB42E0F6A58DB745201E78858DE5E` |
| 桌面快捷方式 | `%USERPROFILE%\Desktop\LagLens.lnk` → 上述 EXE（已更新并验证可启动） |

打包脚本自带的必需文件、`qwindows.dll`、禁止文件检查全部通过。

## 2. 打包版启动验证（真实 Windows）

| 检查 | 结果 |
|---|---|
| 双击快捷方式启动 | 窗口出现，标题 `LagLens - 实时性能监测` |
| 窗口响应 | `Responding=True` |
| 关闭 | `CloseMainWindow` 后 10 s 内正常退出 |
| `smoke_test_windows.ps1`（临时数据目录） | `startup_ok=True`、`close_ok=True` |

## 3. 真实 Windows GUI 行为验证

在原生 `windows` Qt 平台（非 offscreen）运行当前源码窗口，使用真实
`Komadori_Inn.exe`（140,699 帧 / 24.9 MB）和 `chrome.exe`（1,847 帧）采集，
并用 `QWidget.grab()` 保存真实渲染截图。

| 检查 | 结果 |
|---|---|
| `show_analysis` 返回耗时（大报告） | 2.2 ms |
| 加载页 0.25 s 内的主线程最长停顿 | 15 ms |
| 点击 → 报告可用 | 3,472 ms（后台计算，期间定时器持续触发 29 次） |
| 加载全过程主线程最长停顿 | 253 ms（viewer 构建 + 首次布局/绘制） |
| 图表 `grab()`（含完整重绘） | 45.3 ms，1,378 显示点 / 140,699 帧 |
| 24 个滚动偏移的平均绘制耗时 | 4.6 ms，最大 21.0 ms，滚动范围 4,056 px |
| 图表点击映射 | 显示点 296 → 原始帧 30,222；详情面板打开，事件联动正常 |
| 大报告 A 未完成就切 chrome B | 加载页出现，B 生效 |
| A 在后台完成之后 | 活动报告、viewer、AI `report_key` 仍是 B |
| 中英文加载页 | 中文与英文截图均无混排 |

截图（真实数据，静态捕获，不是交互录屏）：

- `captures/perf_loading_zh.png` — 中文加载页
- `captures/perf_analysis_komadori_zh.png` — 大报告结论/概览/硬件遥测
- `captures/perf_chart_komadori_zh.png` — 降采样后的帧时间图（尖峰保留）
- `captures/perf_scroll_komadori_zh.png` — 滚动后的发现列表
- `captures/perf_after_switch_zh.png` — A→B 切换后显示 chrome 报告
- `captures/perf_loading_en.png` — 英文加载页
- `captures/perf_analysis_komadori_en.png` — 英文报告

## 4. 自动化测试

`.\.venv\Scripts\python.exe -m unittest discover -s tests -t .`

```
Ran 717 tests in 32.324s

OK
```

新增/修改的覆盖：

- `tests/test_analysis_async.py`（4 项）：加载页先出现、A→B 快速切换不串台、
  B 加载后 AI 上下文是 B、失败保留当前报告并能打开另一份。
- `tests/test_diagnostics_optimization.py`（2 项）：滑动窗口停顿检测与旧算法
  逐事件一致；尖峰不被窗口更新掩盖。
- `tests/test_ui_theme.py`：5,000 帧降采样、峰值保留、首尾帧保留、点击索引
  仍指向原始帧。
- `tests/test_capture.py`：同步路径回归；AI 自动跟随当前报告。

## 5. 未验证 / 限制

- **没有用 UI 自动化在打包版 EXE 里点击打开大报告。** 打包版只验证了启动、
  响应和关闭；加载/滚动/切换是在同一份源码的原生 Windows GUI 中验证的。
  两者 UI 代码相同，但这不等于在 EXE 内完成点击验收。
- 滚动“流畅”是 24 个偏移的绘制耗时（平均 4.6 ms、最大 21 ms）推断，没有
  人眼观感或帧时间录制的独立证据。
- 单次 253 ms 的主线程停顿仍在：本轮没有把 viewer 构建拆成多帧增量。它比
  改前的 9.4 s 低两个数量级，但不是零。
- 在加载大报告期间关闭窗口会等待当前解析完成：实测 3,472 ms 的 Komadori
  加载在关闭时也需要约 3.5 s 才退出。等待上限 5 s，超过上限的 worker 保持
  引用而不销毁，避免“销毁运行中的 QThread”导致进程中止。
- 之前的 `Qt6Core.dll` `0xc0000005`（offset `0xebf55`）崩溃未复现也未修复。
- 本轮没有做 ETW 采集、真流式输出、多 AI 服务商或真实联合 ETW 验收。
