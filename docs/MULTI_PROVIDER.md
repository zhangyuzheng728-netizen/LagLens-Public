# 多 AI 服务商接入（2026-11-14）

在保留 DeepSeek 的基础上接入 OpenAI、Claude、Gemini。复用上一阶段的
`ai_stream` 事件契约和同一套聊天界面；没有单独的 UI 分支、没有模拟打字、
没有用 `buffered_stream()` 冒充流式。

## 1. 分工

| 层 | 文件 | 职责 |
|---|---|---|
| 事件契约 | `ai_stream.py` | `TextDelta` / `StreamCompleted` / `StreamError` |
| 传输工具 | `ai_http.py` | JSON 编码、SSE 行解析、HTTP/超时/断流映射、token 用量归一 |
| 服务商适配器 | `deepseek_client.stream_insight` | DeepSeek SSE（`delta.content`，要求 `[DONE]` 或 `finish_reason`） |
| | `openai_client.stream_chat` | OpenAI Responses API（`response.output_text.delta`，`response.completed`，忽略 reasoning 与 `output_text.done`） |
| | `claude_client.stream_chat` | Claude Messages API（`text_delta`，`message_stop`，忽略 `thinking_delta`/tool JSON） |
| | `gemini_client.stream_chat` | Gemini `streamGenerateContent?alt=sse`（`parts[].text`，跳过 `thought`，要求 `finishReason`） |
| 注册与凭据 | `ai_providers.py` | 服务商/模型注册表、每家的 Key（凭据管理器/env/会话）、`make_streamer()`、连接测试、设置读取 |
| 会话 | `ai_chat.ChatSession` | 发送时快照 provider/model，流式写入同一条回复，停止/失败/切换 |
| 设置 | `ai_settings.AISettingsCard` | 服务商/模型选择、每家独立 Key、连接测试；切换只保存，不发请求 |

统一契约不变：

```python
stream(payload, api_key=..., timeout=..., should_stop=...)
    -> TextDelta | StreamCompleted      # 失败抛 StreamError
```

适配器负责各自协议；聊天层只认这三种事件。

## 2. 服务商与默认模型

| 服务商 | 默认模型 | 可选预设 | 凭据目标（Windows Credential Manager） | 环境变量（后备） |
|---|---|---|---|---|
| DeepSeek（默认） | `deepseek-flash` | `deepseek-flash` | `LagLens/DeepSeekApiKey`（与旧版相同） | `DEEPSEEK_API_KEY` |
| OpenAI | `gpt-4.1` | `gpt-4.1`, `gpt-4.1-mini` | `LagLens/OpenAIApiKey` | `OPENAI_API_KEY` |
| Claude | `claude-sonnet-4-5` | `claude-sonnet-4-5`, `claude-haiku-4-5` | `LagLens/ClaudeApiKey` | `ANTHROPIC_API_KEY` |
| Gemini | `gemini-2.5-flash` | `gemini-2.5-flash`, `gemini-2.5-pro` | `LagLens/GeminiApiKey` | `GEMINI_API_KEY` |

模型下拉框可编辑，预设只是常用值。DeepSeek 的凭据目标保持
`LagLens/DeepSeekApiKey`，已有用户不需要迁移或重新填 Key。

## 3. 切换行为

- 设置页选择服务商后立即保存 `ai/provider`；模型保存到 `ai/model/<provider>`，
  再次切回时恢复上次为该服务商选的模型。
- 切换只更新设置与 AI 页面顶部的「AI 服务：服务商 · 模型」，**不发任何请求**；
  只有点「测试连接」或发送消息才会联网。
- 发送时解析一次 `(provider, model, key)` 并传给会话；请求期间修改设置不会
  影响进行中的请求（消息里记录实际使用的 `provider`/`model`）。
- 缺少 Key：不发送，状态提示「尚未配置 X 的 API Key…」，并显示「前往 AI 设置」。
- 鉴权失败：状态显示服务商无关的鉴权错误 + 「请在设置 → AI 服务中检查 X 的
  Key」，不偷偷切换服务商、不自动重试；用户可手动重试或更换 Key。
- 自由聊天流式；`LAGLENS_AI_MODE=structured` 的严格校验仍只用于 DeepSeek
  （其他服务商按自由文本流式处理），保留原有校验行为。

## 4. 自动化验证（744 tests）

新增 `tests/test_ai_providers.py`（17 项）：

