from __future__ import annotations

from blast_radius import (
    Change,
    ChangeKind,
    ImpactFacts,
    Owner,
    QueryRef,
    ResolvedTable,
    Usage,
    Verdict,
    assess,
)
from blast_radius.writeback import TAGS, render_document

DS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.analytics.order_details,PROD)"


def _resolved():
    return ResolvedTable(raw="analytics.order_details", urn=DS, matched_name="analytics.order_details",
                         platform="snowflake", score=1.0, exact=True, candidates=())


def _q(name):
    return QueryRef(urn=f"urn:li:query:{name}", name=name, description="", sql="SELECT 1",
                    author="sarah", datasets=frozenset({DS}), columns=frozenset())


def _break_assessment():
    return assess(ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="discount_amount"),
        resolved=_resolved(),
        usage=Usage(DS, unique_users=5, total_queries=19, top_queries=(), user_counts=(),
                    field_counts={"discount_amount": 11}),
        breaking_queries=[_q("Daily revenue"), _q("Net margin")],
        owners=[Owner("urn:li:corpGroup:finance", "corpGroup", name="finance-team")]))


def test_render_document_break():
    title, body = render_document(_break_assessment(), pr_ref="acme/demo#4")
    assert "Breaking change" in title and "discount_amount" in title
    assert "❌" in body
    assert "Daily revenue" in body and "Net margin" in body      # the real breaking queries
    assert "acme/demo#4" in body                                 # PR link/ref
    assert "Deterministic" in body                               # provenance footer


def test_tags_cover_break_and_warn():
    assert set(TAGS) == {Verdict.BREAK, Verdict.WARN}
    for v in (Verdict.BREAK, Verdict.WARN):
        urn, name, desc = TAGS[v]
        assert urn.startswith("urn:li:tag:") and name and desc
