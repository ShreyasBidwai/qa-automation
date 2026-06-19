"""ORM models. Importing them here registers every table on ``Base.metadata``
so Alembic autogenerate and ``verify_migrations`` see the full schema.
"""

from __future__ import annotations

from .auth_challenge_log import AuthChallengeLog
from .base import Base
from .coverage import Coverage
from .finding import Finding
from .model_edge import ModelEdge
from .model_node import ModelNode
from .project import Project
from .result import Result
from .run import Run
from .test_case import TestCase
from .test_script import TestScript

__all__ = [
    "Base",
    "Project",
    "Run",
    "Result",
    "TestCase",
    "TestScript",
    "Coverage",
    "ModelNode",
    "ModelEdge",
    "AuthChallengeLog",
    "Finding",
]
