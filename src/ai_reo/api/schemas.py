"""Pydantic schemas governing API request and response data structures."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    """Payload to spawn a new analysis session."""
    binary_path: str
    binary_hash: str
    name: Optional[str] = None
    working_dir: Optional[str] = None


class SessionRenameRequest(BaseModel):
    """Payload to rename an existing session."""
    name: str


class SessionResponse(BaseModel):
    """Standardized representation of an ongoing or completed session."""
    id: str
    name: Optional[str]
    status: str
    binary_path: str
    binary_hash: str
    working_dir: Optional[str]
    created_at: str


class GraphExportResponse(BaseModel):
    """Knowledge Graph bulk dump serialization."""
    session_id: str
    nodes: List[Dict[str, Any]]


class AnalyzeRequest(BaseModel):
    """Payload to instruct the Orchestrator with a new objective."""
    goal: str


class AnalyzeResponse(BaseModel):
    """Result of passing the state through the LangGraph agents."""
    status: str
    final_report: Optional[str] = None
    active_agent: Optional[str] = None


class ToolInvokeRequest(BaseModel):
    """Payload for manual human-in-the-loop tool execution overrides."""
    tool_name: str
    kwargs: Dict[str, Any]


class BinaryUploadResponse(BaseModel):
    """Response carrying the locally sandboxed path and calculated SHA256 of an uploaded binary."""
    filename: str
    binary_hash: str
    size_bytes: int


class ZipUploadResponse(BaseModel):
    """Response after extracting an uploaded ZIP archive into the session binary directory."""
    filenames: List[str]
    binary_hash: str
    total_size_bytes: int


# ---------------------------------------------------------------------------
# LLM Provider Management Schemas
# ---------------------------------------------------------------------------

class ProviderCreateRequest(BaseModel):
    """Payload to register a new LLM provider at runtime."""
    id: Optional[str] = None
    display_name: str
    provider_type: str                      # openai | anthropic | google | mistral | ollama | lmstudio | generic
    api_key: Optional[str] = None
    base_url: Optional[str] = None          # Required for ollama, lmstudio, generic
    models: List[str] = []                  # Available model tags
    selected_model: str = "auto"            # "auto" or a specific model name
    enabled: bool = True
    # Advanced settings
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    request_timeout: Optional[int] = None


class ProviderUpdateRequest(BaseModel):
    """Partial update payload for an existing provider."""
    display_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: Optional[List[str]] = None
    selected_model: Optional[str] = None
    enabled: Optional[bool] = None
    # Advanced settings
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    request_timeout: Optional[int] = None


class ProviderResponse(BaseModel):
    """Serialized provider configuration returned by the API (api_key masked)."""
    id: str
    display_name: str
    provider_type: str
    has_api_key: bool                       # True if key is set, never expose the raw key
    base_url: Optional[str]
    models: List[str]
    selected_model: str
    enabled: bool
    tested: bool                            # Whether test_connection has passed at least once


class ProviderTestResult(BaseModel):
    """Result of a live provider connectivity test."""
    ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
