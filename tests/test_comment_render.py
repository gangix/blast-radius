from __future__ import annotations

import dataclasses

from blast_radius import Change, ChangeKind, LineageNode, Verdict
from blast_radius.comment import render_comment
from blast_radius.severity import ImpactFacts, assess


def pass_assessment(column="gift_wrap"):
    return assess(ImpactFacts(change=Change(ChangeKind.ADD_COLUMN, "orders", column=column),
                              resolved=None))


def test_render_has_marker_header_and_footer():
    out = render_comment([pass_assessment()])
    assert out.startswith("<!-- blast-radius:v1 -->")
    assert "## ✅ Blast Radius — No downstream impact" in out
    assert out.rstrip().endswith(
        "_Deterministic analysis from DataHub lineage + 30-day query history._"
    )


def test_render_section_lists_reasons_as_bullets():
    a = pass_assessment()
    out = render_comment([a])
    assert "### ✅ Add column `gift_wrap`" in out
    for reason in a.reasons:
        assert f"- {reason}" in out


def test_overall_verdict_is_worst_of():
    a = pass_assessment()
    brk = dataclasses.replace(a, verdict=Verdict.BREAK)
    out = render_comment([a, brk])
    assert "## ❌ Blast Radius — Breaking change" in out


def test_pass_section_collapses_when_not_all_pass():
    a = pass_assessment("gift_wrap")
    brk = dataclasses.replace(a, verdict=Verdict.BREAK)
    out = render_comment([a, brk])
    assert "<details>" in out
    assert "<summary>✅ Add column `gift_wrap`</summary>" in out


def test_all_pass_pr_has_no_collapse():
    out = render_comment([pass_assessment("a"), pass_assessment("b")])
    assert "<details>" not in out
    assert "### ✅ Add column `a`" in out


from blast_radius import Owner, QueryRef


def query(name, author, sql="SELECT 1"):
    return QueryRef(urn=f"urn:li:query:{name}", name=name, description="", sql=sql,
                    author=author, datasets=frozenset(), columns=frozenset())


def break_assessment_with_queries():
    a = pass_assessment("discount_amount")
    return dataclasses.replace(
        a,
        verdict=Verdict.BREAK,
        breaking_queries=[query("Daily revenue", "sarah"), query("Net margin", "james")],
        owners=[Owner("urn:li:corpGroup:finance", "corpGroup", name="finance-team"),
                Owner("urn:li:corpGroup:finance", "corpGroup", name="finance-team")],  # dup
    )


def test_breaking_queries_table_has_only_query_and_author():
    out = render_comment([break_assessment_with_queries()])
    assert "**Breaking queries**" in out
    assert "| Query | Author |" in out
    assert "| Daily revenue | sarah |" in out
    assert "reads/day" not in out.split("**Breaking queries**")[1].split("<details>")[0]


def test_query_sql_in_nested_details():
    out = render_comment([break_assessment_with_queries()])
    assert "<summary>SQL — Daily revenue</summary>" in out
    assert "```sql" in out


def test_owners_are_plain_text_deduped_no_at_sign():
    out = render_comment([break_assessment_with_queries()])
    assert "**Owners (from DataHub):** finance-team" in out
    assert "@finance-team" not in out
    assert out.count("finance-team") == 1  # deduped by urn


def test_owners_with_null_name_never_surfaces_email():
    """When an owner has name=None and email set, owners line uses URN tail, not email."""
    a = pass_assessment("sensitive_field")
    owners_with_email = [
        Owner("urn:li:corpuser:jdoe", "corpuser", name=None, email="jdoe@example.com"),
    ]
    a = dataclasses.replace(a, verdict=Verdict.WARN, owners=owners_with_email)
    out = render_comment([a])

    # Extract the owners line from the output
    owners_line = next(line for line in out.split("\n") if "**Owners (from DataHub):**" in line)

    # Must not contain @ anywhere
    assert "@" not in owners_line, f"Owners line contains @: {owners_line}"
    # Must contain the URN tail (last colon-segment)
    assert "jdoe" in owners_line, f"URN tail 'jdoe' not in owners line: {owners_line}"


from blast_radius.severity import ImpactSignals


