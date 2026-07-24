"""Plain result types returned by :mod:`blast_radius.datahub_client`.

These are deliberately dumb data holders — no DataHub SDK types leak past the
client boundary, so the severity and comment layers depend only on this module.
"""

from __future__ import annotations

from dataclasses import dataclass

# Lineage/entity categories we treat as user-facing "consumers" in a blast radius.
CONSUMER_TYPES = frozenset({"DASHBOARD", "CHART"})


@dataclass(frozen=True)
class LineageNode:
    """A single entity reachable downstream of a changed dataset."""

    urn: str
    entity_type: str  # DATASET | CHART | DASHBOARD | DATA_JOB | ...
    degree: int       # hop distance from the source (1 = direct downstream)
    name: str | None = None

    @property
    def is_consumer(self) -> bool:
        return self.entity_type in CONSUMER_TYPES

    @property
    def label(self) -> str:
        return self.name or self.urn


@dataclass(frozen=True)
class Owner:
    """A registered owner of an affected asset (who to notify)."""

    urn: str
    kind: str  # "corpuser" | "corpGroup"
    name: str | None = None
    email: str | None = None

    @property
    def mention(self) -> str:
        """Best available human handle for a PR @mention / notification."""
        return self.name or self.email or self.urn.split(":")[-1]


@dataclass(frozen=True)
class QueryRef:
    """A production query and the dataset/columns it reads.

    ``columns`` holds ``(dataset_urn, column)`` pairs so a single query that
    joins several tables maps cleanly onto whichever table/column changed.
    """

    urn: str
    name: str | None
    description: str | None
    sql: str | None
    author: str | None
    datasets: frozenset[str]
    columns: frozenset[tuple[str, str]]

    def references_dataset(self, dataset_urn: str) -> bool:
        return dataset_urn in self.datasets

    def references_column(self, dataset_urn: str, column: str) -> bool:
        return (dataset_urn, column) in self.columns


@dataclass(frozen=True)
class Usage:
    """Aggregated usage statistics for a dataset (latest daily bucket)."""

    dataset_urn: str
    unique_users: int
    total_queries: int
    top_queries: tuple[str, ...]
    #: (user_urn, count, email) sorted by count desc.
    user_counts: tuple[tuple[str, int, str | None], ...]
    #: column -> query count in the window.
    field_counts: dict[str, int]

    def field_query_count(self, column: str) -> int:
        return self.field_counts.get(column, 0)

    @property
    def top_user(self) -> tuple[str, int, str | None] | None:
        return self.user_counts[0] if self.user_counts else None
