# 报告加载、切换与滚动性能（2026-11-14）

本阶段解决三个实测问题：大报告打开时主线程长时间阻塞、分析页滚动时图表反复
全量重绘、快速切换报告时晚到的旧结果可能覆盖新报告。界面外观、单窗口导航、
AI 自由文本行为均未改动。

## 1. 基线与测量方法

测量都在同一台机器、同一批真实采集上完成，`QT_QPA_PLATFORM=offscreen`
（无显示器依赖），Python 3.12 + PySide6 6.12。

| 样本 | 行数 | 文件大小 | 说明 |
|---|---|---|---|
| `chrome.exe_20261113_171411_475047.csv` | 1,847 | 322,584 B | 普通真实采集 |
| `Komadori_Inn.exe_20261113_114409_249528.csv` | 140,699 | 24,898,006 B | 大真实采集 |

基线（改动前，HEAD `5079870`）：

| 阶段 | Chrome | Komadori |
|---|---|---|
| CSV 读取 | 6 ms | 336 ms |
| timebase | 3 ms | 96 ms |
| swap-chain 索引 | 3 ms | 411 ms |
| 选链 | 1 ms | 152 ms |
| 统计 | 2 ms | 376 ms |
| `FrameViewer` 构建（含诊断 + AI 摘要） | 142 ms | **8,385 ms** |
| 数据 + 界面总计 | 154 ms | **9,381 ms** |
| 图表单次绘制 | 11.1 ms（1,847 点） | **762.8 ms（140,699 点）** |
| 主线程事件循环 | 同步阻塞全程 | 同步阻塞约 9.4 s |

`cProfile` 定位到的两个真实热点：

1. `diagnostics._detect_local_stutters` 对每一帧重新切片 4.5 s 基线窗口并排序：
   Komadori 实测 5.27 s，profiler 下 11.7 s。
2. `ai_insight.build_report_summary` 在 `FrameViewer` 中被调用两次（诊断刷新前
   后各一次），合计约 4.6 s（profiler）。
3. 图表每次 `paintEvent` 都为全部 140,699 帧重建 `QPointF` 并绘制整条折线，
   单次绘制 762.8 ms；滚动时每个暴露事件都会触发。

CSV 读取（336 ms）和统计（376 ms）不是主要矛盾，因此没有改解析器。

## 2. 改了什么

### 2.1 停顿检测：滑动排序窗口 + MAD 早退

`diagnostics._detect_local_stutters` 原来对每帧做
`metrics[left:right]` 切片、`statistics.median`、逐帧偏差排序。现在维护一个
按 `duration_ms` 有序的滑动窗口（`insort` / `bisect` 删除），帧时间递增所以
左右边界单调右移；只有当当前帧超过 `max(median * ratio, floor)` 时才计算
MAD 项（MAD 只会抬高阈值，不会降低）。

结果一致性不是靠“看起来差不多”，而是用真实 Komadori 采集与旧实现逐事件
对比：合并后 12 个事件的 `index / time_ms / duration_ms / baseline_median_ms /
threshold_ms` 完全相同。`tests/test_diagnostics_optimization.py` 保留旧算法
作为参考实现做回归。

- 5.27 s → 0.091 s（同一进程、同一份数据，约 58×）。

### 2.2 图表：像素桶峰值降采样 + 缓存

`FrameChart` 现在：

- 按控件宽度（800–3000）把时间轴分成像素桶，每桶只保留 `duration` 最大的
  那一帧，再加首尾帧；`Komadori` 在 1276 px 宽时是 1,277 个显示点。
- 几何、轴标签和显示点按 `(frames 标识, 帧数, 宽, 高)` 缓存，滚动时只重绘，
  不重算。尺寸变化才重建。
- `point_frames` 保存每个显示点对应的原始帧索引；点击命中后仍然发射原始
  索引，`show_details` 与事件联动逻辑不变。
- `set_frames` 显式失效缓存（切换链选择时）。

降采样**只作用于绘制**：`frames` 列表、`frame_stats`、停顿检测、JSON/Markdown
导出和 AI 事实仍然使用全部帧。`tests/test_ui_theme.py` 用 5,000 帧 +
单点 500 ms 尖峰断言：显示点 ≤ 1,000、首尾帧和尖峰帧都在 `point_frames` 中、
`chart.frames` 仍是 5,000。

- 单次绘制 762.8 ms → 11.5 ms（Komadori），11.1 ms → 3.4 ms（Chrome）。

### 2.3 后台加载：`analysis_loader` + `analysis_worker`

新增两个模块，把**纯 Python**工作移出 GUI 线程：

| 模块 | 职责 |
|---|---|
| `analysis_loader.load_analysis_bundle` | CSV 读取、timebase、swap-chain、统计、诊断、AI 报告摘要，返回 `PreparedAnalysis` |
| `analysis_worker.AnalysisWorker` | `QThread` 包装，`ready(generation, prepared)` / `failed(generation, message)` |

`main.show_analysis` 现在立刻返回：切到“正在加载报告…”页面并在后台启动
worker。worker 只返回数据对象，**Qt 控件仍在主线程构建**（PySide6 不允许在
子线程创建/操作控件）。

