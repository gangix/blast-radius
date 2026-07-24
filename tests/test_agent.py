from __future__ import annotations

import pytest

from blast_radius import (
    Change,
    ChangeKind,
    FileChange,
    FileStatus,
    LineageNode,
    Owner,
    QueryRef,
    ResolvedTable,
    Usage,
    Verdict,
)
from blast_radius.agent import BlastRadiusAgent, DataHubUnavailable
from blast_radius.config import DataHubConfig

DS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.analytics.order_details,PROD)"


class FakeClient:
    """Records calls; returns canned data; can be told to fail specific methods."""

    def __init__(self, *, urns=(DS,), downstream=None, usage=None, owners=None,
                 q_col=None, q_ds=None, fail=()):
        self.config = DataHubConfig(instance_prefix="b2fd91", platform="snowflake", fabric="PROD")
        self._urns = list(urns)
        self._downstream = downstream or {}
        self._usage = usage or {}
        self._owners = owners or {}
        self._q_col = q_col or {}
        self._q_ds = q_ds or {}
        self._fail = set(fail)
        self.calls: list[tuple] = []

    def _rec(self, name, *args):
        self.calls.append((name, *args))
        if name in self._fail:
            raise RuntimeError(f"boom:{name}")

    def dataset_urns(self):
        self._rec("dataset_urns")
        return list(self._urns)

    def downstream(self, urn):
        self._rec("downstream", urn)
        return self._downstream.get(urn, [])

    def usage(self, urn):
        self._rec("usage", urn)
        return self._usage.get(urn)

    def owners(self, urn):
        self._rec("owners", urn)
        return self._owners.get(urn, [])

    def queries_for_column(self, urn, column):
        self._rec("queries_for_column", urn, column)
        return self._q_col.get((urn, column), [])

    def queries_for_dataset(self, urn):
        self._rec("queries_for_dataset", urn)
        return self._q_ds.get(urn, [])


def resolved(name="analytics.order_details"):
    return ResolvedTable(raw=name, urn=DS, matched_name=name, platform="snowflake",
                         score=1.0, exact=True, candidates=())


def dashboards(n):
    return [LineageNode(f"urn:li:dashboard:(tableau,d{i})", "DASHBOARD", 3, f"Dashboard {i}")
            for i in range(n)]


def qref(name):
    return QueryRef(urn=f"urn:li:query:{name}", name=name, description="", sql="SELECT 1",
                    author="sarah", datasets=frozenset({DS}), columns=frozenset())


def test_gather_column_change_fetches_column_scoped_queries():
    fc = FakeClient(q_col={(DS, "discount_amount"): [qref("q1")]})
    agent = BlastRadiusAgent(client=fc)
    facts = agent.gather(Change(ChangeKind.DROP_COLUMN, "analytics.order_details",
                                column="discount_amount"), resolved())
    assert [q.name for q in facts.breaking_queries] == ["q1"]
    called = {c[0] for c in fc.calls}
    assert "queries_for_column" in called and "queries_for_dataset" not in called


def test_gather_table_change_fetches_dataset_scoped_queries():
    fc = FakeClient(q_ds={DS: [qref("q1"), qref("q2")]})
    agent = BlastRadiusAgent(client=fc)
    facts = agent.gather(Change(ChangeKind.DROP_TABLE, "analytics.order_details"), resolved())
    assert len(facts.breaking_queries) == 2
    called = {c[0] for c in fc.calls}
    assert "queries_for_dataset" in called and "queries_for_column" not in called


def test_gather_unresolved_and_additive_fetch_nothing():
    fc = FakeClient()
    agent = BlastRadiusAgent(client=fc)
    agent.gather(Change(ChangeKind.DROP_COLUMN, "mystery", column="x"), None)
    agent.gather(Change(ChangeKind.ADD_COLUMN, "analytics.order_details", column="new_col"),
                 resolved())
    assert fc.calls == []  # no DataHub touched for unresolved or additive changes


def test_gather_degrades_on_fetch_failure():
    fc = FakeClient(fail={"downstream"})
    agent = BlastRadiusAgent(client=fc)
    warnings: list[str] = []
    facts = agent.gather(Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="c"),
                         resolved(), warnings=warnings)
    assert facts.downstream == []
    assert any("downstream" in w and "analytics.order_details" in w for w in warnings)
    # the other fetches still ran
    assert {"usage", "owners", "queries_for_column"} <= {c[0] for c in fc.calls}


def test_gather_memoizes_shared_urn():
    fc = FakeClient(downstream={DS: dashboards(2)})
    agent = BlastRadiusAgent(client=fc)
    cache: dict = {}
    for col in ("a", "b"):
        agent.gather(Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column=col),
                     resolved(), cache=cache)
    assert sum(1 for c in fc.calls if c[0] == "downstream") == 1
    assert sum(1 for c in fc.calls if c[0] == "usage") == 1


# ------------------------------------------------------------- review() E2E
def ddl(sql):
    return FileChange(path="migrations/001.sql", new_content=sql, status=FileStatus.ADDED)


def usage_with(field_counts, total=0, users=0):
    return Usage(dataset_urn=DS, unique_users=users, total_queries=total, top_queries=(),
                 user_counts=(), field_counts=field_counts)


