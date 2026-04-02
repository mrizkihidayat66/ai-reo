"""Skills loader module for AI-REO.

Skills follow the Anthropic SKILL.md convention: each skill is a directory under
skills_dir containing a SKILL.md file with YAML frontmatter.

Frontmatter schema (required: name, description; AI-REO extension: targets):
    ---
    name: malware-analysis                    # required, lowercase+hyphens
    description: >                            # required; what it does + when to use it
      Structured workflow for malware triage. Use when...
    targets: [static_analyst, deobfuscator]   # AI-REO extension; absent = universal
    ---

Backward-compatible: plain *.md files at the root of skills_dir are also loaded
with the older frontmatter format (when_to_use, tags, argument_hint).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_yaml_list(raw: str) -> List[str]:
    """Minimal YAML list parser — handles both inline and block list formats."""
    raw = raw.strip()
    # Inline: [a, b, c]
    if raw.startswith("[") and raw.endswith("]"):
        return [item.strip().strip("'\"") for item in raw[1:-1].split(",") if item.strip()]
    # Block:
    #   - a
    #   - b
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip().strip("'\""))
    return items


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_without_frontmatter)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    fm_raw = match.group(1)
    body = text[match.end():]
    fm: dict = {}

    current_key: str | None = None
    current_lines: List[str] = []

    def _flush() -> None:
        if current_key is not None:
            value = "\n".join(current_lines).strip()
            fm[current_key] = value

    for line in fm_raw.splitlines():
        if ":" in line and not line.startswith(" ") and not line.startswith("-"):
            _flush()
            key, _, rest = line.partition(":")
            current_key = key.strip()
            current_lines = [rest.strip()]
        else:
            current_lines.append(line)

    _flush()

    # Parse list fields
    parsed: dict = {}
    for k, v in fm.items():
        if v.startswith("[") or "\n- " in ("\n" + v):
            parsed[k] = _parse_yaml_list(v)
        else:
            parsed[k] = v

    return parsed, body


@dataclass
class Skill:
    name: str
    content: str
    targets: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    when_to_use: str = ""
    argument_hint: str = ""

    @property
    def is_universal(self) -> bool:
        return not self.targets


class SkillLoader:
    """Scans skills_dir for .md files and provides per-agent skill lookup."""

    def __init__(self) -> None:
        self._cache: List[Skill] | None = None

    def _skills_dir(self) -> Path:
        from ai_reo.config import settings
        return Path(settings.tools.skills_dir).expanduser().resolve()

    def reload(self) -> None:
        """Force a reload of all skills from disk on next access."""
        self._cache = None

    def load_all(self) -> List[Skill]:
        """Return all skills, loading from disk if necessary."""
        if self._cache is not None:
            return self._cache

        skills_dir = self._skills_dir()
        if not skills_dir.exists():
            self._cache = []
            return self._cache

        loaded: List[Skill] = []
        for md_file in sorted(skills_dir.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                fm, body = _parse_frontmatter(text)

                # SKILL.md convention: name comes from frontmatter or parent directory name.
                # Legacy flat files: name comes from the file stem.
                if md_file.name == "SKILL.md":
                    skill_name = fm.get("name") or md_file.parent.name
                else:
                    skill_name = md_file.stem

                # Support both new-style `description` and legacy `when_to_use` field.
                when_to_use = fm.get("when_to_use") or fm.get("description", "")

                skill = Skill(
                    name=skill_name,
                    content=body.strip(),
                    targets=fm.get("targets", []),
                    tags=fm.get("tags", []),
                    when_to_use=when_to_use,
                    argument_hint=fm.get("argument_hint", ""),
                )
                loaded.append(skill)
                logger.debug("Loaded skill '%s' (targets=%s)", skill.name, skill.targets)
            except Exception as exc:
                logger.warning("Failed to load skill from %s: %s", md_file, exc)

        self._cache = loaded
        logger.info("Skill loader: loaded %d skill(s) from %s", len(loaded), skills_dir)
        return self._cache

    def get_for_agent(self, agent_name: str) -> List[Skill]:
        """Return all skills that apply to the given agent (universal + agent-targeted)."""
        agent_lower = agent_name.lower()
        return [
            s for s in self.load_all()
            if s.is_universal or any(t.lower() == agent_lower for t in s.targets)
        ]


# Module-level singleton
skill_loader = SkillLoader()
