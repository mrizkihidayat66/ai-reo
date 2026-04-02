"""Skills API routes — list and retrieve agent skill files."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from ai_reo.skills.loader import skill_loader

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillSummary(BaseModel):
    name: str
    targets: List[str]
    tags: List[str]
    universal: bool
    when_to_use: str
    argument_hint: str


class SkillDetail(SkillSummary):
    content: str


@router.get("", response_model=List[SkillSummary], summary="List all loaded skills")
async def list_skills() -> List[SkillSummary]:
    """Return metadata for every skill loaded from the skills directory."""
    skill_loader.reload()
    return [
        SkillSummary(
            name=s.name,
            targets=s.targets,
            tags=s.tags,
            universal=s.is_universal,
            when_to_use=s.when_to_use,
            argument_hint=s.argument_hint,
        )
        for s in skill_loader.load_all()
    ]


@router.get("/{name}", response_model=SkillDetail, summary="Get a specific skill")
async def get_skill(name: str) -> SkillDetail:
    """Return the full content and metadata for a named skill."""
    for s in skill_loader.load_all():
        if s.name == name:
            return SkillDetail(
                name=s.name,
                targets=s.targets,
                tags=s.tags,
                universal=s.is_universal,
                when_to_use=s.when_to_use,
                argument_hint=s.argument_hint,
                content=s.content,
            )
    raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