def test_review_hard_break_scenario():
    fc = FakeClient(
        downstream={DS: dashboards(3)},
        usage={DS: usage_with({"discount_amount": 11}, total=19, users=5)},
        owners={DS: [Owner("urn:li:corpGroup:finance", "corpGroup", name="finance-team")]},
        q_col={(DS, "discount_amount"): [qref("Daily revenue"), qref("Net margin")]},
    )
    report = BlastRadiusAgent(client=fc).review(
        [ddl("ALTER TABLE analytics.order_details DROP COLUMN discount_amount;")])
    assert report.verdict is Verdict.BREAK
    assert "❌" in report.markdown
    assert report.warnings == []


def test_review_clean_pass_scenario():
    fc = FakeClient(downstream={DS: dashboards(3)},
                    usage={DS: usage_with({"discount_amount": 11})})
    report = BlastRadiusAgent(client=fc).review(
        [ddl("ALTER TABLE analytics.order_details DROP COLUMN gift_wrap;")])
    assert report.verdict is Verdict.PASS
    assert "✅" in report.markdown


def test_review_empty_changes_is_pass():
    report = BlastRadiusAgent(client=FakeClient()).review([])
    assert report.verdict is Verdict.PASS
    assert report.assessments == []


def test_review_raises_on_total_outage():
    fc = FakeClient(fail={"dataset_urns"})
    with pytest.raises(DataHubUnavailable):
        BlastRadiusAgent(client=fc).review(
            [ddl("ALTER TABLE analytics.order_details DROP COLUMN discount_amount;")])


def test_review_surfaces_fetch_warnings_but_still_reports():
    fc = FakeClient(fail={"downstream"}, usage={DS: usage_with({"discount_amount": 11})},
                    q_col={(DS, "discount_amount"): [qref("q1")]})
    report = BlastRadiusAgent(client=fc).review(
        [ddl("ALTER TABLE analytics.order_details DROP COLUMN discount_amount;")])
    assert report.warnings  # a downstream failure was recorded
    assert report.markdown  # comment still produced


# ------------------------------------------------------------- live DataHub
@pytest.mark.integration
def test_review_hard_break_live_datahub():
    """End-to-end against a live, seeded DataHub. Auto-skips if unreachable."""
    agent = BlastRadiusAgent()
    try:
        urns = agent.client.dataset_urns()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DataHub not reachable: {exc}")
    if not any("order_details" in u for u in urns):
        pytest.skip("DataHub reachable but demo data not seeded")

    report = agent.review(
        [ddl("ALTER TABLE analytics.order_details DROP COLUMN discount_amount;")])
    assert report.verdict is Verdict.BREAK
    assert "❌" in report.markdown


class FakeContext:
    def __init__(self, *, down=None, fail_down=False):
        self._down = down or []
        self._fail = fail_down
        self.docs = []
        self.tags = []
        self.ensured = []
    def downstream(self, urn, **k):
        if self._fail:
            raise RuntimeError("kit down")
        return self._down
    def ensure_tag(self, tag_urn, **k): self.ensured.append(tag_urn)
    def write_assessment(self, urn, **k): self.docs.append((urn, k)); return "urn:li:document:1"
    def tag_change(self, urn, cols, tag_urn): self.tags.append((urn, cols, tag_urn)); return list(cols)


def test_gather_uses_kit_downstream_when_context_present():
    fc = FakeClient(q_col={(DS, "discount_amount"): [qref("q1")]})
    ctx = FakeContext(down=dashboards(3))
    agent = BlastRadiusAgent(client=fc, context_client=ctx)
    facts = agent.gather(Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="discount_amount"),
                         resolved())
    assert len(facts.downstream) == 3            # came from the Kit
    assert "downstream" not in {c[0] for c in fc.calls}  # SDK downstream not called


def test_gather_falls_back_to_sdk_when_kit_downstream_fails():
    fc = FakeClient(downstream={DS: dashboards(2)}, q_col={(DS, "c"): []})
    ctx = FakeContext(fail_down=True)
    agent = BlastRadiusAgent(client=fc, context_client=ctx)
    warnings: list[str] = []
    facts = agent.gather(Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="c"),
                         resolved(), warnings=warnings)
    assert len(facts.downstream) == 2 and any("lineage" in w.lower() or "kit" in w.lower() for w in warnings)


def test_review_writes_back_when_enabled():
    fc = FakeClient(usage={DS: usage_with({"discount_amount": 11})},
                    q_col={(DS, "discount_amount"): [qref("Daily revenue")]})
    ctx = FakeContext(down=dashboards(3))
    agent = BlastRadiusAgent(client=fc, context_client=ctx, write_back=True)
    report = agent.review([ddl("ALTER TABLE analytics.order_details DROP COLUMN discount_amount;")])
    assert report.writeback is not None and report.writeback.document_urn == "urn:li:document:1"
    assert "discount_amount" in report.writeback.tagged_columns
    assert ctx.ensured and ctx.docs and ctx.tags       # tag ensured, doc saved, column tagged


def test_review_no_writeback_when_disabled():
    agent = BlastRadiusAgent(client=FakeClient(), context_client=FakeContext(), write_back=False)
    report = agent.review([ddl("ALTER TABLE analytics.order_details DROP COLUMN gift_wrap;")])
    assert report.writeback is None
