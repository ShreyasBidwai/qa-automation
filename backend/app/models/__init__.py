"""ORM models. Importing them here registers every table on ``Base.metadata``
so Alembic autogenerate and ``verify_migrations`` see the full schema.
"""

from __future__ import annotations

from .auth_challenge_log import AuthChallengeLog
from .base import Base
from .coverage import Coverage
from .document_chunk import DocumentChunk
from .finding import Finding
from .finding_result import FindingResult
from .finding_triage import FindingTriage
from .incident import Incident
from .job import Job
from .model_edge import ModelEdge
from .model_node import ModelNode
from .organization import Organization
from .organization_invite import OrganizationInvite
from .organization_member import OrganizationMember
from .password_reset_token import PasswordResetToken
from .project import Project
from .project_document import ProjectDocument
from .result import Result
from .run import Run
from .spec_divergence import SpecDivergence
from .test_case import TestCase
from .test_heal import TestHeal
from .test_script import TestScript
from .user import User
from .user_session import UserSession

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
    "FindingResult",
    "FindingTriage",
    "User",
    "UserSession",
    "PasswordResetToken",
    "Organization",
    "OrganizationMember",
    "OrganizationInvite",
    "Job",
    "ProjectDocument",
    "DocumentChunk",
    "SpecDivergence",
    "TestHeal",
    "Incident",
]
