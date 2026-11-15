# AI 请求体 4 KiB 预算修复（LagLens 2.0，2026-11-15）

修复旧构建在发请求前把正常请求误判为超限的问题。4 KiB 仍是 LagLens 自己的
硬上限；本修复按**适配器真正发送的 UTF-8 请求体**计量，超限时先在本地按优先级
压缩，合规后只发送一次。

## 1. 旧问题的数据

- 运行中的旧包是 `6cc8d1a`（`D:\LagLensData\multi_provider`）。
- 两分钟抖音记录 `douyin.exe_20261115_162238_073712.csv`（5,620 帧）。
- 旧代码固定预留 64 B，`ChatSession` 只允许 4,032 B；该记录的聊天 payload 是
  **4,034 B**，差 2 B 被本地 `PromptTooLarge` 拒绝。
- 实际 DeepSeek 流式 body（payload + `stream` + `stream_options`）只有
  **4,088 B**，本应可发。
- `5c5c23f` 加入事件总数等事实后，payload 变为 4,086 B，流式 body 约 4,140 B；
  仅改预留仍会超限，必须压缩摘要。

## 2. 现在的计量与发送

- 每个适配器提供 `build_body()`：DeepSeek、OpenAI、Claude、Gemini 各自的
  模型、消息和流式字段都算进去。
- `ai_providers.request_body(provider, model, payload)` 用
  `ai_http.encode_json` 产生请求字节；`stream_body(bytes)` 直接发送这份字节，
  **测量和发送是同一份序列化结果**。
- `ai_chat.ChatSession` 在真实流式路径把 `body_fn` 传给
  `ai_insight.build_chat_payload`，循环按 body 字节数判断；合规后拿到
  `(payload, body)`，只调用一次发送。
- 每个适配器的 `stream_body` 仍会再检查一次 ≤4,096 B，超限请求不会上线。
- `ai_insight.MAX_REQUEST_BYTES` 保持 4,096，没有调大。

## 3. 摘要压缩优先级

摘要大小不随帧数或异常次数线性增长：全程统计在本地计算，事实表是固定字段；
事件明细最多 3 个代表样本（带距采集开始的时间）。

压缩顺序（每步重算 body 字节数）：

1. 旧对话轮次；
2. 可选诊断细节与代表性事件窗口；
3. 技能卡；
4. compact 文本（去掉重复标题、显示行、硬件行等）；
5. compact=3（去掉目标行、应用场景行）；
6. 逐组删除次要事实：
   - 网络响应数/样本数；
   - 重复头部/低价值事实；
   - 每帧 CPU/GPU 忙碌时间；
   - CPU/GPU 利用率、进程 CPU、目标 FPS。

**永不删除**：总帧数 `displayed_frames`、平均 FPS、P95/P99 帧时间、
异常长帧总数、≥1 秒次数、最长停顿及时间、网络超时次数/超时率、
`telemetry_alignment`。缺数据写 `unknown`，不写 0。

## 4. 失败原因与诊断日志

- 用户问题本身过长（最小摘要可放下）：`prompt_too_large`，提示缩短问题。
- 即使最小摘要也放不下：`summary_too_large`，提示这是本地发送限制，
  **不是录制时长的问题**，不要求缩短录制。
- `ai_diagnostics.jsonl` 的 `api_error` 只记录：
  `error_code`、`actual_bytes`、`limit`、`failure_stage`（`question`/`summary`）、
  `elapsed_ms`；不记录 Key、请求正文或完整报告。
- 成功请求的 `request` 事件新增 `request_bytes` 与 `limit`，便于验收。

## 5. 自动化验证

`tests/test_ai_request_budget.py`（11 项）：

- 4,096 B body 可发；4,097 B 在无法再压缩时抛 `PromptTooLarge`，且理由为
  `summary`；不会调用传输层。
- 中文 UTF-8 按字节计量（字节数大于字符数）。
- 四家适配器的 body 包含各自协议字段（DeepSeek 的 `stream_options`、
  OpenAI 的 `input`、Claude 的 `max_tokens`、Gemini 的 `contents`/
  `systemInstruction`）；4,097 B 在四家都不会进入 `urlopen`，4,096 B 会进入。
- 抖音形状报告（5,620 帧、2 个事件）在四家都 ≤4,096 B，关键事实全部保留。
- 400 个事件与 2 个事件的摘要大小差 <200 B，样本数仍受限。
- 最小摘要的关键事实不会被压缩删除。
- 问题过长与摘要过大的 `reason` 区分；诊断日志只含字节数/上限/阶段，
  不含 Key 或问题正文。

`tests/verify_two_hour_report.py`（本地脚本，非单元测试）：

- 432,000 帧（2 小时 60 FPS），大量异常，11 次 ≥1 秒，最长 4.2 秒发生在
  6022.957 秒（后半段）。
- 实际 `diagnostics.analyze` → 12 个事件，7 个在后半段。
- 实际 Markdown 导出（6,267 B）包含 6022.96 秒事件。
- 摘要关键统计：432,000 帧、P95/P99 16.67 ms、12 个事件、11 次 ≥1 秒、
  最长 4.2 秒、后半段事件、遥测未对齐。
- 最终 DeepSeek body **4,001 B**，代表样本 3 个且包含后半段；
  报告/导出与 AI 请求分别通过。

完整测试：**762 passing**。

## 6. 真机与打包验收

- 从干净提交构建 `LagLens-v2.0.0-win64.zip`；`BUILD_INFO.txt` 必须等于该提交。
- 用新 ZIP 内 EXE（不是旧快捷方式）打开现有 5,620 帧抖音记录，跑一次真实
  DeepSeek「全面分析」：确认流式完成、日志 `request_bytes` ≤4,096、回复中的
  「2 次异常/1 次 ≥1 秒」等数字与报告一致。
- 两小时模拟记录只证明本地报告/导出/请求预算；**不等于真机连续采集通过**。
- 2–3 分钟真实游戏新采集与导出验收需要用户操作，单独记录。
