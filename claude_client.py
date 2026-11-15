"""Claude Messages API streaming adapter.

The adapter owns the Anthropic request shape (system prompt separated,
required ``max_tokens``), SSE event names and usage placement.  Only
``text_delta`` content is forwarded; thinking deltas and tool-input JSON
are ignored.
"""

from __future__ import annotations

import ai_http
import ai_stream


API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"
MODELS = (
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
)
MAX_TOKENS = 1024


def _body(payload, model):

    system_parts = []
    messages = []

    for message in payload.get("messages") or ():

        role = str(message.get("role") or "user")
        text = str(message.get("content") or "")

        if not text:

            continue

        if role == "system":

            system_parts.append(text)
            continue

        role = "assistant" if role == "assistant" else "user"

        if messages and messages[-1]["role"] == role:

            messages[-1]["content"] += "\n\n" + text

        else:

            messages.append(
                {
                    "role": role,
                    "content": text,
                }
            )

    body = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": messages,
        "stream": True,
    }

    if system_parts:

        body["system"] = "\n\n".join(system_parts)

    return body


def build_body(payload, model=DEFAULT_MODEL):
    """Build the exact Claude Messages API streaming body."""

    return _body(payload, model)


def stream_body(
    body,
    model=DEFAULT_MODEL,
    api_key=None,
    timeout=ai_http.DEFAULT_TIMEOUT,
    should_stop=None,
):
    """Send one already-built body and parse the Messages SSE stream."""

    key = (api_key or "").strip()

    if not key:

        raise ai_stream.StreamError("missing_key")

    raw_body = (
        bytes(body)
        if isinstance(body, (bytes, bytearray))
        else ai_http.encode_json(body)
    )
    ai_http.ensure_body_size(raw_body)

    request = ai_http.build_request(
        API_URL,
        raw_body,
        {
            "x-api-key": key,
            "anthropic-version": API_VERSION,
        },
    )

    completed = False
    saw_text = False
    model_seen = model or DEFAULT_MODEL
    input_tokens = None
    output_tokens = None
    finish_reason = ""

    try:

        with ai_http.open_stream(request, timeout) as response:

            for data in ai_http.iter_sse_data(response):

                if should_stop is not None and should_stop():

                    return

                event = ai_http.parse_event(data)
                event_type = str(event.get("type") or "")

                if event_type == "message_start":

                    message = event.get("message") or {}
                    model_seen = str(
                        message.get("model") or model_seen
                    )
                    usage = message.get("usage") or {}
                    input_tokens = usage.get(
                        "input_tokens",
                        input_tokens,
                    )

                elif event_type == "content_block_delta":

                    delta = event.get("delta") or {}

                    if delta.get("type") != "text_delta":

                        continue

                    text = delta.get("text")

                    if isinstance(text, str) and text:

                        saw_text = True
                        yield ai_stream.TextDelta(text)

                elif event_type == "message_delta":

                    delta = event.get("delta") or {}

                    if delta.get("stop_reason"):

                        finish_reason = str(
                            delta["stop_reason"]
                        )

                    usage = event.get("usage") or {}
                    output_tokens = usage.get(
                        "output_tokens",
                        output_tokens,
                    )

                elif event_type == "message_stop":

                    completed = True

                elif event_type == "error":

                    error = event.get("error") or {}
                    raise ai_stream.StreamError(
                        "server",
                        detail=str(
                            error.get("message")
                            if isinstance(error, dict)
                            else error
                        ),
                    )

    except ai_stream.StreamError:

        raise

    except Exception as error:

        raise ai_http.transport_error(error) from error

    if should_stop is not None and should_stop():

        return

    if not completed:

        raise ai_stream.StreamError(
            "connection",
            detail="stream ended before message_stop",
        )

    if not saw_text:

        raise ai_stream.StreamError(
            "invalid_response",
            detail="empty assistant content",
        )

    yield ai_stream.StreamCompleted(
        usage=ai_http.usage_dict(
            input_tokens,
            output_tokens,
            (
                input_tokens + output_tokens
                if isinstance(input_tokens, int)
                and isinstance(output_tokens, int)
                else None
            ),
        ),
        model=model_seen,
        finish_reason=finish_reason or "stop",
    )


def stream_chat(
    payload,
    model=DEFAULT_MODEL,
    api_key=None,
    timeout=ai_http.DEFAULT_TIMEOUT,
    should_stop=None,
):
    """Backward-compatible wrapper: build the body, then stream it."""

    yield from stream_body(
        build_body(payload, model),
        model=model,
        api_key=api_key,
        timeout=timeout,
        should_stop=should_stop,
    )
