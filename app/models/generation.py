"""Generation model — audit + cost log of one LLM call.

A row is inserted in `pending` state before the streaming call begins,
then updated to `succeeded` / `failed` with token counts after the
stream finishes. Used to track LLM spend per user and to surface
per-character regeneration history.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, Uuid
from sqlmodel import Field, SQLModel


class GenerationStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Generation(SQLModel, table=True):
    __tablename__ = "generations"

    id: UUID = Field(
        sa_column=Column(Uuid, primary_key=True, default=uuid4),
    )
    project_id: UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    prompt: str = Field(nullable=False)
    status: GenerationStatus = Field(default=GenerationStatus.PENDING, nullable=False)
    model: str = Field(nullable=False)
    input_tokens: int | None = Field(default=None)
    output_tokens: int | None = Field(default=None)
    error: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = Field(default=None)
