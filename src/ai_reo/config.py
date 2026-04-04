"""Configuration management for AI-REO.

Settings are loaded in this priority order (highest wins):
  1. Real environment variables
  2. .env file in the working directory
  3. Default values below

All settings are prefixed with ``AI_REO_``.

NOTE: LLM provider settings (API keys, models, base URLs) are managed
entirely at runtime via the frontend UI and stored in browser localStorage.
The .env file only governs operational/infrastructure settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env variables into os.environ immediately so nested BaseSettings pick them up
load_dotenv()

# Repo root resolved at import time — works when installed in editable mode (`pip install -e .`).
# Override with AI_REO_AGENTS_DIR / AI_REO_SKILLS_DIR env vars for production deployments.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class DatabaseSettings(BaseSettings):
    """Settings for data persistence."""

    model_config = SettingsConfigDict(env_prefix="AI_REO_")

    database_url: str = Field(
        default="sqlite:///~/.ai-reo/sessions.db",
        description="SQLAlchemy database URL.",
    )


class ToolSettings(BaseSettings):
    """Settings for the Docker-based tool integration layer."""

    model_config = SettingsConfigDict(env_prefix="AI_REO_")

    sessions_dir: Path = Field(
        default=Path.home() / ".ai-reo" / "sessions",
        description="Root directory where per-session working directories are created.",
    )
    docker_network: str = Field(
        default="ai-reo-tools",
        description="Docker network connecting tool containers.",
    )
    max_tool_rounds: int = Field(
        default=10,
        description="Maximum tool-call rounds per agent step before forcing completion.",
    )
    skills_dir: Path = Field(
        default=_REPO_ROOT / "skills",
        description="Directory containing skill .md files. Defaults to the bundled skills/ at the repo root.",
    )
    scripts_dir: Path = Field(
        default=_REPO_ROOT / "tmp" / ".ai-reo" / "scripts",
        description="Persistent directory for agent-generated reusable scripts. Defaults to tmp/.ai-reo/scripts inside the repo.",
    )
    agents_dir: Path = Field(
        default=_REPO_ROOT / "agents",
        description="Directory containing agent instruction .md files. Defaults to the bundled agents/ at the repo root.",
    )
    cape_url: str = Field(
        default="",
        description="Base URL for the CAPE Sandbox REST API (e.g. http://localhost:8000). Leave empty to disable CAPE integration.",
    )


class ServerSettings(BaseSettings):
    """Settings for the FastAPI server."""

    model_config = SettingsConfigDict(env_prefix="AI_REO_")

    host: str = Field(default="127.0.0.1", description="Bind address.")
    port: int = Field(default=9000, description="Bind port.")
    log_level: Literal["debug", "info", "warning", "error", "critical"] = Field(
        default="info",
        description="Logging level for uvicorn and application.",
    )
    max_upload_size_mb: int = Field(
        default=200,
        description="Maximum size (in MB) for ZIP file uploads. Default: 200 MB.",
    )


class Settings(BaseSettings):
    """Root settings object aggregating all sub-configurations."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AI_REO_",
        extra="ignore",
    )

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)


# ---------------------------------------------------------------------------
# Module-level singleton – import this everywhere so settings are shared.
# ---------------------------------------------------------------------------
settings = Settings()
