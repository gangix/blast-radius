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
