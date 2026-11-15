"""OpenAI Responses API streaming adapter.

The adapter owns the OpenAI request shape, SSE event names and usage
placement.  Only assistant-visible ``response.output_text.delta`` text is
forwarded; reasoning summaries, the full text in
``response.output_text.done`` and protocol events are never appended.
"""

from __future__ import annotations

import ai_http
import ai_stream


API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4.1"
MODELS = (
    "gpt-4.1",
    "gpt-4.1-mini",
)


def _body(payload, model):

    items = []

    for message in payload.get("messages") or ():

        role = str(message.get("role") or "user")
        text = str(message.get("content") or "")

        if not text:

            continue

        if role not in ("system", "user", "assistant"):

            role = "user"

        items.append(
            {
                "role": role,
                "content": text,
            }
        )

    return {
        "model": model or DEFAULT_MODEL,
        "input": items,
        "stream": True,
        "store": False,
    }


def build_body(payload, model=DEFAULT_MODEL):
    """Build the exact OpenAI Responses API streaming body."""

    return _body(payload, model)


def stream_body(
    body,
    model=DEFAULT_MODEL,
    api_key=None,
    timeout=ai_http.DEFAULT_TIMEOUT,
    should_stop=None,
):
    """Send one already-built body and parse the Responses SSE stream."""

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
            "Authorization": f"Bearer {key}",
        },
    )

    completed = False
    saw_text = False
    usage = None
    model_seen = model or DEFAULT_MODEL
    finish_reason = ""

    try:

        with ai_http.open_stream(request, timeout) as response:

            for data in ai_http.iter_sse_data(response):

                if should_stop is not None and should_stop():

                    return

                if data == "[DONE]":

                    break

                event = ai_http.parse_event(data)
                event_type = str(event.get("type") or "")

                if event_type == "response.output_text.delta":

                    text = event.get("delta")

                    if isinstance(text, str) and text:

                        saw_text = True
                        yield ai_stream.TextDelta(text)

                elif event_type in (
                    "response.completed",
                    "response.incomplete",
                ):

                    completed = True
                    result = event.get("response") or {}
                    usage = _usage(result.get("usage"))
                    model_seen = str(
                        result.get("model") or model_seen
                    )

                    if event_type == "response.incomplete":

                        details = (
                            result.get("incomplete_details") or {}
                        )
                        finish_reason = str(
                            details.get("reason") or "incomplete"
                        )

                elif event_type in (
                    "response.failed",
                    "error",
                ):

                    error = (
                        event.get("error")
                        or (event.get("response") or {}).get(
                            "error"
                        )
                        or {}
                    )
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
            detail="stream ended before response.completed",
        )

    if not saw_text:

        raise ai_stream.StreamError(
            "invalid_response",
            detail="empty assistant content",
        )

    yield ai_stream.StreamCompleted(
        usage=usage,
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


def _usage(raw):

    if not isinstance(raw, dict):

        return None

    return ai_http.usage_dict(
        raw.get("input_tokens"),
        raw.get("output_tokens"),
        raw.get("total_tokens"),
    )
