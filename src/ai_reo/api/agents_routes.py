"""REST endpoints — expose agent registry metadata to the frontend."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentInfo(BaseModel):
    name: str
    description: str
    primary_tools: str
    route_keywords: List[str]
    allowed_tools: List[str]


@router.get("", response_model=List[AgentInfo], summary="List all registered agents")
async def list_agents() -> List[AgentInfo]:
    """Return metadata for every agent defined in AGENT_REGISTRY."""
    from ai_reo.agents.specialized import AGENT_REGISTRY

    result = []
    for name, meta in AGENT_REGISTRY.items():
        agent_cls = meta["class"]
        try:
            instance = agent_cls()
            allowed = list(getattr(instance, "allowed_tools", []))
        except Exception:
            allowed = []
        result.append(
            AgentInfo(
                name=name,
                description=meta["description"],
                primary_tools=meta["primary_tools"],
                route_keywords=meta["route_keywords"],
                allowed_tools=allowed,
            )
        )
    return result


@router.get("/{name}", response_model=AgentInfo, summary="Get a specific agent")
async def get_agent(name: str) -> AgentInfo:
    """Return metadata for a single named agent."""
    from ai_reo.agents.specialized import AGENT_REGISTRY

    meta = AGENT_REGISTRY.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found.")

    agent_cls = meta["class"]
    try:
        instance = agent_cls()
        allowed = list(getattr(instance, "allowed_tools", []))
    except Exception:
        allowed = []

    return AgentInfo(
        name=name,
        description=meta["description"],
        primary_tools=meta["primary_tools"],
        route_keywords=meta["route_keywords"],
        allowed_tools=allowed,
    )
