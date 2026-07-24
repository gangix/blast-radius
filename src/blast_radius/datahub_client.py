"""The only place that talks to DataHub — the deterministic source of truth.

Every downstream-impact fact the agent reports originates here: lineage
traversal, which queries read which columns, usage statistics, and ownership.
There is no LLM in this module and no inference; if it isn't in the graph, we
do not claim it. The generation layer only phrases what these methods return.

All methods are read-only. URNs are built via :class:`DataHubConfig` so the
same code works against the local quickstart or the hosted judging instance.
"""

from __future__ import annotations

from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph
from datahub.metadata.schema_classes import (
    CorpUserInfoClass,
    DatasetUsageStatisticsClass,
    OwnershipClass,
    QueryPropertiesClass,
    QuerySubjectsClass,
)

from .config import DataHubConfig
from .models import LineageNode, Owner, QueryRef, Usage

# Downstream lineage in one call, resolving display names inline to avoid a
# round-trip per node. skipCache so a freshly-ingested graph reflects reality.
_DOWNSTREAM_GQL = """
query blastRadius($urn: String!, $count: Int!) {
  searchAcrossLineage(input: {
    urn: $urn, direction: DOWNSTREAM, count: $count,
    query: "*", searchFlags: { skipCache: true }
  }) {
    total
    searchResults {
      degree
      entity {
        urn
        type
        ... on Dataset   { name properties { name } }
        ... on Chart     { properties { name } }
        ... on Dashboard { properties { name } }
        ... on DataJob   { properties { name } }
      }
    }
  }
}
"""

_SCHEMA_FIELD_PREFIX = "urn:li:schemaField:("


