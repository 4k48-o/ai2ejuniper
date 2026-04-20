class LLMError(Exception):
    """Base LLM error."""


class LLMTimeoutError(LLMError):
    """LLM request timed out."""


class LLMRefusalError(LLMError):
    """LLM refused to respond."""


class LLMParseError(LLMError):
    """Failed to parse LLM response."""


class LLMQuotaError(LLMError):
    """LLM API quota exceeded."""
