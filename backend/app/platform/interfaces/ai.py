"""AI provider interface."""
from abc import abstractmethod
from typing import Iterator
from app.platform.interfaces.base import BaseProvider

class AIProvider(BaseProvider):
    """Abstraction interface for LLM provider operations (Ollama, OpenAI, Gemini, etc.)."""

    @abstractmethod
    def complete(self, prompt: str, model: str) -> str:
        """Run text completion on a fully-assembled prompt."""
        pass

    @abstractmethod
    def stream_complete(self, prompt: str, model: str) -> Iterator[str]:
        """Stream completion tokens progressively."""
        pass
