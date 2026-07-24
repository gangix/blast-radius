"""Unit tests for the deterministic severity model (no DataHub)."""

from __future__ import annotations

from blast_radius import (
    Change,
    ChangeKind,
    ImpactFacts,
    LineageNode,
    QueryRef,
    ResolvedTable,
    Usage,
    Verdict,
    assess,
)


def resolved(name: str = "order_entry_db.analytics.order_details") -> ResolvedTable:
    urn = f"urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.{name},PROD)"
    return ResolvedTable(raw=name, urn=urn, matched_name=name, platform="snowflake",
                         score=1.0, exact=True, candidates=())


def dashboards(n: int) -> list[LineageNode]:
    return [LineageNode(f"urn:li:dashboard:(tableau,d{i})", "DASHBOARD", 3, f"Dashboard {i}")
            for i in range(n)]


def query(name: str, author: str, *cols: str) -> QueryRef:
    ds = resolved().urn
    return QueryRef(urn=f"urn:li:query:{name}", name=name, description="", sql="SELECT ...",
                    author=author, datasets=frozenset({ds}),
                    columns=frozenset((ds, c) for c in cols))


def usage(field_counts: dict[str, int], total: int = 0, users: int = 0) -> Usage:
    return Usage(dataset_urn=resolved().urn, unique_users=users, total_queries=total,
                 top_queries=(), user_counts=(), field_counts=field_counts)


# ------------------------------------------------------------- the 3 scenarios
def test_hard_break_drop_hot_column():
    facts = ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="discount_amount"),
        resolved=resolved(),
        downstream=dashboards(3),
        usage=usage({"discount_amount": 11}, total=19, users=5),
        breaking_queries=[query("Daily revenue by category", "sarah", "discount_amount"),
                          query("Net margin after discounts", "james", "discount_amount")],
    )
    a = assess(facts)
    assert a.verdict is Verdict.BREAK
    assert a.emoji == "❌"
    assert a.signals.query_volume_per_day == 11
    assert "discount_amount" in " ".join(a.reasons)


def test_warning_moderate_column():
    facts = ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="warehouse_name"),
        resolved=resolved(),
        downstream=dashboards(1),
        usage=usage({"warehouse_name": 2}),
        breaking_queries=[query("Delivery SLA breach rate", "andrea", "warehouse_name")],
    )
    a = assess(facts)
    assert a.verdict is Verdict.WARN
    assert a.emoji == "⚠️"


def test_clean_pass_unqueried_column():
    facts = ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "analytics.order_details", column="gift_wrap"),
        resolved=resolved(),
        downstream=dashboards(3),          # table feeds dashboards...
        usage=usage({"discount_amount": 11}),  # ...but nothing reads gift_wrap
        breaking_queries=[],
    )
    a = assess(facts)
    assert a.verdict is Verdict.PASS, "an unqueried column must pass even on a popular table"
    assert a.score == 0.0


# ------------------------------------------------------------- escalation logic
def test_break_by_query_count_even_if_low_volume():
    facts = ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "t", column="c"),
        resolved=resolved(),
        breaking_queries=[query(f"q{i}", f"u{i}", "c") for i in range(3)],  # 3 queries -> broad
        usage=usage({"c": 1}),
    )
    assert assess(facts).verdict is Verdict.BREAK


def test_break_by_user_breadth():
    facts = ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "t", column="c"),
        resolved=resolved(),
        breaking_queries=[query("q1", "a", "c"), query("q2", "b", "c"),
                          # same query name repeats but 4 distinct authors overall
                          query("q3", "cc", "c"), query("q4", "d", "c")],
        usage=usage({"c": 1}),
    )
    assert assess(facts).verdict is Verdict.BREAK


# ------------------------------------------------------------- other kinds
def test_additive_add_column_passes():
    a = assess(ImpactFacts(
        change=Change(ChangeKind.ADD_COLUMN, "orders", column="loyalty_tier"),
        resolved=resolved("order_entry_db.order_entry.orders"),
        downstream=dashboards(3),
    ))
    assert a.verdict is Verdict.PASS
    assert "Additive" in a.reasons[0]


def test_unresolved_table_passes_with_caveat():
    a = assess(ImpactFacts(
        change=Change(ChangeKind.DROP_COLUMN, "mystery_table", column="x"),
        resolved=None,
    ))
    assert a.verdict is Verdict.PASS
    assert a.confidence == "low"
    assert "not found" in " ".join(a.reasons).lower()


def test_drop_table_with_consumers_breaks():
    a = assess(ImpactFacts(
        change=Change(ChangeKind.DROP_TABLE, "analytics.order_details"),
        resolved=resolved(),
        downstream=dashboards(3),
        usage=usage({}, total=40),
        breaking_queries=[query("q", "sarah")],
    ))
    assert a.verdict is Verdict.BREAK


def test_logic_change_caps_at_warn():
    a = assess(ImpactFacts(
        change=Change(ChangeKind.LOGIC_CHANGE, "order_details", confidence="medium"),
        resolved=resolved(),
        downstream=dashboards(3),
        usage=usage({}, total=40),
    ))
    assert a.verdict is Verdict.WARN  # never BREAK — we can't prove it broke
    assert a.confidence == "medium"


def test_type_change_flags_corruption_when_hot():
    a = assess(ImpactFacts(
        change=Change(ChangeKind.ALTER_COLUMN_TYPE, "analytics.order_details",
                      column="order_total", new="NUMBER(38,4)"),
        resolved=resolved(),
        usage=usage({"order_total": 15}),
        breaking_queries=[query("aov", "sarah", "order_total")],
    ))
    assert a.verdict is Verdict.BREAK
    assert any("corrupt" in r for r in a.reasons)
