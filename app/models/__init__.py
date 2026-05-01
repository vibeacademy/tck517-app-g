"""SQLModel database models.

Importing this package registers all five domain entities with
`SQLModel.metadata`, which is what Alembic autogenerate diffs against.

`Session` is intentionally NOT re-exported here to avoid colliding with
`sqlmodel.Session`. Import it explicitly: `from app.models.session
import Session`.
"""

from app.models import session as _session  # noqa: F401  (side-effect: register `sessions`)
from app.models.character import Character
from app.models.generation import Generation, GenerationStatus
from app.models.project import Project
from app.models.user import User

__all__ = [
    "Character",
    "Generation",
    "GenerationStatus",
    "Project",
    "User",
]
