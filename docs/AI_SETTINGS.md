# AI Service Settings

## UI

**Settings → AI service** shows:

- provider **DeepSeek**;
- model `deepseek-flash`;
- password-style API key input;
- **Save key** / **Change key**, **Remove key**, **Test connection**;
- a status line that never echoes the complete key.

No custom API URL or other provider is exposed. Opening the page and
saving a key do not send any request.

## Credential storage

The key is stored in Windows Credential Manager under the current user:

```text
LagLens/DeepSeekApiKey
```

`credential_store.py` uses `CredWriteW`, `CredReadW`, `CredDeleteW` and
`CredFree`. The key is never written to the INI, logs, reports, exports
or the package. A save failure is reported in the settings card.

## Key precedence

`deepseek_client.get_api_key()` uses:

1. saved Windows Credential Manager key;
2. `DEEPSEEK_API_KEY` environment variable (development/tests);
3. an in-memory key typed into a session prompt.

After removing the saved key, if the environment variable is present,
the settings page explicitly says:

> 未保存到本机；仍在使用环境变量中的 Key

Removing the local credential does not revoke the DeepSeek platform key.

## Connection test

**Test connection** runs in the background only after a click. It sends a
minimal request with one short user message and `max_tokens: 8`; it does
not include chat history, a report or capture data. It distinguishes:

- success;
- invalid key;
- insufficient balance;
- rate limit;
- connection/timeout;
- other HTTP/service errors.

## AI assistant when no key exists

The AI assistant shows **前往 AI 设置** when no saved, environment or
session key is available. After saving, the next send immediately uses
the new key without restarting LagLens.

## Tests

`tests/test_ai_settings.py` uses mocked credential operations and mocked
connection tests. It covers no request on open, save success/failure,
environment fallback, removal, and connection success/auth failure.
`tests/test_deepseek_client.py` covers saved > environment > session
precedence and the minimal connection payload. No real API call is made.
