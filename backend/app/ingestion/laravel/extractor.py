"""LaravelExtractor — deterministic, single-endpoint EndpointSpec extraction.

The focused seed of `LaravelAdapter` (TRD §5): given a local Laravel repo and a
route target, produce one normalized `EndpointSpec`. No git provider, no
app-wide crawl, no AI (Sprint 2 generalizes to the whole-app NormalizedModel).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from app.ingestion.commands import CommandResult, check_output, run_subprocess
from app.ingestion.errors import ActionResolutionError
from app.ingestion.models import EndpointSpec

from .normalize import normalize_rules
from .route_list import (
    RouteFacts,
    RouteTarget,
    path_params_from_uri,
    route_facts_from_output,
)
from .validation import extract_validation

logger = logging.getLogger("app.ingestion.laravel")

_HELPER_SCRIPT = str(Path(__file__).parent / "php" / "extract_validation.php")

CommandRunner = Callable[[Sequence[str], "str | None", float], CommandResult]


class LaravelExtractor:
    def __init__(
        self,
        *,
        runner: CommandRunner = run_subprocess,
        php_path: str = "php",
        artisan_timeout: float = 60.0,
        php_timeout: float = 30.0,
        helper_script: str = _HELPER_SCRIPT,
    ) -> None:
        self._runner = runner
        self._php = php_path
        self._artisan_timeout = artisan_timeout
        self._php_timeout = php_timeout
        self._helper = helper_script

    def extract_endpoint(self, repo_path: str, target: RouteTarget) -> EndpointSpec:
        facts = self._route_facts(repo_path, target)
        controller_fqcn, action = self._resolve_action(facts.action)
        extraction = extract_validation(
            repo_path=repo_path,
            controller_fqcn=controller_fqcn,
            action=action,
            runner=self._runner,
            php_path=self._php,
            helper_script=self._helper,
            timeout=self._php_timeout,
        )
        logger.info(
            "ingestion.laravel.extracted",
            extra={
                "method": facts.method,
                "uri": facts.uri,
                "auth_required": facts.auth_required,
                "validation_source": extraction.source,
                "field_count": len(extraction.rules),
            },
        )
        return EndpointSpec(
            method=facts.method,
            uri=facts.uri,
            route_name=facts.name,
            auth_required=facts.auth_required,
            path_params=path_params_from_uri(facts.uri),
            query_params=[],
            validation_fields=normalize_rules(extraction.rules),
        )

    def _route_facts(self, repo_path: str, target: RouteTarget) -> RouteFacts:
        result = self._runner(
            [self._php, "artisan", "route:list", "--json"],
            repo_path,
            self._artisan_timeout,
        )
        stdout = check_output(result, what="artisan route:list")
        return route_facts_from_output(stdout, target)

    @staticmethod
    def _resolve_action(action: str) -> tuple[str, str]:
        if "@" not in action:
            raise ActionResolutionError(
                f"route action {action!r} is not a Controller@method"
            )
        controller, _, method = action.partition("@")
        if not controller or not method:
            raise ActionResolutionError(f"unparseable route action {action!r}")
        return controller, method
