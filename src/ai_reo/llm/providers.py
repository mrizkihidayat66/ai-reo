"""LLM Provider abstractions and connection management.

All provider configuration (API keys, models, base URLs) is managed at runtime
through the frontend UI. There is no .env seeding — the registry starts empty
and is populated by API calls from the React ProvidersContext on mount.
"""

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

import litellm

from ai_reo.exceptions import LLMError, LLMProviderUnavailableError


# ---------------------------------------------------------------------------
# Provider Config Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """Runtime configuration for a single LLM provider instance."""
    display_name: str
    provider_type: str          # openai | anthropic | google | mistral | ollama | lmstudio | generic
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: List[str] = field(default_factory=list)
    selected_model: str = "auto"
    enabled: bool = True
    tested: bool = False        # True once a successful test_connection completes

    def get_effective_model(self) -> str:
        """Return the model to use: first in list if 'auto', else selected_model."""
        if self.selected_model == "auto":
            return self.models[0] if self.models else self._default_model()
        return self.selected_model

    def _default_model(self) -> str:
        defaults = {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20241022",
            "google": "gemini/gemini-2.0-flash",
            "mistral": "mistral/mistral-large-latest",
            "ollama": "ollama/llama3",
            "lmstudio": "openai/local-model",
            "generic": "openai/local-model",
        }
        return defaults.get(self.provider_type, "gpt-4o")


# ---------------------------------------------------------------------------
# Abstract Provider Interface
# ---------------------------------------------------------------------------

class BaseLLMProvider(ABC):
    """Abstract interface for LLM backends."""

    @abstractmethod
    async def chat_completion(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Any:
        """Issue a standard chat completion request."""
        pass

    @abstractmethod
    async def chat_stream(
        self, messages: List[Dict[str, Any]], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """Issue a streaming chat completion request yielding text chunks."""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Verify provider configured correctly and endpoint is theoretically reachable."""
        pass


# ---------------------------------------------------------------------------
# Dynamic Litellm-Backed Provider  (handles all provider types via litellm)
# ---------------------------------------------------------------------------

class DynamicLitellmProvider(BaseLLMProvider):
    """A single provider that routes any ProviderConfig through litellm's unified API."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def _litellm_model(self) -> str:
        """Build the litellm model string from provider_type and effective model."""
        ptype = self.config.provider_type
        model = self.config.get_effective_model()

        # litellm already uses prefixed format for most providers
        prefixed = {"openai", "anthropic", "google", "mistral"}
        if ptype in prefixed:
            return model if "/" in model else model
        if ptype in ("ollama", "lmstudio", "generic"):
            return model if "/" in model else f"openai/{model}"
        return model

    def _litellm_kwargs(self) -> Dict[str, Any]:
        """Build extra kwargs (api_base, api_key) for litellm."""
        kw: Dict[str, Any] = {}
        if self.config.api_key:
            kw["api_key"] = self.config.api_key
        if self.config.base_url:
            kw["api_base"] = self.config.base_url
        return kw

    async def chat_completion(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Any:
        try:
            return await litellm.acompletion(
                model=self._litellm_model(),
                messages=messages,
                **self._litellm_kwargs(),
                **kwargs,
            )
        except Exception as e:
            raise LLMError(f"[{self.config.display_name}] completion failed: {e}")

    async def chat_stream(
        self, messages: List[Dict[str, Any]], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        try:
            response = await litellm.acompletion(
                model=self._litellm_model(),
                messages=messages,
                stream=True,
                **self._litellm_kwargs(),
                **kwargs,
            )
            async for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            raise LLMError(f"[{self.config.display_name}] stream failed: {e}")

    def health_check(self) -> bool:
        ptype = self.config.provider_type
        if ptype in ("ollama", "lmstudio", "generic"):
            return bool(self.config.base_url)
        return bool(self.config.api_key)


# ---------------------------------------------------------------------------
# LLM Manager — dynamic, runtime-configurable (no .env seeding)
# ---------------------------------------------------------------------------

class LLMManager:
    """Manager holding initialized providers and routing requests to enabled ones.

    The registry starts EMPTY. Providers are registered at runtime by the
    frontend ProvidersContext which POSTs each stored provider on mount.
    """

    def __init__(self) -> None:
        # id → ProviderConfig registry
        self._configs: Dict[str, ProviderConfig] = {}
        # id → BaseLLMProvider instance
        self._providers: Dict[str, DynamicLitellmProvider] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register_provider(self, config: ProviderConfig) -> ProviderConfig:
        """Register or replace a provider config."""
        self._configs[config.id] = config
        self._providers[config.id] = DynamicLitellmProvider(config)
        return config

    def update_provider(self, provider_id: str, **updates: Any) -> ProviderConfig:
        """Apply partial updates to an existing provider."""
        cfg = self._get_config(provider_id)
        for k, v in updates.items():
            if v is not None and hasattr(cfg, k):
                setattr(cfg, k, v)
        # Rebuild the litellm provider instance to pick up changes
        self._providers[provider_id] = DynamicLitellmProvider(cfg)
        return cfg

    def remove_provider(self, provider_id: str) -> None:
        self._configs.pop(provider_id, None)
        self._providers.pop(provider_id, None)

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        self._get_config(provider_id).enabled = enabled

    def list_providers(self) -> List[ProviderConfig]:
        return list(self._configs.values())

    def _get_config(self, provider_id: str) -> ProviderConfig:
        if provider_id not in self._configs:
            raise LLMProviderUnavailableError(f"Provider '{provider_id}' not found.")
        return self._configs[provider_id]

    # ------------------------------------------------------------------
    # Live test
    # ------------------------------------------------------------------

    async def test_provider(self, provider_id: str) -> Dict[str, Any]:
        """Send a minimal completion to verify the provider is reachable."""
        provider = self._providers.get(provider_id)
        cfg = self._get_config(provider_id)
        if not provider:
            return {"ok": False, "latency_ms": None, "error": "Provider not instantiated."}
        t0 = time.monotonic()
        try:
            await provider.chat_completion(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            cfg.tested = True
            return {"ok": True, "latency_ms": elapsed, "error": None}
        except Exception as e:
            return {"ok": False, "latency_ms": None, "error": str(e)}

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def get_provider(self, name: Optional[str] = None) -> DynamicLitellmProvider:
        """Get a provider by id, or auto-select the best enabled one."""
        if name and name in self._providers:
            return self._providers[name]

        # Auto-select: prefer tested+enabled, then any enabled
        enabled = [p for p in self._configs.values() if p.enabled]
        tested_enabled = [p for p in enabled if p.tested]
        target = (tested_enabled or enabled or list(self._configs.values()))

        if not target:
            raise LLMProviderUnavailableError(
                "No LLM providers configured. Visit the Settings page to add one."
            )
        return self._providers[target[0].id]


# Global singleton
llm_manager = LLMManager()
