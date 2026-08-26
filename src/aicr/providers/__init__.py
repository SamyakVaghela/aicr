from __future__ import annotations

from typing import Any, Dict

from .base import ConfigError, Provider, ProviderError

_REGISTRY = {}


def _load():
    if _REGISTRY:
        return _REGISTRY
    from .anthropic_provider import AnthropicProvider
    from .gemini_provider import GeminiProvider
    from .mock_provider import MockProvider
    from .ollama_provider import OllamaProvider
    from .openai_provider import OpenAIProvider

    _REGISTRY.update({
        "anthropic": AnthropicProvider,
        "claude": AnthropicProvider,
        "openai": OpenAIProvider,
        "azure": OpenAIProvider,
        "openai-compatible": OpenAIProvider,
        "gemini": GeminiProvider,
        "google": GeminiProvider,
        "ollama": OllamaProvider,
        "local": OllamaProvider,
        "mock": MockProvider,
    })
    return _REGISTRY


def available() -> list:
    return sorted({"anthropic", "openai", "gemini", "ollama", "mock"})


def get_provider(name: str, cfg: Dict[str, Any]) -> Provider:
    reg = _load()
    key = (name or "").strip().lower()
    if key not in reg:
        raise ConfigError(
            f"Unknown provider '{name}'. Choose one of: {', '.join(available())}"
        )
    return reg[key](cfg)


__all__ = ["Provider", "ProviderError", "ConfigError", "get_provider", "available"]
