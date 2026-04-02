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
# Model tier classification for smart auto-selection
# ---------------------------------------------------------------------------

# Substring → tier mapping.  "large" = capable / slow, "fast" = lightweight / quick.
_MODEL_TIER_MAP: Dict[str, str] = {
    # OpenAI
    "gpt-4o-mini": "fast",
    "gpt-3.5": "fast",
    "gpt-4o": "large",
    "gpt-4-turbo": "large",
    "gpt-4": "large",
    "o1": "large",
    "o3": "large",
    # Anthropic
    "claude-3-5-haiku": "fast",
    "claude-3-haiku": "fast",
    "claude-3-5-sonnet": "large",
    "claude-3-opus": "large",
    "claude-sonnet": "large",
    "claude-opus": "large",
    # Google
    "gemini-2.0-flash": "fast",
    "gemini-1.5-flash": "fast",
    "gemini-2.0-pro": "large",
    "gemini-1.5-pro": "large",
    "gemini-2.5-pro": "large",
    # Mistral
    "mistral-small": "fast",
    "mistral-medium": "large",
    "mistral-large": "large",
    # Local / default
    "llama3": "fast",
    "codellama": "fast",
}


def _model_tier(model_name: str) -> str:
    """Classify a model as 'large' or 'fast' based on known name patterns."""
    lower = model_name.lower()
    # Check longer substrings first to avoid "gpt-4o" matching before "gpt-4o-mini"
    for substr in sorted(_MODEL_TIER_MAP, key=len, reverse=True):
        if substr in lower:
            return _MODEL_TIER_MAP[substr]
    return "fast"  # Unknown models default to fast


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
    # Advanced settings (optional overrides)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    request_timeout: Optional[int] = None

    def get_effective_model(self, task_type: str = "ANALYSIS") -> str:
        """Return the model to use, considering task type for 'auto' selection.

        For ANALYSIS tasks, prefer larger/more capable models.
        For CHAT tasks, prefer faster models.
        """
        if self.selected_model != "auto":
            return self.selected_model
        if not self.models:
            return self._default_model()

        preferred_tier = "large" if task_type == "ANALYSIS" else "fast"
        for m in self.models:
            if _model_tier(m) == preferred_tier:
                return m
        return self.models[0]

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

    def _litellm_model(self, task_type: str = "ANALYSIS") -> str:
        """Build the litellm model string from provider_type and effective model."""
        ptype = self.config.provider_type
        model = self.config.get_effective_model(task_type=task_type)

        # litellm already uses prefixed format for most providers
        prefixed = {"openai", "anthropic", "google", "mistral"}
        if ptype in prefixed:
            return model if "/" in model else model
        if ptype in ("ollama", "lmstudio", "generic"):
            return model if "/" in model else f"openai/{model}"
        return model

    def _litellm_kwargs(self) -> Dict[str, Any]:
        """Build extra kwargs (api_base, api_key, advanced settings) for litellm."""
        kw: Dict[str, Any] = {}
        if self.config.api_key:
            kw["api_key"] = self.config.api_key
        if self.config.base_url:
            kw["api_base"] = self.config.base_url
        if self.config.temperature is not None:
            kw["temperature"] = self.config.temperature
        if self.config.max_tokens is not None:
            kw["max_tokens"] = self.config.max_tokens
        if self.config.request_timeout is not None:
            kw["timeout"] = self.config.request_timeout
        return kw

    async def chat_completion(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Any:
        task_type = kwargs.pop("task_type", "ANALYSIS")
        try:
            return await litellm.acompletion(
                model=self._litellm_model(task_type=task_type),
                messages=messages,
                **self._litellm_kwargs(),
                **kwargs,
            )
        except Exception as e:
            raise LLMError(f"[{self.config.display_name}] completion failed: {e}")

    async def chat_stream(
        self, messages: List[Dict[str, Any]], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        task_type = kwargs.pop("task_type", "ANALYSIS")
        try:
            response = await litellm.acompletion(
                model=self._litellm_model(task_type=task_type),
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
                max_tokens=16,
            )
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            cfg.tested = True
            return {"ok": True, "latency_ms": elapsed, "error": None}
        except Exception as e:
            return {"ok": False, "latency_ms": None, "error": str(e)}

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def get_provider(self, name: Optional[str] = None, task_type: str = "ANALYSIS") -> DynamicLitellmProvider:
        """Get a provider by id, or auto-select the best one for the task type.

        Scoring: tested (+3), enabled (+2), has matching-tier model (+1).
        For ANALYSIS tasks, prefer providers with a \"large\" tier model.
        For CHAT tasks, prefer providers with a \"fast\" tier model.
        """
        if name and name in self._providers:
            return self._providers[name]

        candidates = list(self._configs.values())
        if not candidates:
            raise LLMProviderUnavailableError(
                "No LLM providers configured. Visit the Settings page to add one."
            )

        preferred_tier = "large" if task_type == "ANALYSIS" else "fast"

        def _score(cfg: ProviderConfig) -> int:
            s = 0
            if cfg.enabled:
                s += 2
            if cfg.tested:
                s += 3
            # Check if any of the provider's models match the preferred tier
            if any(_model_tier(m) == preferred_tier for m in cfg.models):
                s += 1
            return s

        candidates.sort(key=_score, reverse=True)
        best = candidates[0]
        return self._providers[best.id]


# Global singleton
llm_manager = LLMManager()
