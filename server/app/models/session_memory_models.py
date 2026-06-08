"""Pydantic models for optional server-side AgentSessionMemory (Stage 6)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionMetaPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(alias="sessionId")
    last_server_boot_id: str | None = Field(default=None, alias="lastServerBootId")
    schema_fingerprint: str | None = Field(default=None, alias="schemaFingerprint")
    local_updated_at: str | None = Field(default=None, alias="localUpdatedAt")
    server_version: int | None = Field(default=None, alias="serverVersion")
    server_updated_at: str | None = Field(default=None, alias="serverUpdatedAt")


class AgentSessionMemoryPayload(BaseModel):
    """Same logical fields as client ``WorkspaceMemory`` (wire JSON uses camelCase)."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1
    chat_transcript: list[dict[str, Any]] = Field(default_factory=list, alias="chatTranscript")
    agent_transcript: list[dict[str, Any]] = Field(default_factory=list, alias="agentTranscript")
    apply_log: list[dict[str, Any]] = Field(default_factory=list, alias="applyLog")
    preview_history: list[dict[str, Any]] = Field(default_factory=list, alias="previewHistory")
    applied_plans_summary: str = Field(default="", alias="appliedPlansSummary")
    session_meta: SessionMetaPayload = Field(alias="sessionMeta")


class SessionPutRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    memory: AgentSessionMemoryPayload
    project_id: str | None = Field(default=None, alias="projectId")
    workspace_key_hash: str | None = Field(default=None, alias="workspaceKeyHash")
    local_updated_at: str | None = Field(default=None, alias="localUpdatedAt")
    expected_version: int | None = Field(default=None, alias="expectedVersion")


class SessionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    version: int
    updated_at: str = Field(alias="updatedAt")
    memory: AgentSessionMemoryPayload
