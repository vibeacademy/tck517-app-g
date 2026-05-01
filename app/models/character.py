"""Character model.

`data` is JSONB on Postgres and JSON on SQLite. The Pydantic shape lives
in app/characters/schema.py (a later ticket); persisting as JSONB lets
the schema iterate without per-prompt migrations. See ADR-004.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, ForeignKey, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Character(SQLModel, table=True):
    __tablename__ = "characters"

    id: UUID = Field(
        sa_column=Column(Uuid, primary_key=True, default=uuid4),
    )
    project_id: UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("projects.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
