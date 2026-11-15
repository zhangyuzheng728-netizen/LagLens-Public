# AI 助手通用流式输出（2026-11-14）

本阶段把 AI 助手从「等完整响应」改成**真实流式**：服务商适配器发起真实
流式请求并解析自己的协议，聊天层只消费统一的正文片段、完成状态、用量和
错误。界面代码不认识 DeepSeek 的字段。自由聊天、提示词、按报告隔离的会话
和单窗口导航都保留；没有新增服务商。

## 1. 分工

| 层 | 文件 | 负责 |
|---|---|---|
| 事件契约 | `ai_stream.py` | `TextDelta`、`StreamCompleted`、`StreamError`、`buffered_stream`、`PROTOCOL_MARGIN_BYTES` |
| 服务商适配器 | `deepseek_client.stream_insight` | 真实 SSE 请求、`data:` 行解析、`delta.content`、`usage`、HTTP/超时/断流映射；忽略 `reasoning_content` |
| 会话/状态 | `ai_chat.ChatSession` | 在后台线程消费事件、增量写入同一条回复、停止、失败与不完整标记 |
| 界面 | `ai_chat.ChatPanel` / `AIChatPage` | 显示片段、停止按钮、状态文案；**不解析任何服务商字段** |

适配器就是一个可调用对象：

```python
stream(payload, api_key=..., timeout=..., should_stop=...)
    -> iterator of ai_stream.TextDelta | ai_stream.StreamCompleted
```

失败时抛 `StreamError(code, status, detail)`（DeepSeek 适配器抛
`DeepSeekError`，聊天层两种都识别）。新增服务商只需要写一个满足该契约的
适配器并注入 `AIChatPage(streamer=...)`，聊天界面无需修改。

## 2. 行为

- **先显示后完成**：第一段正文到达时创建一条 `streaming=True` 的助手消息，
  之后追加到同一条；`StreamCompleted` 才把 `complete` 置为 `True`。
- **不做假打字**：没有完整响应后的逐字回放。片段就是网络收到的片段。
- **不显示推理**：只读取正文增量，`reasoning_content` 等字段被忽略。
- **4 KiB 预算**：流式请求会在共享预算上留 64 字节给 `stream` /
  `stream_options` 协议字段，请求体仍不超过 4096 字节。
- **校验流程保留**：`LAGLENS_AI_MODE=structured` 的严格诊断仍走完整响应 +
  本地校验后才显示，不提前展示未验证内容。默认自由聊天走流式。

## 3. 停止、断流与切换

- **停止生成**：状态栏出现「停止生成」。停止会立即作废当前 `request_id`，
  已显示内容保留并标记 `complete=False, interrupted="stopped"`，UI 显示
  「未完成」和「已停止，这条回复不完整。」。迟到的片段被 `request_id`
  守卫丢弃；不需要等网络返回就能继续输入。
- **断网/超时/HTTP 错误**：已显示部分保留并标记 `interrupted="error"`，
  `last_error_code` 记录原因（`connection`、`timeout`、`auth`…），
  不自动重发；「重试」按钮可用，由用户手动触发。
- **历史隔离**：`_history_snapshot()` 过滤 `complete=False` 的消息，未完成
  的回复不会被当作完整回答发给下一轮；重试时的偏移也不会错位。
- **报告隔离**：每个 `report_key` 一个 `ChatSession`；切换报告会断开旧会话
  的界面信号。A 的迟到片段只写 A 的会话，不会进入 B 的对话或覆盖 B 的状态，
  切回 A 时仍能看到 A 的完整/部分回复。
- **主线程**：网络读取在 `laglens-ai-chat` 线程；界面用 40 ms 合并渲染，
  流式期间仍可滚动、切换页面和报告。

## 4. 自动化验证

`tests/test_ai_stream.py`（10 项）：

1. SSE 解析：多段正文拼接正确、`reasoning_content` 不出现、`usage` 保留、
   请求体含 `stream`/`stream_options`；
2. HTTP 401 → `auth`；流中途 `IncompleteRead` → `connection`；
   `should_stop` 提前结束且不再产出完成事件；
3. 测试适配器经 `AIChatPage`/`ChatPanel` 同一链路：第一段在 `pending=True`
   时已出现在 transcript，完成前不含后续片段；
4. 手动停止：保留片段、标记未完成、迟到片段被忽略；下一条消息可正常发送；
   未完成回复不出现在下一次请求的历史里；
5. 中途断流：保留片段、`connection` 错误、只请求一次（不自动重发）、
   手动重试成功；
6. 生成中 A → B：B 的 transcript 不含 A 的文本，切回 A 可见；
7. 严格结构化模式仍在完成前不显示任何内容。

完整测试：**727 passing**（原有 717 + 10）。

## 5. 真实 DeepSeek 验收（原生 Windows GUI）

环境：本机 `windows` Qt 平台，真实报告 `douyin.exe_20261114_152446_066430.csv`
（1,254 帧），已保存的 DeepSeek Key（不输出 Key），问题为一条三句话的
报告总结请求。测三次，最后一次（最终代码）：

| 指标 | 结果 |
|---|---|
| 发送 → 会话里出现第一段正文 | **0.688 s**（另两次 0.844 s / 1.282 s） |
| 发送 → 界面可见第一段 | **0.829 s**（含 40 ms 合并渲染） |
| 发送 → 完成 | **1.531 s**（另两次 1.985 s / 2.219 s） |
| 正文增量次数 | 37 次（长度 2 → 199 字符，完成前持续增长） |
| 状态文案 | 生成中显示「正在生成…」+「停止生成」 |
| 主线程事件循环最长间隔 | 80 ms（另两次 47 / 45 ms），仍可滚动/切换 |
| 用量 | 有 `usage` |
| 诊断日志 | `first_delta=671 ms`，`elapsed_ms=1531` |

截图（真实数据，静态捕获）：

- `captures/ai_stream_partial_zh.png` — 生成中：部分正文 + 正在生成 + 停止生成
- `captures/ai_stream_done_zh.png` — 完成后：完整回答 + 「可以继续追问。」

没有输出 Key、问题原文或完整回答内容；只记录长度、耗时和状态。

## 6. 未验证 / 限制

- 停止在网络阻塞期间要等到下一个数据块（或 socket 超时）才真正关闭连接；
  正常情况下是几十毫秒。界面状态会立即变成「已停止」。
- 首个数据块可能一次包含较多正文（本例 113 字符），这是服务端分批方式，
  不是客户端伪造的逐字输出。
- 只实测了 DeepSeek。OpenAI / Claude / Gemini 尚未接入；接入时必须用各自
  的真实流式协议并重复「第一段在完成前可见」的验收，只接通普通请求不算
  完成。
- 本轮未改打包行为；打包版在提交后构建，`BUILD_INFO.txt` 记录本提交。
