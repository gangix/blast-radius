from __future__ import annotations

import blast_radius.agent_context as ac
from blast_radius.agent_context import AgentContextClient, _nodes_from_lineage
from blast_radius.config import DataHubConfig

LINEAGE = {"downstreams": {"total": 2, "searchResults": [
    {"entity": {"urn": "urn:li:dashboard:(tableau,d0)", "type": "DASHBOARD", "name": "Revenue",
                "platform": {"name": "tableau"}}, "degree": 3},
    {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,x.order_details,PROD)", "type": "DATASET",
                "name": "order_details", "platform": {"name": "dbt"}}, "degree": 1},
], "hasMore": False}}


def test_nodes_from_lineage_maps_search_results():
    nodes = _nodes_from_lineage(LINEAGE)
    assert [n.entity_type for n in nodes] == ["DASHBOARD", "DATASET"]
    assert nodes[0].urn == "urn:li:dashboard:(tableau,d0)" and nodes[0].name == "Revenue" and nodes[0].degree == 3


def test_nodes_from_lineage_empty_safe():
    assert _nodes_from_lineage({}) == [] and _nodes_from_lineage({"downstreams": {}}) == []


def _client(monkeypatch):
    # DataHubContext just sets a contextvar; a dummy client is fine since tool fns are patched.
    monkeypatch.setattr(ac, "DataHubContext", lambda c: __import__("contextlib").nullcontext())
    return AgentContextClient(DataHubConfig(), client=object())


def test_downstream_routes_through_kit(monkeypatch):
    monkeypatch.setattr(ac, "get_lineage", lambda urn, **k: LINEAGE)
    nodes = _client(monkeypatch).downstream("urn:li:dataset:(x,y,PROD)")
    assert [n.entity_type for n in nodes] == ["DASHBOARD", "DATASET"]


def test_write_assessment_calls_save_document(monkeypatch):
    calls = {}
    monkeypatch.setattr(ac, "save_document",
                        lambda **k: (calls.update(k), {"success": True, "urn": "urn:li:document:1"})[1])
    urn = _client(monkeypatch).write_assessment("urn:li:dataset:(x,y,PROD)", title="T", body_md="B",
                                                related_assets=["urn:li:chart:c"])
    assert urn == "urn:li:document:1"
    assert calls["title"] == "T" and calls["urn"] == "urn:li:dataset:(x,y,PROD)" \
        and calls["related_assets"] == ["urn:li:chart:c"]


def test_tag_change_calls_add_tags(monkeypatch):
    calls = {}
    monkeypatch.setattr(ac, "add_tags", lambda **k: (calls.update(k), {"success": True})[1])
    _client(monkeypatch).tag_change("urn:li:dataset:(x,y,PROD)", ["discount_amount"], "urn:li:tag:blast-radius-breaking")
    assert calls["tag_urns"] == ["urn:li:tag:blast-radius-breaking"]
    assert calls["entity_urns"] == ["urn:li:dataset:(x,y,PROD)"] and calls["column_paths"] == ["discount_amount"]


def test_ensure_tag_emits_when_absent(monkeypatch):
    emitted = []
    class G:
        def exists(self, urn): return False
        def emit(self, mcp): emitted.append(mcp)
    monkeypatch.setattr(ac, "get_graph", lambda: G())
    _client(monkeypatch).ensure_tag("urn:li:tag:blast-radius-breaking", name="blast-radius-breaking", description="d")
    assert len(emitted) == 1
