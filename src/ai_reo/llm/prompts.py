"""Engine for loading and rendering JSON-based prompt templates."""

import json
from pathlib import Path
from typing import Any, Dict


class SafeDict(dict):
    """A dictionary that returns the original brace-wrapped key when missing.
    Prevents str.format() from crashing if a template expects {kg_summary} but it's not provided.
    """
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


_DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptEngine:
    """Loads prompt templates from the filesystem and renders them with variables."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self.templates_dir = templates_dir or _DEFAULT_PROMPTS_DIR
        self.templates: Dict[str, Dict[str, Any]] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.templates_dir.exists():
            return
            
        for json_file in self.templates_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "name" in data:
                        self.templates[data["name"]] = data
            except (json.JSONDecodeError, OSError) as e:
                # Log error gracefully in a full implementation
                print(f"Failed to load prompt template {json_file}: {e}")

    def get_template(self, template_name: str) -> Dict[str, Any]:
        """Get the raw template definition dictionary."""
        if template_name not in self.templates:
            raise ValueError(f"Prompt template '{template_name}' not found in {self.templates_dir}")
        return self.templates[template_name]

    def render(self, template_name: str, **kwargs: Any) -> str:
        """Render the 'system' field of a specific template with context variables."""
        template_data = self.get_template(template_name)
        system_text = template_data.get("system", "")
        
        # Robust string replacement to avoid JSON bracket { } parsing crash from str.format()
        for k, v in kwargs.items():
            system_text = system_text.replace(f"{{{k}}}", str(v))
            
        return system_text

# Global singleton
prompt_engine = PromptEngine()
