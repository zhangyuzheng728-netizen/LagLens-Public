"""AI provider registry, per-provider credentials and selection helpers.

Each provider supplies a real streaming adapter with the same contract as
:mod:`ai_stream`.  The chat UI resolves the provider once when a message
is sent, so changing the selection never affects an in-flight request.

Credentials are stored per provider in Windows Credential Manager.  The
DeepSeek credential target is unchanged from earlier versions, so
existing users keep their saved key without any migration.
"""

from __future__ import annotations

import os

from dataclasses import dataclass

import ai_http
import ai_stream
import claude_client
import credential_store
import deepseek_client
import gemini_client
import openai_client


DEFAULT_PROVIDER = "deepseek"

_SESSION_KEYS = {}


@dataclass(frozen=True)
class Provider:

    id: str
    label: str
    models: tuple
    default_model: str
    stream: object
    build_body: object
    stream_body: object
    env_var: str
    credential_target: str

    @property
    def selected_model(self):

        return self.default_model


def _deepseek_stream_body(
    body,
    api_key=None,
    timeout=None,
    should_stop=None,
):

    kwargs = {"should_stop": should_stop}

    if api_key is not None:

        kwargs["api_key"] = api_key

    if timeout is not None:

        kwargs["timeout"] = timeout

    try:

        yield from deepseek_client.stream_body(body, **kwargs)

    except deepseek_client.DeepSeekError as error:

        raise ai_stream.StreamError(
            error.code,
            status=error.status,
            detail=error.detail,
        ) from error


def _deepseek_stream(
    payload,
    model=None,
    api_key=None,
    timeout=None,
    should_stop=None,
):

    yield from _deepseek_stream_body(
        deepseek_client.build_body(payload, model),
        api_key=api_key,
        timeout=timeout,
        should_stop=should_stop,
    )


PROVIDER_LIST = (
    Provider(
        id="deepseek",
        label="DeepSeek",
        models=("deepseek-flash",),
        default_model="deepseek-flash",
        stream=_deepseek_stream,
        build_body=deepseek_client.build_body,
        stream_body=_deepseek_stream_body,
        env_var=deepseek_client.API_KEY_ENV,
        credential_target=credential_store.CREDENTIAL_TARGET,
    ),
    Provider(
        id="openai",
        label="OpenAI",
        models=openai_client.MODELS,
        default_model=openai_client.DEFAULT_MODEL,
        stream=openai_client.stream_chat,
        build_body=openai_client.build_body,
        stream_body=openai_client.stream_body,
        env_var="OPENAI_API_KEY",
        credential_target="LagLens/OpenAIApiKey",
    ),
    Provider(
        id="claude",
        label="Claude",
        models=claude_client.MODELS,
        default_model=claude_client.DEFAULT_MODEL,
        stream=claude_client.stream_chat,
        build_body=claude_client.build_body,
        stream_body=claude_client.stream_body,
        env_var="ANTHROPIC_API_KEY",
        credential_target="LagLens/ClaudeApiKey",
    ),
    Provider(
        id="gemini",
        label="Gemini",
        models=gemini_client.MODELS,
        default_model=gemini_client.DEFAULT_MODEL,
        stream=gemini_client.stream_chat,
        build_body=gemini_client.build_body,
        stream_body=gemini_client.stream_body,
        env_var="GEMINI_API_KEY",
        credential_target="LagLens/GeminiApiKey",
    ),
)

PROVIDERS = {provider.id: provider for provider in PROVIDER_LIST}


def get(provider_id=None):

    return (
        PROVIDERS.get(str(provider_id or ""))
        or PROVIDERS[DEFAULT_PROVIDER]
    )


def label(provider_id=None):

    return get(provider_id).label


def ids():

    return tuple(provider.id for provider in PROVIDER_LIST)


def _saved_key(provider):

    try:

        value = credential_store.read_secret(
            provider.credential_target
        )

    except credential_store.CredentialError:

        return None

    return (value or "").strip() or None


