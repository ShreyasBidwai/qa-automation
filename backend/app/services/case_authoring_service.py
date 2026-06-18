"""CaseAuthoringService — Mode A: a human authors a case from scratch.

Creates a brand-new lineage at version 1 (current), ``origin="authored"`` and
``edited_by_human=true``, carrying the standard case fields and a human-set
oracle. Because the case is human-edited from birth, the merge engine's
clobber-protection (T3.2) already covers it: a later re-generation matching its
``case_key`` can only ever propose, never overwrite. Authored cases are ordinary
versioned cases — a later change goes through the existing T3.1 edit path
(append-only history), so there is no parallel case model.

The case's Pest script is rendered deterministic-first: a simple case from a
pure template (no AI), a complex one via the T1.4 AI render (see
[[app/generation/authored.py]]). Repositories do the writes (Standards §5).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.types import AIProvider
from app.generation.authored import (
    AuthoredCaseSpec,
    compute_authored_case_key,
    render_authored_script,
)
from app.models.enums import AuthoredBy, CaseOrigin, Framework
from app.models.test_case import TestCase
from app.models.test_script import TestScript
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_script_repository import TestScriptRepository

from .errors import InvalidCaseSpecError

logger = logging.getLogger("app.case_authoring")

# Provenance recorded in ``generated_by`` for the no-AI template path.
_TEMPLATE_GENERATED_BY = "template"


@dataclass(frozen=True)
class AuthoredCase:
    """The result of authoring: the new v1 case and its rendered script."""

    test_case: TestCase
    test_script: TestScript


class CaseAuthoringService:
    """Author human-written test cases (Mode A). All operations project-scoped."""

    def __init__(
        self, session: AsyncSession, *, provider: AIProvider, budget_tokens: int
    ) -> None:
        self._session = session
        self._repo = TestCaseRepository(session)
        self._script_repo = TestScriptRepository(session)
        self._provider = provider
        self._budget = budget_tokens

    async def create_case(
        self,
        project_id: uuid.UUID,
        spec: AuthoredCaseSpec,
        authored_by: str,
    ) -> AuthoredCase:
        """Create a new human-authored case (a fresh lineage, v1, current).

        The case is ``origin="authored"``, ``edited_by_human=true`` with full
        provenance (``authored_by=human``, the author in ``edited_by``, and the
        row's ``created_at`` as the timestamp). Its ``case_key`` is computed when
        the case targets a known endpoint+type (so re-generation recognizes it),
        else null (free-form). Its Pest script is rendered deterministic-first.

        Raises ``InvalidCaseSpecError`` if the spec is malformed.
        """
        _validate(spec)

        case = TestCase(
            project_id=project_id,
            type=spec.type,
            layer=spec.layer,
            target_node=None,
            preconditions={
                "endpoint": {
                    "method": spec.endpoint.method,
                    "uri": spec.endpoint.uri,
                    "route_name": spec.endpoint.route_name,
                },
                "auth_required": spec.auth_required,
                "db_dependencies": [asdict(dep) for dep in spec.db_setup],
            },
            steps={
                "method": spec.endpoint.method,
                "uri": spec.endpoint.uri,
                "path_values": spec.path_values,
                "authenticated": spec.authenticated,
                "payload": spec.payload,
                "case": spec.name,
                "rule": spec.rule,
            },
            expected={"status": spec.expected_status, "shape": spec.expected_shape},
            oracle_source=spec.oracle_source,
            # Provenance: human-authored from scratch. authored_by(enum)=human and
            # edited_by_human=true so the merge engine treats it as a human edit;
            # the author identity goes in edited_by, the timestamp is created_at.
            authored_by=AuthoredBy.HUMAN,
            edited_by_human=True,
            edited_by=authored_by,
            origin=CaseOrigin.AUTHORED,
            requirement_link=spec.requirement_link,
            case_key=compute_authored_case_key(spec),
            is_current=True,
        )
        await self._repo.add(case)
        # Make server-defaulted columns (version, lineage_id, created_at) concrete.
        await self._session.refresh(case)

        code, deterministic = render_authored_script(self._provider, spec, self._budget)
        script = await self._script_repo.add(
            TestScript(
                project_id=project_id,
                test_case_id=case.id,
                framework=Framework.PEST,
                code=code,
                generated_by=(
                    _TEMPLATE_GENERATED_BY if deterministic else self._generated_by()
                ),
                deterministic=deterministic,
            )
        )

        logger.info(
            "case.authored",
            extra={
                "project_id": str(project_id),
                "lineage_id": str(case.lineage_id),
                "case_key": case.case_key,
                "authored_by": authored_by,
                "deterministic_script": deterministic,
            },
        )
        return AuthoredCase(test_case=case, test_script=script)

    def _generated_by(self) -> str:
        """Identity recorded for an AI-rendered script (the provider class)."""
        return type(self._provider).__name__


def _validate(spec: AuthoredCaseSpec) -> None:
    if not spec.name.strip():
        raise InvalidCaseSpecError("authored case requires a name")
    if not spec.endpoint.method.strip():
        raise InvalidCaseSpecError("authored case requires an HTTP method")
    if not spec.endpoint.uri.strip():
        raise InvalidCaseSpecError("authored case requires a URI")
    if not 100 <= spec.expected_status <= 599:
        raise InvalidCaseSpecError(
            f"expected_status {spec.expected_status} is out of HTTP range"
        )
