"""Resolve a diff's table/model names to real DataHub dataset URNs.

This is the seam between :mod:`blast_radius.diff_parser` (which emits table
names *as written in code* — a 2-part ``schema.table``, a fully-qualified
``db.schema.table``, or a bare dbt model stem, in whatever case the author
used) and :mod:`blast_radius.datahub_client` (which needs an exact URN).

Resolution is deterministic and grounded in the catalogue: we do not guess a
URN and hope it exists — we match the name against the set of dataset URNs that
*actually* exist in DataHub, by trailing-segment match, case-insensitively, and
rank candidates by platform so a warehouse table wins over its BI copy. If
nothing matches, we return ``None`` rather than inventing an entity.

The matching core (:func:`match_table`) is a pure function over a list of
catalogue entries, so it is unit-testable without a live DataHub.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import DataHubConfig
from .datahub_client import DataHubClient
from .diff_parser import Change

# Platform preference when a name matches datasets on several platforms. The
# changed thing is a source table/model, so physical warehouses win; its dbt
# model is next; BI datasets (Looker/Tableau) are downstream *consumers*, not
# the changed table, so they rank last.
_WAREHOUSE = frozenset(
    {"snowflake", "bigquery", "redshift", "postgres", "mysql", "databricks",
     "hive", "athena", "clickhouse", "oracle", "mssql", "trino", "presto"}
)
_TRANSFORM = frozenset({"dbt"})
_BI = frozenset({"looker", "tableau", "powerbi", "mode", "superset", "metabase", "quicksight"})
_STORAGE = frozenset({"s3", "gcs", "abs", "hdfs", "file"})


def _platform_rank(platform: str, prefer: str | None) -> int:
    if prefer and platform == prefer:
        return -1
    if platform in _WAREHOUSE:
        return 0
    if platform in _TRANSFORM:
        return 1
    if platform in _BI:
        return 3
    if platform in _STORAGE:
        return 4
    return 2


@dataclass(frozen=True)
class _Entry:
    """A catalogue dataset, parsed for matching."""

    urn: str
    platform: str
    segments: tuple[str, ...]  # name segments, prefix-stripped, lower-cased


@dataclass(frozen=True)
class ResolvedTable:
    """The outcome of resolving one written name to a dataset URN."""

    raw: str                        # name as written in the diff
    urn: str                        # chosen dataset URN
    matched_name: str               # matched dataset's dotted name (prefix-stripped)
    platform: str
    score: float                    # 1.0 exact, lower for partial/ambiguous
    exact: bool
    candidates: tuple[str, ...]     # other plausible URNs (siblings / ambiguity)

    @property
    def is_confident(self) -> bool:
        return self.score >= 0.9

    @property
    def ambiguous(self) -> bool:
        return bool(self.candidates) and not self.exact


def parse_dataset_urn(urn: str) -> tuple[str, str]:
    """Return ``(platform, name)`` from a dataset URN.

    Robust to the embedded platform URN and to fabric; the name segment never
    contains a comma in practice, but we reconstruct defensively just in case.
    """
    inner = urn[len("urn:li:dataset:(") : -1]
    parts = inner.split(",")
    platform = parts[0].rsplit(":", 1)[-1]
    name = ",".join(parts[1:-1]) if len(parts) >= 3 else parts[1]
    return platform, name


def _segments(name: str, instance_prefix: str) -> tuple[str, ...]:
    """Prefix-stripped, lower-cased, dot-split segments of a dataset name."""
    n = name.strip().strip('"').lower()
    p = instance_prefix.lower()
    if p and n.startswith(f"{p}."):
        n = n[len(p) + 1 :]
    return tuple(s for s in n.split(".") if s)


def _specificity(want: tuple[str, ...], have: tuple[str, ...]) -> int:
    """How well ``want`` matches as a trailing segment run of ``have`` (0 = no)."""
    if want and len(want) <= len(have) and have[-len(want):] == want:
        return len(want)
    return 0


def _score(spec: int, want: tuple[str, ...], best: _Entry, n_matches: int) -> float:
    if spec == len(best.segments) == len(want):
        return 1.0                          # exact, full-length match
    if spec >= 2:
        return 0.9                          # qualified suffix (schema.table) — unambiguous enough
    # bare single-segment (dbt stem) match
    return 0.7 if n_matches == 1 else 0.6


def match_table(
    raw: str,
    entries: list[_Entry],
    *,
    instance_prefix: str = "",
    prefer_platform: str | None = None,
) -> ResolvedTable | None:
    """Pure matching core: best dataset for ``raw`` among ``entries``."""
    want = _segments(raw, instance_prefix)
    if not want:
        return None

    scored: list[tuple[int, int, _Entry]] = []
    for e in entries:
        spec = _specificity(want, e.segments)
        if spec:
            scored.append((spec, -_platform_rank(e.platform, prefer_platform), e))
    if not scored:
        return None

    # Highest specificity first, then most-preferred platform.
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best_spec, _, best = scored[0]
    return ResolvedTable(
        raw=raw,
        urn=best.urn,
        matched_name=".".join(best.segments),
        platform=best.platform,
        score=_score(best_spec, want, best, len(scored)),
        exact=want == best.segments,
        candidates=tuple(e.urn for _, _, e in scored[1:]),
    )


class TableResolver:
    """Resolve written table/model names to catalogue dataset URNs."""

    def __init__(self, client: DataHubClient, *, prefer_platform: str | None = None) -> None:
        self.client = client
        self.prefer_platform = prefer_platform
        self._entries: list[_Entry] | None = None

    @property
    def config(self) -> DataHubConfig:
        return self.client.config

    def entries(self, *, refresh: bool = False) -> list[_Entry]:
        if self._entries is None or refresh:
            prefix = self.config.instance_prefix
            out: list[_Entry] = []
            for urn in self.client.dataset_urns():
                platform, name = parse_dataset_urn(urn)
                out.append(_Entry(urn, platform, _segments(name, prefix)))
            self._entries = out
        return self._entries

    def resolve(self, table: str, *, prefer_platform: str | None = None) -> ResolvedTable | None:
        return match_table(
            table,
            self.entries(),
            instance_prefix=self.config.instance_prefix,
            prefer_platform=prefer_platform or self.prefer_platform,
        )

    def resolve_change(self, change: Change) -> ResolvedTable | None:
        return self.resolve(change.table)

    def resolve_all(self, changes: list[Change]) -> dict[str, ResolvedTable | None]:
        """Resolve each distinct changed table once."""
        return {t: self.resolve(t) for t in {c.table for c in changes}}