def with_signals(a, **kw):
    base = {
        "breaking_queries": 0,
        "query_volume_per_day": 0,
        "dashboards": 0,
        "charts": 0,
        "total_downstream": 0,
        "breaking_query_users": 0,
    }
    base.update(kw)
    return dataclasses.replace(a, signals=ImpactSignals(**base))


def test_single_change_has_no_table():
    out = render_comment([pass_assessment()])
    assert "| Change | Verdict | Impact |" not in out


def test_multi_change_table_ranks_and_scopes_columns():
    # a hot column drop (score high) + a clean column add (score 0)
    hot = with_signals(
        dataclasses.replace(
            pass_assessment("discount_amount"),
            change=Change(ChangeKind.DROP_COLUMN, "order_details", column="discount_amount"),
            verdict=Verdict.BREAK, score=90.0),
        breaking_queries=2, query_volume_per_day=11, dashboards=3)
    calm = with_signals(pass_assessment("gift_wrap"), dashboards=3)  # table has dashboards...
    out = render_comment([calm, hot])  # deliberately unordered
    table = out.split("| Change | Verdict | Impact |")[1]
    # ranked: hot (score 90) before calm (score 0)
    assert table.index("discount_amount") < table.index("gift_wrap")
    # Fix #1: the clean column row must NOT advertise the table's 3 dashboards
    calm_row = next(ln for ln in table.splitlines() if "gift_wrap" in ln)
    assert "dashboard" not in calm_row
    # the hot column row shows column-scoped impact
    hot_row = next(ln for ln in table.splitlines() if "discount_amount" in ln)
    assert "2 queries" in hot_row and "11 reads/day" in hot_row


def test_impact_cell_table_change_may_use_downstream():
    drop_tbl = with_signals(
        dataclasses.replace(pass_assessment(),
                            change=Change(ChangeKind.DROP_TABLE, "order_details"),
                            verdict=Verdict.BREAK, score=50.0),
        total_downstream=37, dashboards=3)
    other = pass_assessment("x")
    out = render_comment([drop_tbl, other])
    row = next(ln for ln in out.splitlines() if "Drop table" in ln)
    assert "37 downstream" in row and "3 dashboards" in row


def test_affected_assets_render_as_clickable_links():
    # break_assessment_with_queries() is an ADD_COLUMN change -> a COLUMN kind,
    # so the consumers header is the scoped "Downstream of ..." form, not
    # "Affected assets:" (see test_consumers_header_scoped_by_change_kind).
    a = dataclasses.replace(
        break_assessment_with_queries(),
        downstream_consumers=[LineageNode("urn:li:dashboard:(tableau,d0)", "DASHBOARD", 3,
                                          "Finance Overview")],
    )
    out = render_comment([a])
    assert "**Downstream of `orders`** (table-level; field bindings not verified):" in out
    assert ("[Finance Overview]"
            "(https://datahub.example.com/dashboard/"
            "urn%3Ali%3Adashboard%3A%28tableau%2Cd0%29)") in out


def test_breaking_query_name_with_pipe_is_escaped():
    a = dataclasses.replace(
        pass_assessment("discount_amount"),
        verdict=Verdict.BREAK,
        breaking_queries=[query("Daily revenue | EMEA", "sarah")],
    )
    out = render_comment([a])
    assert "Daily revenue \\| EMEA" in out
    # The row must still have exactly the two data columns -- no phantom
    # column from the raw, unescaped "|" in the query name.
    row = next(ln for ln in out.splitlines() if "Daily revenue" in ln and ln.startswith("|"))
    assert row == "| Daily revenue \\| EMEA | sarah |"


def test_consumers_header_scoped_by_change_kind():
    dashboard = LineageNode("urn:li:dashboard:(tableau,d0)", "DASHBOARD", 3, "Finance Overview")

    column_change = dataclasses.replace(
        pass_assessment("discount_amount"),
        verdict=Verdict.WARN,
        downstream_consumers=[dashboard],
    )
    out = render_comment([column_change])
    assert "**Downstream of `orders`** (table-level; field bindings not verified):" in out
    assert "**Affected assets:**" not in out

    table_change = dataclasses.replace(
        pass_assessment(),
        change=Change(ChangeKind.DROP_TABLE, "analytics.order_details"),
        verdict=Verdict.BREAK,
        downstream_consumers=[dashboard],
    )
    out = render_comment([table_change])
    assert "**Affected assets:**" in out
    assert "**Downstream of" not in out
