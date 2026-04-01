"""Tests provider create semantics for restart-safe ID stability."""

import uuid

from ai_reo.api.provider_routes import create_provider
from ai_reo.api.schemas import ProviderCreateRequest
from ai_reo.llm.providers import llm_manager


def _reset_manager() -> None:
    for cfg in list(llm_manager.list_providers()):
        llm_manager.remove_provider(cfg.id)


def test_create_provider_honors_client_id() -> None:
    _reset_manager()
    provider_id = str(uuid.uuid4())

    resp = create_provider(
        ProviderCreateRequest(
            id=provider_id,
            display_name="LM Studio",
            provider_type="lmstudio",
            base_url="http://localhost:1234",
            models=["openai/local-model"],
            selected_model="auto",
            enabled=True,
        )
    )

    assert resp.id == provider_id


def test_create_provider_with_same_id_updates_in_place() -> None:
    _reset_manager()
    provider_id = str(uuid.uuid4())

    create_provider(
        ProviderCreateRequest(
            id=provider_id,
            display_name="Provider A",
            provider_type="lmstudio",
            base_url="http://localhost:1234",
            models=["openai/local-model"],
            selected_model="auto",
            enabled=True,
        )
    )

    updated = create_provider(
        ProviderCreateRequest(
            id=provider_id,
            display_name="Provider B",
            provider_type="lmstudio",
            base_url="http://localhost:1234",
            models=["openai/local-model"],
            selected_model="auto",
            enabled=False,
        )
    )

    providers = llm_manager.list_providers()
    assert len(providers) == 1
    assert updated.id == provider_id
    assert updated.display_name == "Provider B"
    assert updated.enabled is False