- 四家适配器：分段 SSE 的正文拼接、推理字段过滤、用量归一、请求 URL/协议
  字段、缺少终止事件 → `connection`、HTTP 401 → `auth`；
- 凭据：DeepSeek 继续走原有函数；其余三家写入各自的 Credential Manager 目标；
  默认仍为 DeepSeek + `deepseek-flash`；设置读写与恢复；
- 设置页：切换服务商保存 provider/model 且 `urlopen` 未被调用、恢复上次模型、
  Key 保存到当前服务商的目标、状态跟随当前服务商；
- 共用界面（对四家逐一执行）：第一段在完成前可见、完成后拼接完整、消息记录
  provider/model；鉴权失败只请求一次并提示设置；中途断流保留片段、标记未完成、
  手动重试成功；停止后用另一家继续发送；进行中请求保持原服务商；注入的测试
  客户端优先于网络（不会被真实适配器覆盖）。

原有 DeepSeek 流式测试、自由聊天、按报告隔离、结构化诊断测试全部保留并通过。

## 5. 真实 Windows GUI 验收（同一份报告、同一条问题）

环境：原生 `windows` Qt 平台，报告 `douyin.exe_20261114_152446_066430.csv`
（1,254 帧）。不输出 Key、问题原文或回答正文。

| 服务商 | 模型 | 自动化 | 真实 GUI | 首段可见 | 完成 | 备注 |
|---|---|---|---|---|---|---|
| DeepSeek | `deepseek-flash` | 通过 | **通过**（已保存 Key） | **0.781 s**（正文 0.672 s） | **0.859 s** | 8 个增量、有 usage、主线程最大间隔 23 ms |
| OpenAI | `gpt-4.1` | 通过 | **调用被拒：HTTP 401** | — | — | 环境中的 `OPENAI_API_KEY` 无效/过期；已按鉴权失败处理，无重试、不切换 |
| Claude | `claude-sonnet-4-5` | 通过 | **未验收**（无 Key）；缺 Key 路径已实测 | — | — | 发送被拦截，提示前往设置，未联网 |
| Gemini | `gemini-2.5-flash` | 通过 | **未验收**（无 Key）；缺 Key 路径已实测 | — | — | 同上 |

另在真实 GUI 中验证：设置页从 DeepSeek 切到 OpenAI 后，AI 页面顶部立即显示
「AI 服务：OpenAI · gpt-4.1」，`urlopen` 未被调用；切回 DeepSeek 后模型恢复
`deepseek-flash`，原保存的 Key 仍为 `saved`（无迁移）。

OpenAI 的真实 SSE 正文没有完成验证：401 发生在建立流之前。适配器的流式解析
由自动化分段测试覆盖，不能把 401 当作流式验收通过。

## 6. 以后新增一家服务商

1. 新建 `<provider>_client.py`，实现
   `stream_chat(payload, model, api_key, timeout, should_stop)`，用
   `ai_http` 发真实流式请求，只产出 `ai_stream.TextDelta` / `StreamCompleted`，
   失败抛 `StreamError`（含 `auth`/`timeout`/`connection` 等码）。
2. 在 `ai_providers.PROVIDER_LIST` 增加 `Provider`（id、显示名、模型、默认模型、
   凭据目标、环境变量、协议余量）。
3. 在 `locales/*.json` 不需要为服务商新增文案（错误与设置文案是通用的）。
4. 在 `tests/test_ai_providers.py` 的 `PROVIDER_CASES` 增加该家的分段协议用例，
   跑「第一段在完成前可见、断流不算成功、401 映射、设置持久化」。
5. 用真实 Key 在原生 GUI 发一条请求，记录首段与总耗时；没有真实调用就标注
   「自动化通过，真实调用未验收」。

## 7. 限制

- 只对 DeepSeek 完成了真实流式验收；OpenAI 真实调用返回 401；Claude/Gemini
  没有可用 Key。
- 停止仍要等下一个数据块或 socket 超时才能真正关闭连接（界面立即标记已停止）。
- 4 KiB 对话内容预算继续生效；非 DeepSeek 额外预留 256 字节给协议包装字段。
- Claude 的 `max_tokens` 固定 1024；Gemini/OpenAI 未暴露生成参数设置。
- 严格结构化诊断（`LAGLENS_AI_MODE=structured`）仍只绑定 DeepSeek。
