"""Provider-neutral streaming contract for the AI assistant.

A streaming adapter is a plain callable::

    stream(payload, api_key=..., timeout=..., should_stop=...)
        -> iterator of TextDelta | StreamCompleted

The adapter owns everything provider-specific: the real HTTP streaming
request, the wire format (SSE or otherwise), event names, reasoning /
thinking fields and usage placement.  The chat layer only consumes text
deltas and a completion marker, so adding a provider does not change the
Qt chat code.

Failure handling: adapters raise :class:`StreamError` (or their own
provider error type) and the chat session converts it into a visible
error.  Transport errors must not be swallowed silently.
"""

from __future__ import annotations


class TextDelta:
    """One piece of assistant-visible text.

    The adapter must never put reasoning, tool protocol or other
    non-answer text into ``text``.
    """

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = str(text or "")


class StreamCompleted:
    """The stream ended normally."""

    __slots__ = ("usage", "model", "finish_reason")

    def __init__(self, usage=None, model="", finish_reason=""):
        self.usage = usage
        self.model = str(model or "")
        self.finish_reason = str(finish_reason or "")


class StreamError(Exception):
    """A provider-neutral stream failure."""

    def __init__(self, code, status=0, detail=""):
        super().__init__(detail or code)
        self.code = str(code or "unknown")
        self.status = int(status or 0)
        self.detail = str(detail or "")


def buffered_stream(text, usage=None, model="", finish_reason="stop"):
    """Adapt a complete buffered answer to the streaming contract.

    Used for non-streaming clients and for the validated structured
    diagnosis path, which needs the whole answer before showing it.
    """

    text = str(text or "")

    if text:
        yield TextDelta(text)

    yield StreamCompleted(
        usage=usage,
        model=model,
        finish_reason=finish_reason,
    )


def text_of(events):
    """Collect the assistant text from an event iterator (tests, tools)."""

    parts = []

    for event in events:

        if isinstance(event, TextDelta):
            parts.append(event.text)

    return "".join(parts)