class DataHubClient:
    """Thin, typed read facade over DataHub for impact analysis."""

    def __init__(self, config: DataHubConfig | None = None) -> None:
        self.config = config or DataHubConfig.from_env()
        self.graph = DataHubGraph(
            DatahubClientConfig(server=self.config.server, token=self.config.token)
        )
        self._query_index: list[QueryRef] | None = None
        self._name_cache: dict[str, str | None] = {}

    # ------------------------------------------------------------------ URNs
    def dataset_urn(self, table: str) -> str:
        """Build a dataset URN from a ``db.schema.table`` name."""
        name = self.config.qualify(table)
        return (
            f"urn:li:dataset:(urn:li:dataPlatform:{self.config.platform},"
            f"{name},{self.config.fabric})"
        )

    @staticmethod
    def field_urn(dataset_urn: str, column: str) -> str:
        return f"{_SCHEMA_FIELD_PREFIX}{dataset_urn},{column})"

    @staticmethod
    def parse_schema_field(sf_urn: str) -> tuple[str, str] | None:
        """Split a schemaField URN into ``(dataset_urn, column)``.

        The dataset URN itself contains commas, but the column never does, so
        the final comma is the separator.
        """
        if not sf_urn.startswith(_SCHEMA_FIELD_PREFIX):
            return None
        inner = sf_urn[len(_SCHEMA_FIELD_PREFIX):-1]  # strip wrapper "(" .. ")"
        dataset_urn, _, column = inner.rpartition(",")
        return (dataset_urn, column) if dataset_urn and column else None

    def exists(self, urn: str) -> bool:
        return self.graph.exists(urn)

    def dataset_urns(self) -> list[str]:
        """Every dataset URN in the catalogue (used to resolve names to URNs)."""
        return list(self.graph.get_urns_by_filter(entity_types=["dataset"]))

    # -------------------------------------------------------------- lineage
    def downstream(self, urn: str, *, count: int = 500) -> list[LineageNode]:
        """All entities reachable downstream of ``urn`` (the blast radius).

        Excludes the source itself. Sorted by hop distance then type so the
        nearest, most concrete impact reads first.
        """
        res = self.graph.execute_graphql(_DOWNSTREAM_GQL, variables={"urn": urn, "count": count})
        nodes: list[LineageNode] = []
        for r in res["searchAcrossLineage"]["searchResults"]:
            entity = r["entity"]
            if entity["urn"] == urn:
                continue
            nodes.append(
                LineageNode(
                    urn=entity["urn"],
                    entity_type=entity.get("type", "UNKNOWN"),
                    degree=r.get("degree", 0),
                    name=self._entity_name(entity),
                )
            )
        nodes.sort(key=lambda n: (n.degree, n.entity_type, n.label))
        return nodes

    # -------------------------------------------------------------- queries
    def query_index(self, *, refresh: bool = False) -> list[QueryRef]:
        """All query entities with their dataset/column subjects, cached.

        The reverse ``dataset <- query`` edge is not graph-indexed in the OSS
        build, so we scan query entities once and index in memory. Fine at
        catalogue scale; swap for GraphQL ``listQueries`` if it ever isn't.
        """
        if self._query_index is not None and not refresh:
            return self._query_index

        index: list[QueryRef] = []
        for q_urn in self.graph.get_urns_by_filter(entity_types=["query"]):
            props = self.graph.get_aspect(entity_urn=q_urn, aspect_type=QueryPropertiesClass)
            subjects = self.graph.get_aspect(entity_urn=q_urn, aspect_type=QuerySubjectsClass)

            datasets: set[str] = set()
            columns: set[tuple[str, str]] = set()
            for subj in (subjects.subjects if subjects else []):
                entity = subj.entity
                if entity.startswith("urn:li:dataset:"):
                    datasets.add(entity)
                else:
                    parsed = self.parse_schema_field(entity)
                    if parsed:
                        columns.add(parsed)
                        datasets.add(parsed[0])

            index.append(
                QueryRef(
                    urn=q_urn,
                    name=props.name if props else None,
                    description=props.description if props else None,
                    sql=props.statement.value if props and props.statement else None,
                    author=props.created.actor if props and props.created else None,
                    datasets=frozenset(datasets),
                    columns=frozenset(columns),
                )
            )
        self._query_index = index
        return index

    def queries_for_dataset(self, dataset_urn: str) -> list[QueryRef]:
        return [q for q in self.query_index() if q.references_dataset(dataset_urn)]

    def queries_for_column(self, dataset_urn: str, column: str) -> list[QueryRef]:
        """Production queries that read a specific column (what a drop breaks)."""
        return [q for q in self.query_index() if q.references_column(dataset_urn, column)]

    # ---------------------------------------------------------------- usage
    def usage(self, dataset_urn: str) -> Usage | None:
        """Latest daily usage bucket for a dataset (per-user + per-field)."""
        stats = self.graph.get_latest_timeseries_value(
            entity_urn=dataset_urn,
            aspect_type=DatasetUsageStatisticsClass,
            filter_criteria_map={},
        )
        if stats is None:
            return None
        user_counts = tuple(
            (uc.user, uc.count, uc.userEmail) for uc in (stats.userCounts or [])
        )
        return Usage(
            dataset_urn=dataset_urn,
            unique_users=stats.uniqueUserCount or 0,
            total_queries=stats.totalSqlQueries or 0,
            top_queries=tuple(stats.topSqlQueries or []),
            user_counts=user_counts,
            field_counts={fc.fieldPath: fc.count for fc in (stats.fieldCounts or [])},
        )

    # ------------------------------------------------------------ ownership
    def owners(self, urn: str) -> list[Owner]:
        ownership = self.graph.get_aspect(entity_urn=urn, aspect_type=OwnershipClass)
        if not ownership:
            return []
        out: list[Owner] = []
        for owner in ownership.owners:
            owner_urn = owner.owner
            kind = "corpGroup" if ":corpGroup:" in owner_urn else "corpuser"
            name = email = None
            if kind == "corpuser":
                info = self.graph.get_aspect(entity_urn=owner_urn, aspect_type=CorpUserInfoClass)
                if info:
                    name, email = info.displayName, info.email
            out.append(Owner(urn=owner_urn, kind=kind, name=name, email=email))
        return out

    # -------------------------------------------------------------- helpers
    def _entity_name(self, entity: dict) -> str | None:
        urn = entity["urn"]
        if urn in self._name_cache:
            return self._name_cache[urn]
        props = entity.get("properties") or {}
        name = props.get("name") or entity.get("name")
        self._name_cache[urn] = name
        return name
