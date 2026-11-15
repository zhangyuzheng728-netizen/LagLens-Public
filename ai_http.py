"""Small shared HTTP/SSE helpers for the provider adapters.

Only standard-library code.  Providers differ in their JSON bodies and
event names, but they share the transport concerns: request encoding,
SSE line framing, HTTP status mapping and the requirement that a stream
which ends before its terminal event is a failure.
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.request

import ai_stream


DEFAULT_TIMEOUT = 30.0
MAX_REQUEST_BYTES = 4096


def encode_json(payload):

    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def ensure_body_size(raw_body, limit=MAX_REQUEST_BYTES):
    """Reject an oversized body before any network call."""

    size = len(raw_body)

    if size > limit:

        raise ai_stream.StreamError(
            "too_large",
            detail=f"{size} bytes, limit {limit}",
        )

    return raw_body


def build_request(url, body, headers, accept="text/event-stream"):

    merged = {
        "Content-Type": "application/json",
        "Accept": accept,
    }
    merged.update(headers or {})

    return urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=merged,
    )


def open_stream(request, timeout):

    return urllib.request.urlopen(
        request,
        timeout=float(timeout or DEFAULT_TIMEOUT),
    )


def iter_sse_data(response):
    """Yield the ``data:`` payload of each SSE line."""

    for raw_line in response:

        line = raw_line.decode(
            "utf-8",
            "replace",
        ).strip()

        if not line or line.startswith(":"):

            continue

        if not line.startswith("data:"):

            continue

        data = line[5:].strip()

        if data:

            yield data


def http_error(error):
    """Map an HTTPError to a provider-neutral StreamError."""

    status = int(getattr(error, "code", 0) or 0)

    if status in (401, 403):

        code = "auth"

    elif status == 402:

        code = "balance"

    elif status == 413:

        code = "too_large"

    elif status == 429:

        code = "rate_limit"

    elif status >= 500:

        code = "server"

    elif status >= 400:

        code = "invalid_request"

    else:

        code = "http"

    detail = ""

    try:

        body = error.read()

        if body:

            detail = body.decode(
                "utf-8",
                "replace",
            )[:300]

    except Exception:

        detail = ""

    return ai_stream.StreamError(
        code,
        status=status,
        detail=detail,
    )


def transport_error(error):
    """Map a non-HTTP transport exception to a StreamError."""

    if isinstance(error, urllib.error.HTTPError):

        return http_error(error)

    if isinstance(
        error,
        (TimeoutError, socket.timeout),
    ):

        return ai_stream.StreamError(
            "timeout",
            detail=str(error),
        )

    if isinstance(error, urllib.error.URLError):

        reason = getattr(error, "reason", None)

        code = (
            "timeout"
            if isinstance(
                reason,
                (TimeoutError, socket.timeout),
            )
            else "connection"
        )

        return ai_stream.StreamError(
            code,
            detail=str(reason or error),
        )

    if isinstance(
        error,
        (http.client.HTTPException, OSError),
    ):

        return ai_stream.StreamError(
            "connection",
            detail=str(error),
        )

    return ai_stream.StreamError(
        "unknown",
        detail=str(error),
    )


def parse_event(data):
    """Decode one SSE data payload; a malformed event is an error."""

    try:

        event = json.loads(data)

    except json.JSONDecodeError as error:

        raise ai_stream.StreamError(
            "invalid_response",
            detail=str(error),
        ) from error

    if not isinstance(event, dict):

        return {}

    return event


def usage_dict(prompt=None, completion=None, total=None):
    """Normalize token usage to the shared prompt/completion/total shape."""

    usage = {}

    if isinstance(prompt, int) and prompt >= 0:

        usage["prompt_tokens"] = prompt

    if isinstance(completion, int) and completion >= 0:

        usage["completion_tokens"] = completion

    if isinstance(total, int) and total >= 0:

        usage["total_tokens"] = total

    elif usage:

        usage["total_tokens"] = sum(usage.values())

    return usage or None
