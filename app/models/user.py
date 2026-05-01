"""User model.

Email is stored case-insensitively (citext on Postgres, plain String on
SQLite for tests). Magic-link auth state lives on this row: a freshly
minted nonce is persisted before sending an email, and rotated again
when the link is consumed — that rotation is what enforces single-use.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Uuid
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(
        sa_column=Column(Uuid, primary_key=True, default=uuid4),
    )
    email: str = Field(
        sa_column=Column(
            String(255).with_variant(CITEXT(), "postgresql"),
            unique=True,
            nullable=False,
        ),
    )
    magic_link_nonce: str | None = Field(default=None)
    magic_link_sent_at: datetime | None = Field(default=None)
    last_login_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
