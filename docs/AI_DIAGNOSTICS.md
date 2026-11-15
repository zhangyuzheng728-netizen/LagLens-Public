# AI diagnostic log

Status: implemented, automated tests passing. The log is local and is not
uploaded.

## Purpose

A failed structured answer used to leave only a short validation string. The
log records enough context to tell a model/format problem apart from a fact
reference, numeric, scenario or API error, without storing the chat or the
raw model output.

## Location

`%LOCALAPPDATA%\LagLens\logs\ai_diagnostics.jsonl`

`LAGLENS_DATA_DIR` changes the base directory through the normal settings
path resolution. The file is JSON Lines: one JSON object per line.

## Fields

Common fields:

- `ts`: UTC timestamp;
- `event`: `request`, `response`, `local_repair`, `repair_request`,
  `repair_response`, `final` or `api_error`;
- `model`: for example `deepseek-flash`;
- `report_id`: first 12 hex characters of the report key hash;
- `file`: capture basename only, never the full path;
- `session_id`: capture session ID or `unknown`;
- `scenario`, `scenario_source`, `quality`;
- `mode`: `freeform` (default) or `structured`;
- `language`: the UI/question language used for the prompt;
- `message_count`: number of messages, not their text.

Validation fields:

- `parse_ok`: JSON parsing result;
- `local_repairs`: count of fact-ID syntax repairs applied before validation;
- `validation`: list of safe entries such as
  `{"type":"numeric","fact_id":"longest_display_stall","number":"11","unit":"秒"}`;
- types include `numeric`, `fact_reference`, `json`, `conclusion`, `network`,
  `hardware`, `scenario`, `safety`, `format` and `other`;
- `repair_attempted`, `repair_ok`;
- `final_source`: `ai`, `fallback` or `error`;
- `elapsed_ms`;
- `usage`: `prompt_tokens`, `completion_tokens`, `total_tokens` when the
  provider returns them.

API errors record `error_code` and `error_status`; the provider's response
body and the exception detail are not logged.

## Privacy and safety

- API keys, Authorization headers and environment values are never passed to
  the logger. The logger also drops keys named `api_key`, `authorization`,
  `headers`, `env`, `content`, `messages`, `question`, `answer`, `response`,
  `raw`, `detail`, `path`, `file_path` and `report_path`.
- Full chat messages and raw model responses are not stored.
- The capture path is reduced to a basename plus a short hash.
- A log write failure returns `False`; it never raises into the AI request.
- Rotation: 5 MiB active file plus one 5 MiB backup (about 10 MiB total).
  Backups older than 7 days are removed on the next write.

## Enabling and testing

The application creates the log through `ai_diagnostics.get_log()` in
`main.py`. Tests use a temporary path or a recording double, so the normal
test suite does not write into the user's log.

## Limits

- The log is diagnostic, not an audit trail or a full transcript.
- It does not include the prompt or the model's answer; reproducing a
  specific answer still requires the capture and the question.
- The provider's token usage is logged only when the API returns it.