def api_key_source(provider_id=None):

    provider = get(provider_id)

    if provider.id == "deepseek":

        return deepseek_client.get_api_key_source()

    if _saved_key(provider):

        return "saved"

    if (os.environ.get(provider.env_var) or "").strip():

        return "environment"

    if _SESSION_KEYS.get(provider.id):

        return "session"

    return "none"


def get_api_key(provider_id=None):

    provider = get(provider_id)

    if provider.id == "deepseek":

        return deepseek_client.get_api_key()

    value = _saved_key(provider)

    if value:

        return value

    value = (os.environ.get(provider.env_var) or "").strip()

    if value:

        return value

    return _SESSION_KEYS.get(provider.id)


def set_saved_api_key(provider_id, value):

    provider = get(provider_id)

    text = (value or "").strip()

    if not text:

        raise ValueError("API key is empty")

    if provider.id == "deepseek":

        return deepseek_client.set_saved_api_key(text)

    credential_store.save_secret(
        text,
        target=provider.credential_target,
    )
    return text


def delete_saved_api_key(provider_id):

    provider = get(provider_id)

    if provider.id == "deepseek":

        return deepseek_client.delete_saved_api_key()

    return credential_store.delete_secret(
        provider.credential_target
    )


def set_session_api_key(provider_id, value):

    provider = get(provider_id)
    text = (value or "").strip()

    if provider.id == "deepseek":

        return deepseek_client.set_session_api_key(text)

    _SESSION_KEYS[provider.id] = text or None
    return _SESSION_KEYS.get(provider.id)


def clear_session_api_key(provider_id=None):

    if provider_id is None:

        _SESSION_KEYS.clear()
        deepseek_client.clear_session_api_key()
        return

    provider = get(provider_id)

    if provider.id == "deepseek":

        deepseek_client.clear_session_api_key()
        return

    _SESSION_KEYS.pop(provider.id, None)


def request_body(provider_id, model, payload):
    """Return the exact UTF-8 bytes the provider adapter will send."""

    provider = get(provider_id)
    selected_model = str(model or provider.default_model)
    return ai_http.encode_json(
        provider.build_body(payload, selected_model)
    )


def make_streamer(provider_id, model, body=None):

    provider = get(provider_id)
    selected_model = str(model or provider.default_model)

    if body is not None:

        raw_body = bytes(body)

        def stream_body_only(
            payload=None,
            api_key=None,
            timeout=None,
            should_stop=None,
        ):

            return provider.stream_body(
                raw_body,
                api_key=api_key,
                timeout=timeout,
                should_stop=should_stop,
            )

        return stream_body_only

    def stream(
        payload,
        api_key=None,
        timeout=None,
        should_stop=None,
    ):

        return provider.stream(
            payload,
            model=selected_model,
            api_key=api_key,
            timeout=timeout,
            should_stop=should_stop,
        )

    return stream


def selection_from_settings(settings):
    """Read the persisted provider and model, falling back safely."""

    provider = get(getattr(settings, "ai_provider", lambda: None)())

    model = str(
        getattr(settings, "ai_model", lambda _id: "")(provider.id)
        or provider.default_model
    )

    return provider.id, model


def probe(provider_id, model, api_key=None, timeout=15.0):
    """Verify a key with one minimal real streaming request.

    Returns True when the provider accepts the key and starts producing
    assistant text.  DeepSeek keeps its existing non-streaming probe.
    """

    provider = get(provider_id)
    key = (api_key or "").strip() or get_api_key(provider.id)

    if not key:

        raise ai_stream.StreamError("missing_key")

    if provider.id == "deepseek":

        return bool(
            deepseek_client.test_connection()
        )

    payload = {
        "messages": [
            {
                "role": "user",
                "content": "Reply with OK only.",
            }
        ]
    }
    state = {"seen": False}

    def should_stop():

        return state["seen"]

    events = provider.stream(
        payload,
        model=str(model or provider.default_model),
        api_key=key,
        timeout=timeout,
        should_stop=should_stop,
    )

    try:

        for event in events:

            if isinstance(event, ai_stream.TextDelta):

                state["seen"] = True
                return True

    finally:

        close = getattr(events, "close", None)

        if callable(close):

            try:

                close()

            except Exception:

                pass

    return False
