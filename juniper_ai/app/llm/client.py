"""Unified LLM client interface with provider abstraction."""

import logging
from abc import ABC
from typing import Any

from juniper_ai.app.config import settings
from juniper_ai.app.llm.exceptions import LLMQuotaError, LLMRefusalError, LLMTimeoutError

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract LLM client with shared chat logic (template method pattern).

    Subclasses only need to set ``self._llm`` in ``__init__``.
    """

    _llm: Any  # langchain BaseChatModel

    # -- public API ----------------------------------------------------------

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Send messages to LLM and get a response.

        Returns: {"content": str, "tool_calls": list[dict] | None}
        """
        try:
            llm = self._llm.bind_tools(tools) if tools else self._llm
            response = await llm.ainvoke(messages)

            tool_calls = None
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_calls = [
                    {"name": tc["name"], "args": tc["args"], "id": tc.get("id", "")}
                    for tc in response.tool_calls
                ]

            return {"content": response.content, "tool_calls": tool_calls}
        except Exception as e:
            self._handle_error(e)

    async def chat_stream(self, messages: list[dict], tools: list[dict] | None = None):
        """Stream response from LLM."""
        try:
            llm = self._llm.bind_tools(tools) if tools else self._llm
            async for chunk in llm.astream(messages):
                yield chunk
        except Exception as e:
            self._handle_error(e)

    def bind_tools(self, tools: list) -> Any:
        """Return the underlying LLM bound with the given tools."""
        return self._llm.bind_tools(tools)

    # -- error handling (shared) ---------------------------------------------

    @staticmethod
    def _handle_error(e: Exception):
        error_str = str(e).lower()
        if "timeout" in error_str:
            raise LLMTimeoutError(str(e)) from e
        if "rate" in error_str or "quota" in error_str or "429" in str(e):
            raise LLMQuotaError(str(e)) from e
        if "refused" in error_str or "safety" in error_str:
            raise LLMRefusalError(str(e)) from e
        raise


class AnthropicClient(LLMClient):
    """Claude provider via langchain-anthropic."""

    def __init__(self):
        from langchain_anthropic import ChatAnthropic

        self._llm = ChatAnthropic(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
            timeout=60,
        )


class OpenAIClient(LLMClient):
    """GPT provider via langchain-openai."""

    def __init__(self):
        from langchain_openai import ChatOpenAI

        self._llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            max_tokens=4096,
            timeout=60,
        )


_cached_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Factory: return the configured LLM client (cached singleton)."""
    global _cached_client
    if _cached_client is not None:
        return _cached_client

    if settings.llm_provider == "anthropic":
        _cached_client = AnthropicClient()
    elif settings.llm_provider == "openai":
        _cached_client = OpenAIClient()
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")

    return _cached_client
