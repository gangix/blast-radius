"""The Blast Radius orchestrator: a PR's changed files -> a posted comment.

Deterministic sequencing over the existing modules. Its one judgment beyond
wiring is choosing WHICH facts to fetch and at what SCOPE per change
(column-scoped vs table-scoped queries) — which is what makes the severity
column-vs-table rule true end to end. No LLM lives here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from .comment import CommentContext, render_comment
from .config import DataHubConfig
from .datahub_client import DataHubClient
from .diff_parser import Change, ChangeKind, DiffParser, FileChange
from .resolver import ResolvedTable, TableResolver
from .severity import Assessment, ImpactFacts, Verdict, assess, worst_verdict

_T = TypeVar("_T")

# Column-scoped edit kinds (ADD_COLUMN is additive and handled by the skip rule).
_COLUMN_KINDS = frozenset(
    {ChangeKind.DROP_COLUMN, ChangeKind.RENAME_COLUMN, ChangeKind.ALTER_COLUMN_TYPE}
)
_ADDITIVE_KINDS = frozenset({ChangeKind.ADD_COLUMN, ChangeKind.CREATE_TABLE})


class DataHubUnavailable(RuntimeError):
    """DataHub could not be reached, so no blast radius could be computed.

    Distinct from a clean review — a caller (e.g. the GitHub Action) must treat
    this as an infra failure, never as a green light.
    """


@dataclass(frozen=True)
class Report:
    assessments: list[Assessment]
    verdict: Verdict
    markdown: str
    warnings: list[str] = field(default_factory=list)


class BlastRadiusAgent:
    """Runs the full pipeline: changed files -> verdict + comment + warnings."""

    def __init__(
        self,
        client: DataHubClient | None = None,
        *,
        config: DataHubConfig | None = None,
        comment_ctx: CommentContext | None = None,
        prefer_platform: str | None = None,
    ) -> None:
        self.config = config or DataHubConfig.from_env()
        self.client = client or DataHubClient(self.config)
        self.resolver = TableResolver(self.client, prefer_platform=prefer_platform)
        self.comment_ctx = comment_ctx
        self.diff_parser = DiffParser()

    # -- fact gathering ---------------------------------------------------- #
    def gather(
        self,
        change: Change,
        resolved: ResolvedTable | None,
        *,
        cache: dict | None = None,
        warnings: list[str] | None = None,
    ) -> ImpactFacts:
        facts = ImpactFacts(change=change, resolved=resolved)
        # No blast radius to compute for an unresolved table or an additive change.
        if resolved is None or change.kind in _ADDITIVE_KINDS:
            return facts

        cache = {} if cache is None else cache
        warnings = [] if warnings is None else warnings
        urn = resolved.urn

        facts.downstream = self._memo(cache, "downstream", urn,
                                      lambda: self.client.downstream(urn), [], change, warnings)
        facts.usage = self._memo(cache, "usage", urn,
                                 lambda: self.client.usage(urn), None, change, warnings)
        facts.owners = self._memo(cache, "owners", urn,
                                  lambda: self.client.owners(urn), [], change, warnings)

        if change.kind in _COLUMN_KINDS:
            def fetch_q() -> list:
                return self.client.queries_for_column(urn, change.column)
        else:
            def fetch_q() -> list:
                return self.client.queries_for_dataset(urn)
        facts.breaking_queries = self._safe(fetch_q, [], "queries", change, warnings)
        return facts

    @staticmethod
    def _safe(fn: Callable[[], _T], default: _T, label: str,
              change: Change, warnings: list[str]) -> _T:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - degrade a fetch, never abort a review
            warnings.append(f"{label} fetch failed for {change.table}: {exc}")
            return default

    def _memo(self, cache: dict, kind: str, urn: str, fn: Callable[[], _T],
              default: _T, change: Change, warnings: list[str]) -> _T:
        key = (kind, urn)
        if key not in cache:
            cache[key] = self._safe(fn, default, kind, change, warnings)
        return cache[key]

    # -- orchestration ----------------------------------------------------- #
    def review(self, file_changes: list[FileChange]) -> Report:
        changes = self.diff_parser.parse(file_changes)
        assessments, warnings = self.assess_changes(changes)
        markdown = render_comment(assessments, ctx=self.comment_ctx)
        return Report(
            assessments=assessments,
            verdict=worst_verdict(assessments),
            markdown=markdown,
            warnings=warnings,
        )

    def assess_changes(self, changes: list[Change]) -> tuple[list[Assessment], list[str]]:
        resolved_map = self._resolve_all(changes)
        cache: dict = {}
        warnings: list[str] = []
        assessments = [
            assess(self.gather(c, resolved_map.get(c.table), cache=cache, warnings=warnings))
            for c in changes
        ]
        return assessments, warnings

    def _resolve_all(self, changes: list[Change]) -> dict[str, ResolvedTable | None]:
        try:
            return self.resolver.resolve_all(changes)
        except Exception as exc:  # resolution is our first DataHub touch -> total outage
            raise DataHubUnavailable(
                f"Could not reach DataHub to resolve tables: {exc}"
            ) from exc