`FrameViewer` 新增 `stats` / `diagnostic_report` / `ai_report` 参数，避免
在 GUI 线程重复计算；`_refresh_diagnostics` 发现诊断已预计算时只做界面填充。
另外修正两处冗余：传入 `selection` 但已有 `frames` 时不再重算
`selection.legacy_frames()`（Komadori 约 198 ms），`main` 把
`prepared.telemetry` 传回 viewer，避免再读一次 sidecar（约 97 ms）。

### 2.4 快速切换与失败恢复

- `_analysis_generation` 单调递增；worker 结果携带 generation，只有与当前
  请求一致时才安装。A 晚到不会覆盖 B。
- 多份报告可以同时加载，每个 worker 独立；窗口关闭时
  `_stop_analysis_workers()` 请求中断并等待。
- 加载失败只弹提示并回到当前仍有效的报告；没有当前报告时回到空状态。
  `analysis_empty` 现在有引用，失败路径不会再抛 `AttributeError`。
- 报告安装成功后 AI 页面自动关联当前报告的 `report_key`；每份报告仍有独立
  会话，历史消息不重新翻译、不串台。

## 3. 改前 / 改后对照

同一批文件、同一台机器、同样的 offscreen 平台：

| 指标 | 改前 | 改后 | 说明 |
|---|---|---|---|
| `show_analysis` 返回耗时（Komadori） | ~9.4 s（同步做完所有工作） | **1.5 ms** | 点击后立即切到加载页 |
| 点击 → 报告可用（Komadori） | 9,381 ms | **3,446 ms** | 后台计算，界面可操作 |
| 点击 → 报告可用（Chrome） | 154 ms | **82 ms** | |
| 主线程最长阻塞（Komadori） | ~9.4 s | **159 ms** | 只剩主线程建 viewer + 首帧绘制 |
| 主线程最长阻塞（Chrome） | 154 ms | **46 ms** | |
| 后台 bundle（Komadori） | —（阻塞主线程） | 3,292 ms | `analysis_loader` |
| 预计算 viewer 构建（Komadori） | 8,385 ms | **50 ms** | 原来 376 ms，再去掉重复 legacy/telemetry |
| 预计算 viewer 构建（Chrome） | 142 ms | **25 ms** | |
| 图表单次绘制（Komadori） | 762.8 ms | **11.5 ms** | 1,277 显示点 |
| 图表单次绘制（Chrome） | 11.1 ms | **3.4 ms** | |
| 模拟滚动绘制（Komadori，24 个偏移） | 每个偏移一次全量折线 | **平均 3.2 ms / 最大 11.4 ms** | |
| 模拟滚动绘制（Chrome，24 个偏移） | — | 平均 2.4 ms / 最大 6.0 ms | |
| 停顿检测（Komadori） | 5.27 s | **0.091 s** | 结果逐事件一致 |

## 4. 自动化验证

- 完整测试：**717 passing**（原有 710 + `test_analysis_async.py` 4 项 +
  `test_diagnostics_optimization.py` 2 项 + 图表降采样 1 项）。
- `tests/test_analysis_async.py`（真实 `LagLens` 窗口 + 真实 worker）：
  1. 慢加载时 `show_analysis` 在 0.25 s 内返回且显示加载页；
  2. A 未完成就切 B，A 晚到后活动报告、viewer、AI `report_key` 都仍是 B；
  3. B 加载后 AI 上下文是 B；
  4. 损坏 CSV 失败后保留当前报告，随后能正常打开另一份。
- `tests/test_capture.py` 同步路径回归（`analysis_async=False`）保持通过；
  AI 自动跟随的断言改为 `test_ai_page_follows_active_report` 与
  `test_report_switcher_relinks_ai_chat_to_active_report`。

## 5. 真实文件脚本复核（offscreen，未调用 AI API）

- `Komadori` → 立刻切 `Chrome`：加载页出现，B 生效；等 A 完成后活动报告仍是
  Chrome，viewer 的 `csv_path` 仍是 Chrome，AI `report_key` 是 Chrome。
- 损坏 CSV：弹出提示，Chrome 报告保留；随后打开 Komadori（140,699 帧）成功，
  AI `report_key` 指向 Komadori。
- 加载页中英文文案都能取到。

## 6. 未验证 / 已知限制

- 以上数字来自 **offscreen Qt 平台**，滚动平滑度是用 24 个滚动偏移的绘制耗时
  近似，不是真实显示器上的视觉验收。原生 Windows GUI 的复测结果见
  `docs/ACCEPTANCE_PERF_LOADING.md`：加载页出现 2.2 ms、点击到报告 3,472 ms、
  滚动平均 4.6 ms / 最大 21 ms。
- Komadori 的主线程仍有单次阻塞：offscreen 159 ms，原生 GUI 253 ms（构建
  viewer 加首次布局/绘制）。这已从 9.4 s 降到一次可感知但不影响操作的停顿，
  但没有拆成多帧增量构建。
- 之前出现过的 `Qt6Core.dll` `0xc0000005`（offset `0xebf55`）崩溃在本轮未复现，
  也未修复，仍是开放风险。
- 降采样是“每像素桶保留峰值”，极端密集的尖峰与相邻帧在视觉上会合并；这不
  影响任何统计数据或 AI 事实，但图表不能用来数帧。
- 未做真流式输出、多 AI 服务商、真实联合 ETW 采集。
