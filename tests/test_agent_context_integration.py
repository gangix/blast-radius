from __future__ import annotations

import pytest

from blast_radius.agent_context import AgentContextClient
from blast_radius.config import DataHubConfig
from blast_radius.datahub_client import DataHubClient
from blast_radius.resolver import TableResolver

DEMO_TAG = "urn:li:tag:blast-radius-spike-test"


@pytest.mark.integration
def test_writeback_roundtrip_live():
    """Write a doc + tag to live DataHub via the Agent Context Kit, then clean up. Skips if down."""
    cfg = DataHubConfig.from_env()
    try:
        od = TableResolver(DataHubClient(cfg)).resolve("analytics.order_details")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DataHub not reachable: {exc}")
    if od is None:
        pytest.skip("demo data not seeded")

    ac = AgentContextClient(cfg)
    # read via the Kit
    nodes = ac.downstream(od.urn)
    assert isinstance(nodes, list)
    # write via the Kit
    ac.ensure_tag(DEMO_TAG, name="blast-radius-spike-test", description="integration test tag")
    doc_urn = ac.write_assessment(od.urn, title="Blast Radius — integration test",
                                  body_md="test body", related_assets=[])
    assert doc_urn
    # cleanup so no residue
    from datahub_agent_context.context import DataHubContext, get_graph
    from datahub_agent_context.mcp_tools.tags import remove_tags
    with DataHubContext(ac._client):
        remove_tags(tag_urns=[DEMO_TAG], entity_urns=[od.urn], column_paths=None)
        get_graph().soft_delete_entity(doc_urn) if hasattr(get_graph(), "soft_delete_entity") else None
