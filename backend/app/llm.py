from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import settings


def build_chat_model(**kwargs) -> ChatOpenAI:
    """ChatOpenAI pointed at the Volcengine Ark OpenAI-compatible endpoint."""
    if not settings.ark_api_key:
        raise RuntimeError("ARK_API_KEY is not configured")
    params = {
        "model": settings.ark_model,
        "api_key": settings.ark_api_key,
        "base_url": settings.ark_base_url,
        "streaming": False,
    }
    params.update(kwargs)
    return ChatOpenAI(**params)


def build_streaming_model(**kwargs) -> ChatOpenAI:
    return build_chat_model(streaming=True, **kwargs)