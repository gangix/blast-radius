from __future__ import annotations

import dataclasses

from blast_radius import Change, ChangeKind, Verdict
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
