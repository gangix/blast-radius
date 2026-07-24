# tests/scenarios.py — shared fixture builders for comment golden tests.
# Not collected by pytest (no `test_` prefix); importable because pytest puts
# the tests/ dir on sys.path.
from __future__ import annotations

from blast_radius import (
    Change,
    ChangeKind,
    ImpactFacts,
    LineageNode,
    Owner,
    QueryRef,
    ResolvedTable,
    Usage,
    assess,
)

DS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.analytics.order_details,PROD)"


def _resolved(name="analytics.order_details"):
    return ResolvedTable(raw=name, urn=DS, matched_name=name, platform="snowflake",
                         score=1.0, exact=True, candidates=())


def _dashboards(n):
    return [LineageNode(f"urn:li:dashboard:(tableau,d{i})", "DASHBOARD", 3, f"Dashboard {i}")
            for i in range(n)]


def _query(name, author, *cols, sql="SELECT ...\nFROM order_details"):
    return QueryRef(urn=f"urn:li:query:{name.lower().replace(' ', '_')}", name=name,
                    description="", sql=sql, author=author, datasets=frozenset({DS}),
                    columns=frozenset((DS, c) for c in cols))


def _usage(field_counts, total=0, users=0):
    return Usage(dataset_urn=DS, unique_users=users, total_queries=total, top_queries=(),
                 user_counts=(), field_counts=field_counts)


def hard_break():
    return assess(ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="discount_amount"),
        resolved=_resolved(), downstream=_dashboards(3),
        usage=_usage({"discount_amount": 11}, total=19, users=5),
        breaking_queries=[_query("Daily revenue by category", "sarah", "discount_amount"),
                          _query("Net margin after discounts", "james", "discount_amount")],
        owners=[Owner("urn:li:corpGroup:finance", "corpGroup", name="finance-team")]))


def warning():
    return assess(ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="warehouse_name"),
        resolved=_resolved(), downstream=_dashboards(1),
        usage=_usage({"warehouse_name": 2}),
        breaking_queries=[_query("Delivery SLA breach rate", "andrea", "warehouse_name")]))


def clean_pass():
    return assess(ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="gift_wrap"),
        resolved=_resolved(), downstream=_dashboards(3),
        usage=_usage({"discount_amount": 11}), breaking_queries=[]))
