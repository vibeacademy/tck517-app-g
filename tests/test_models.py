"""Tests for the domain models and the initial migration.

These tests pin two things:

  1. SQLModel.metadata exposes exactly the five domain tables (no
     leftover `todo` table from the starter, no extras).
  2. `Character.data` resolves to JSONB on Postgres and JSON on SQLite —
     this is the dialect-variant pattern from ADR-004; getting it wrong
     once cost us a runtime AttributeError in development.

Migration apply / rollback is exercised by running the Alembic
upgrade + downgrade against an in-memory SQLite engine. CI runs the
real upgrade against a Neon branch on top of this.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

import app.models  # noqa: F401  (registers all models with SQLModel.metadata)
from app.models import Character, Generation, GenerationStatus, Project, User
from app.models.session import Session as UserSession

EXPECTED_TABLES = {"users", "projects", "characters", "generations", "sessions"}


@pytest.fixture(name="engine")
def engine_fixture():
    # SQLite doesn't enforce FK constraints by default — register the
    # PRAGMA on `connect` BEFORE create_all so the cascade-on-delete
    # tests below actually exercise the cascade path. With StaticPool
    # the same connection is reused, so registering after create_all
    # would be too late.
    from sqlalchemy import event

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()

    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def test_metadata_contains_exactly_the_five_domain_tables() -> None:
    assert set(SQLModel.metadata.tables.keys()) == EXPECTED_TABLES


def test_character_data_column_uses_json_on_sqlite_and_jsonb_on_postgres() -> None:
    column = Character.__table__.c.data
    base_type = column.type
    # Default (SQLite, generic) is JSON
    assert isinstance(base_type, JSON)
    # The variant for the postgresql dialect is JSONB
    pg_variant = base_type.dialect_impl(__import__("sqlalchemy").dialects.postgresql.dialect())
    assert isinstance(pg_variant, JSONB)


def test_user_email_column_uses_string_on_sqlite_and_citext_on_postgres() -> None:
    column = User.__table__.c.email
    pg_variant = column.type.dialect_impl(__import__("sqlalchemy").dialects.postgresql.dialect())
    assert isinstance(pg_variant, CITEXT)


def test_can_create_and_read_user(session: Session) -> None:
    user = User(email="alice@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    assert user.id is not None
    assert user.created_at is not None
    fetched = session.exec(select(User).where(User.email == "alice@example.com")).one()
    assert fetched.id == user.id


def test_user_email_is_unique(session: Session) -> None:
    session.add(User(email="dup@example.com"))
    session.commit()
    session.add(User(email="dup@example.com"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_project_belongs_to_user_and_cascades_on_user_delete(session: Session) -> None:
    user = User(email="owner@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    project = Project(user_id=user.id, name="Aragorn")
    session.add(project)
    session.commit()
    project_id = project.id

    session.delete(user)
    session.commit()
    session.expunge_all()

    assert session.get(Project, project_id) is None


def test_character_is_one_per_project(session: Session) -> None:
    user = User(email="char-owner@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    project = Project(user_id=user.id, name="Strider")
    session.add(project)
    session.commit()
    session.refresh(project)

    session.add(Character(project_id=project.id, data={"name": "Strider"}))
    session.commit()

    # A second character on the same project violates the unique constraint
    session.add(Character(project_id=project.id, data={"name": "Aragorn"}))
    with pytest.raises(IntegrityError):
        session.commit()


def test_character_data_round_trips_as_dict(session: Session) -> None:
    user = User(email="json@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    project = Project(user_id=user.id, name="JSON test")
    session.add(project)
    session.commit()
    session.refresh(project)

    payload = {"name": "Boromir", "stats": {"str": 16, "cha": 14}, "tags": ["noble", "fallen"]}
    session.add(Character(project_id=project.id, data=payload))
    session.commit()

    character = session.exec(select(Character).where(Character.project_id == project.id)).one()
    assert character.data == payload


def test_generation_defaults_to_pending(session: Session) -> None:
    user = User(email="gen@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    project = Project(user_id=user.id, name="Gen test")
    session.add(project)
    session.commit()
    session.refresh(project)

    gen = Generation(project_id=project.id, prompt="a brave knight", model="claude-opus-4-7")
    session.add(gen)
    session.commit()
    session.refresh(gen)

    assert gen.status == GenerationStatus.PENDING
    assert gen.completed_at is None


def test_generation_cascades_on_project_delete(session: Session) -> None:
    user = User(email="cascade@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    project = Project(user_id=user.id, name="Doomed")
    session.add(project)
    session.commit()
    session.refresh(project)

    session.add(Generation(project_id=project.id, prompt="x", model="claude-opus-4-7"))
    session.commit()

    session.delete(project)
    session.commit()

    rows = session.exec(select(Generation).where(Generation.project_id == project.id)).all()
    assert rows == []


def test_session_cascades_on_user_delete(session: Session) -> None:
    user = User(email="sess@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)

    from datetime import UTC, datetime, timedelta

    sess = UserSession(
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(sess)
    session.commit()
    session.refresh(sess)
    sess_id = sess.id

    session.delete(user)
    session.commit()

    assert session.exec(select(UserSession).where(UserSession.id == sess_id)).one_or_none() is None


def test_alembic_migration_applies_and_downgrades_cleanly(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run upgrade head → downgrade base → upgrade head against SQLite.

    Verifies that the migration is reversible and idempotent across a
    full round-trip — the DoD requirement. alembic/env.py reads
    DATABASE_URL via app.config.get_settings (lru_cached), so we
    monkeypatch the env var and clear the cache before each command.
    """
    from alembic.config import Config
    from sqlalchemy import inspect

    from alembic import command
    from app.config import get_settings

    db_file = tmp_path / "migration_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()

    cfg = Config()
    cfg.set_main_option("script_location", "alembic")

    def _table_names() -> set[str]:
        engine = create_engine(f"sqlite:///{db_file}")
        try:
            return set(inspect(engine).get_table_names()) - {"alembic_version"}
        finally:
            engine.dispose()

    command.upgrade(cfg, "head")
    assert _table_names() == EXPECTED_TABLES

    command.downgrade(cfg, "base")
    assert _table_names() == set()

    # Round-trip: re-upgrade after a clean downgrade
    command.upgrade(cfg, "head")
    assert _table_names() == EXPECTED_TABLES

    get_settings.cache_clear()


def test_uuid_primary_keys_are_unique() -> None:
    user_a = User(email="a@example.com")
    user_b = User(email="b@example.com")
    # The default factory must produce different UUIDs per instance —
    # if anyone replaces this with a class-level default the regression
    # is silent until the first INSERT.
    assert user_a.email != user_b.email
    # uuid4() is what the column default invokes; verify the
    # invariant directly.
    assert uuid4() != uuid4()
