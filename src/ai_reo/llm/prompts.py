"""Agent prompt engine — reads Markdown instruction files from agents_dir.

Each agent has a dedicated ``<name>.md`` file in the configured ``agents_dir``
(defaults to the bundled ``agents/`` directory at the repo root).

File format:
    ---
    name: static_analyst
    version: "2.1"
    description: ...
    when_to_use: |
      ...
    ---

    <system prompt body with {placeholder} variables>

To customise an agent, edit (or replace) the corresponding ``.md`` file,
or point ``AI_REO_AGENTS_DIR`` to a directory containing your overrides.
"""

import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


class PromptEngine:
    """Renders agent system prompts from Markdown instruction files.

    Looks up ``agents_dir/<template_name>.md``, strips YAML frontmatter,
    and substitutes ``{placeholder}`` variables in the body.
    """

    def _agents_dir(self) -> Path:
        from ai_reo.config import settings
        return Path(settings.tools.agents_dir).expanduser().resolve()

    def render(self, template_name: str, **kwargs: Any) -> str:
        """Render the system prompt for the named agent.

        Args:
            template_name: Agent name (e.g. ``'static_analyst'``).
            **kwargs: Variables to substitute into ``{placeholder}`` tokens.

        Returns:
            The rendered system prompt string.

        Raises:
            FileNotFoundError: If the agent's ``.md`` file does not exist.
        """
        agents_dir = self._agents_dir()
        md_file = agents_dir / f"{template_name}.md"

        if not md_file.exists():
            raise FileNotFoundError(
                f"Agent instruction file '{template_name}.md' not found in {agents_dir}. "
                "Ensure AI_REO_AGENTS_DIR points to the agents/ directory."
            )

        text = md_file.read_text(encoding="utf-8")
        text = _FRONTMATTER_RE.sub("", text, count=1).strip()

        for k, v in kwargs.items():
            text = text.replace(f"{{{k}}}", str(v))

        return text


# Global singleton
prompt_engine = PromptEngine()

