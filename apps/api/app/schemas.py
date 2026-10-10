import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings


class ChatRequest(BaseModel):
    application_id: uuid.UUID
    message: str = Field(min_length=1)
    locale: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    conversation_id: str | None = Field(default=None, max_length=64)

    @field_validator("message")
    @classmethod
    def _check_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        if len(v) > get_settings().chat_max_chars:
            raise ValueError("message too long")
        return v


class ChatUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class ChatResponse(BaseModel):
    reply: str
    cache_status: Literal["miss", "exact_hit", "semantic_hit", "bypass", "error"]
    usage: ChatUsage
    estimated_cost_myr: float
    request_id: uuid.UUID
    provider_mode: Literal["mock", "live", "none"]  # "none": answered from approved FAQ, no provider call
    request_category: str
    cache_decision: str | None = None
    faq_intent_key: str | None = None
    similarity: float | None = None


class ChatSessionResponse(BaseModel):
    token: str
    expires_at: datetime
    application_id: uuid.UUID
    workspace_name: str


class DevLoginRequest(BaseModel):
    role: Literal["owner", "viewer"] = "owner"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret


class MembershipOut(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    role: str


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str | None
    memberships: list[MembershipOut]


class ApplicationOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    has_api_key: bool


class WorkspaceSettings(BaseModel):
    workspace_id: uuid.UUID
    name: str
    monthly_budget_myr: float
    currency: str
    timezone: str
    knowledge_version: int
    role: str
    applications: list[ApplicationOut]
    data_sources: dict[str, int]
    provider_mode: Literal["mock", "live"]
    fx_myr_per_usd_demo: float
    pricing_catalog_version: str


class WorkspaceSettingsPatch(BaseModel):
    monthly_budget_myr: float | None = Field(default=None, ge=0, le=1_000_000)
    timezone: str | None = Field(default=None, max_length=64)


class RotatedKeyResponse(BaseModel):
    application_id: uuid.UUID
    api_key: str
    note: str = "Shown once. Store it securely; only a hash is kept."
