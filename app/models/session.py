"""Session model — server-side row for an authenticated browser cookie.

The class name `Session` matches the architecture doc but collides with
`sqlmodel.Session` (the DB session class). Importers that need both
should alias one — e.g. `from app.models.session import Session as
UserSession` — to keep call sites unambiguous.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, Uuid
from sqlmodel import Field, SQLModel


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: UUID = Field(
        sa_column=Column(Uuid, primary_key=True, default=uuid4),
    )
    user_id: UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(nullable=False)
