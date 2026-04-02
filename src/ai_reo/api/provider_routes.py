"""REST endpoints for runtime LLM provider management."""

import uuid
from typing import List

from fastapi import APIRouter, HTTPException

from ai_reo.api.schemas import (
    ProviderCreateRequest,
    ProviderResponse,
    ProviderTestResult,
    ProviderUpdateRequest,
)
from ai_reo.llm.providers import ProviderConfig, llm_manager

router = APIRouter(prefix="/providers", tags=["providers"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_response(cfg: ProviderConfig) -> ProviderResponse:
    return ProviderResponse(
        id=cfg.id,
        display_name=cfg.display_name,
        provider_type=cfg.provider_type,
        has_api_key=bool(cfg.api_key),
        base_url=cfg.base_url,
        models=cfg.models,
        selected_model=cfg.selected_model,
        enabled=cfg.enabled,
        tested=cfg.tested,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[ProviderResponse])
def list_providers() -> List[ProviderResponse]:
    """Return all registered provider configs (API keys masked)."""
    return [_to_response(cfg) for cfg in llm_manager.list_providers()]


@router.post("/", response_model=ProviderResponse, status_code=201)
def create_provider(req: ProviderCreateRequest) -> ProviderResponse:
    """Register a new LLM provider at runtime."""
    if req.id:
        existing = next((cfg for cfg in llm_manager.list_providers() if cfg.id == req.id), None)
        if existing:
            cfg = llm_manager.update_provider(
                req.id,
                display_name=req.display_name,
                api_key=req.api_key,
                base_url=req.base_url,
                models=req.models,
                selected_model=req.selected_model,
                enabled=req.enabled,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                request_timeout=req.request_timeout,
            )
            return _to_response(cfg)

    cfg = ProviderConfig(
        id=req.id or str(uuid.uuid4()),
        display_name=req.display_name,
        provider_type=req.provider_type,
        api_key=req.api_key or None,
        base_url=req.base_url or None,
        models=req.models,
        selected_model=req.selected_model,
        enabled=req.enabled,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        request_timeout=req.request_timeout,
    )
    llm_manager.register_provider(cfg)
    return _to_response(cfg)


@router.put("/{provider_id}", response_model=ProviderResponse)
def update_provider(provider_id: str, req: ProviderUpdateRequest) -> ProviderResponse:
    """Partially update a provider (models, key, base_url, enabled, selected_model)."""
    try:
        cfg = llm_manager.update_provider(
            provider_id,
            display_name=req.display_name,
            api_key=req.api_key,
            base_url=req.base_url,
            models=req.models,
            selected_model=req.selected_model,
            enabled=req.enabled,
        )
        return _to_response(cfg)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: str) -> None:
    """Remove a provider from the runtime registry."""
    llm_manager.remove_provider(provider_id)


# ---------------------------------------------------------------------------
# Connectivity test
# ---------------------------------------------------------------------------

@router.post("/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(provider_id: str) -> ProviderTestResult:
    """Send a minimal ping to the provider and return latency or error."""
    try:
        result = await llm_manager.test_provider(provider_id)
        return ProviderTestResult(**result)
    except Exception as e:
        return ProviderTestResult(ok=False, error=str(e))
