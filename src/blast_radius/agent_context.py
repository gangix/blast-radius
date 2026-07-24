"""The only module that talks to DataHub via the Agent Context Kit.

Mirrors `datahub_client.py`'s boundary role: `datahub_agent_context` and
`datahub.sdk.DataHubClient` are imported ONLY here, and callers see our `models`
types. Provides a Kit-routed lineage read and the write-back operations
(knowledge doc + governance tag).
"""

from __future__ import annotations

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import TagPropertiesClass
from datahub.sdk import DataHubClient as _SdkClient
from datahub_agent_context.context import DataHubContext, get_graph
from datahub_agent_context.mcp_tools.lineage import get_lineage
from datahub_agent_context.mcp_tools.save_document import save_document
from datahub_agent_context.mcp_tools.tags import add_tags

from .config import DataHubConfig
from .models import LineageNode


class AgentContextError(RuntimeError):
    """A DataHub Agent Context Kit call failed."""


def _nodes_from_lineage(payload: dict) -> list[LineageNode]:
    results = ((payload or {}).get("downstreams") or {}).get("searchResults") or []
    nodes: list[LineageNode] = []
    for r in results:
        ent = r.get("entity") or {}
        urn = ent.get("urn")
        if not urn:
            continue
        nodes.append(LineageNode(urn=urn, entity_type=ent.get("type", "UNKNOWN"),
                                 degree=r.get("degree", 0), name=ent.get("name")))
    return nodes


class AgentContextClient:
    def __init__(self, config: DataHubConfig, *, client=None) -> None:
        self.config = config
        self._client = client or _SdkClient(server=config.server, token=config.token)

    def _ctx(self):
        return DataHubContext(self._client)

    # -- read (routed through the Agent Context Kit) --
    def downstream(self, urn: str, *, max_hops: int = 3,
                   max_results: int = 100) -> list[LineageNode]:
        try:
            with self._ctx():
                payload = get_lineage(urn, upstream=False, max_hops=max_hops,
                                      max_results=max_results)
            return _nodes_from_lineage(payload)
        except Exception as exc:
            raise AgentContextError(f"get_lineage failed for {urn}: {exc}") from exc

    # -- write-back --
    def ensure_tag(self, tag_urn: str, *, name: str, description: str) -> None:
        with self._ctx():
            graph = get_graph()
            if graph.exists(tag_urn):
                return
            graph.emit(MetadataChangeProposalWrapper(
                entityUrn=tag_urn,
                aspect=TagPropertiesClass(name=name, description=description)))

    def write_assessment(self, dataset_urn: str, *, title: str, body_md: str,
                         related_assets: list[str]) -> str | None:
        with self._ctx():
            res = save_document(document_type="Analysis", title=title,
                                content=body_md,
                                related_assets=[dataset_urn, *related_assets])
        if not res.get("success"):
            raise AgentContextError(f"save_document failed: {res.get('message')}")
        return res.get("urn")

    def tag_change(self, dataset_urn: str, columns: list[str],
                   tag_urn: str) -> list[str]:
        with self._ctx():
            add_tags(tag_urns=[tag_urn],
                     entity_urns=[dataset_urn] * len(columns),
                     column_paths=list(columns))
        return list(columns)
