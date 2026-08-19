"""Custom exceptions for AiR LLM library."""


class AiRLLMError(Exception):
    """Base exception for AiR LLM library."""
    pass


class PhaseLoadError(AiRLLMError):
    """Raised when a model cannot be loaded for a phase."""
    pass


class DeviceConstraintError(AiRLLMError):
    """Raised when device doesn't have resources for requested phase."""
    pass


class OllamaConnectionError(AiRLLMError):
    """Raised when Ollama server is unreachable."""
    pass


class ModelNotFoundError(AiRLLMError):
    """Raised when requested model is not available."""
    pass


class UseCardNotRegisteredError(AiRLLMError):
    """Raised when use case is not registered to a phase."""
    pass
